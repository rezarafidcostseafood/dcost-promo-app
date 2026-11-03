import io
import json
import os
import secrets
import threading
import time
import uuid
import datetime as dt
from functools import wraps

import numpy as np
from flask import Flask, g, session, request, redirect, url_for, render_template, flash, abort, send_file, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

import charts
import db as dbm
import engine
import master_io
import rmload
import views

ROLES = ('viewer', 'editor', 'admin')
JOBS = {}
_LOCK = threading.Lock()
_MD = {}
_RES = {}
_FAILS = {}


def create_app(test_config=None):
    app = Flask(__name__)
    base = os.environ.get('DATA_DIR') or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
    if test_config and test_config.get('DATA_DIR'):
        base = test_config['DATA_DIR']
    os.makedirs(os.path.join(base, 'rm'), exist_ok=True)
    os.makedirs(os.path.join(base, 'tmp'), exist_ok=True)
    app.config.update(DATA_DIR=base, DB_PATH=os.path.join(base, 'app.db'), MAX_CONTENT_LENGTH=int(os.environ.get('MAX_UPLOAD_MB', '300')) * 1024 * 1024,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE', '0') == '1',
                      PERMANENT_SESSION_LIFETIME=dt.timedelta(hours=int(os.environ.get('SESSION_HOURS', '12'))))
    kf = os.path.join(base, 'secret.key')
    if os.environ.get('SECRET_KEY'):
        app.secret_key = os.environ['SECRET_KEY']
    else:
        if not os.path.exists(kf):
            with open(kf, 'w') as f:
                f.write(secrets.token_hex(32))
        app.secret_key = open(kf).read().strip()
    if test_config:
        app.config.update({k: v for k, v in test_config.items() if k != 'DATA_DIR'})
    dbm.init_db(app.config['DB_PATH'])
    app.teardown_appcontext(dbm.close_db)

    # ---- bootstrap admin
    c = dbm.connect(app.config['DB_PATH'])
    if c.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0:
        em = (os.environ.get('ADMIN_EMAIL') or '').strip().lower()
        if em:
            pw = os.environ.get('ADMIN_PASSWORD') or secrets.token_urlsafe(9)
            c.execute('INSERT INTO users(email,name,role,pw_hash,must_change,created_at) VALUES(?,?,?,?,?,?)',
                      (em, 'Admin', 'admin', generate_password_hash(pw), 0 if os.environ.get('ADMIN_PASSWORD') else 1, dt.datetime.now().isoformat()))
            c.commit()
            if not os.environ.get('ADMIN_PASSWORD'):
                print(f'[SETUP] Admin dibuat: {em} / kata sandi sementara: {pw}  (wajib diganti saat login pertama)')
    c.close()

    # ---------------------------------------------------------------- util
    def me():
        if 'me' not in g:
            g.me = None
            uid = session.get('uid')
            if uid:
                r = dbm.get_db().execute('SELECT * FROM users WHERE id=? AND active=1', (uid,)).fetchone()
                g.me = dict(r) if r else None
        return g.me

    def need(role='viewer'):
        def deco(fn):
            @wraps(fn)
            def w(*a, **k):
                u = me()
                if not u:
                    return redirect(url_for('login', next=request.path))
                if u['must_change'] and request.endpoint not in ('password', 'logout'):
                    return redirect(url_for('password'))
                if ROLES.index(u['role']) < ROLES.index(role):
                    abort(403)
                return fn(*a, **k)
            return w
        return deco

    @app.before_request
    def csrf():
        if request.method == 'POST':
            tok = session.get('csrf')
            if not tok or not secrets.compare_digest(tok, request.form.get('csrf', '')):
                abort(400, 'Token keamanan tidak valid. Muat ulang halaman lalu coba lagi.')

    @app.after_request
    def hdr(r):
        r.headers['X-Frame-Options'] = 'DENY'
        r.headers['X-Content-Type-Options'] = 'nosniff'
        r.headers['Referrer-Policy'] = 'same-origin'
        r.headers['Cache-Control'] = 'no-store'
        return r

    @app.context_processor
    def ctx():
        if 'csrf' not in session:
            session['csrf'] = secrets.token_hex(16)
        return dict(me=me(), csrf=session['csrf'], charts=charts, kfmt=lambda v: f'{v * 100:.1f}%'.replace('.', ','))

    @app.template_filter('rp')
    def rp(v):
        if v is None or v == '':
            return '-'
        return f'{v:,.0f}'.replace(',', '.')

    @app.template_filter('pct')
    def pct(v, d=1):
        if v is None or isinstance(v, str):
            return v if isinstance(v, str) else 'n/a'
        return f'{v * 100:.{d}f}%'.replace('.', ',')

    @app.template_filter('slice_labels')
    def slice_labels(v):
        out = []
        for x in v:
            out.append(dt.date.fromisoformat(x).strftime('%b %y'))
        return out

    @app.template_filter('tgl')
    def tgl(v):
        return v.strftime('%d-%b-%Y') if v else ''

    @app.template_filter('num1')
    def num1(v):
        return 'n/a' if v is None else f'{v:,.1f}'.replace(',', 'X').replace('.', ',').replace('X', '.')

    def month_arg():
        ms = dbm.months_list(dbm.get_db())
        key = request.args.get('bulan') or (ms[-1]['month'] if ms else None)
        return key, ms

    def mdate(key):
        return dt.date(int(key[:4]), int(key[5:7]), 1)

    def get_md(key, settings):
        stamp = None
        r = dbm.get_db().execute('SELECT uploaded_at FROM months WHERE month=?', (key,)).fetchone()
        if not r:
            return None
        k = (key, r['uploaded_at'], settings['floor'])
        with _LOCK:
            if k not in _MD:
                for old in [x for x in _MD if x[0] == key]:
                    _MD.pop(old)
                rm = rmload.load_rm(os.path.join(app.config['DATA_DIR'], 'rm', key + '.npz'))
                _MD[k] = (engine.MonthData(rm, settings['floor']), int(rm['qty'].shape[0]))
            return _MD[k]

    def get_res(key):
        c = dbm.get_db()
        st = dbm.get_settings(c)
        k = (key, st['ver'])
        with _LOCK:
            if k in _RES:
                return _RES[k]
        got = get_md(key, st)
        if got is None:
            return None
        md, nrows = got
        master, cogs = dbm.load_master(c)
        res = engine.analyze(mdate(key), md, master, st, cogs)
        val = dict(res=res, md=md, nrows=nrows, master=master, cogs=cogs, st=st)
        with _LOCK:
            for old in [x for x in _RES if x[0] == key]:
                _RES.pop(old)
            _RES[k] = val
        return val

    # ---------------------------------------------------------------- auth
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            em = request.form.get('email', '').strip().lower()
            ip = request.remote_addr
            now = time.time()
            fails = [t for t in _FAILS.get((em, ip), []) if now - t < 900]
            if len(fails) >= 5:
                flash('Terlalu banyak percobaan gagal. Coba lagi 15 menit lagi.', 'err')
                return render_template('login.html'), 429
            u = dbm.get_db().execute('SELECT * FROM users WHERE email=? AND active=1', (em,)).fetchone()
            if u and check_password_hash(u['pw_hash'], request.form.get('password', '')):
                session.clear()
                session['uid'] = u['id']
                session['csrf'] = secrets.token_hex(16)
                session.permanent = True
                dbm.get_db().execute('UPDATE users SET last_login=? WHERE id=?', (dt.datetime.now().isoformat(timespec='seconds'), u['id']))
                dbm.get_db().commit()
                _FAILS.pop((em, ip), None)
                nxt = request.args.get('next') or url_for('ringkasan')
                return redirect(nxt if nxt.startswith('/') and not nxt.startswith('//') else url_for('ringkasan'))
            fails.append(now)
            _FAILS[(em, ip)] = fails
            flash('Email atau kata sandi salah, atau akun tidak aktif.', 'err')
        return render_template('login.html')

    @app.route('/logout', methods=['POST'])
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.route('/password', methods=['GET', 'POST'])
    @need('viewer')
    def password():
        if request.method == 'POST':
            u = me()
            old, new, new2 = request.form.get('old', ''), request.form.get('new', ''), request.form.get('new2', '')
            if not check_password_hash(u['pw_hash'], old):
                flash('Kata sandi lama salah.', 'err')
            elif len(new) < 8:
                flash('Kata sandi baru minimal 8 karakter.', 'err')
            elif new != new2:
                flash('Konfirmasi kata sandi tidak sama.', 'err')
            else:
                dbm.get_db().execute('UPDATE users SET pw_hash=?, must_change=0 WHERE id=?', (generate_password_hash(new), u['id']))
                dbm.get_db().commit()
                flash('Kata sandi diganti.', 'ok')
                return redirect(url_for('ringkasan'))
        return render_template('password.html')

    # ---------------------------------------------------------------- analisa
    @app.route('/')
    @need()
    def home():
        return redirect(url_for('ringkasan'))

    @app.route('/ringkasan')
    @need()
    def ringkasan():
        key, ms = month_arg()
        if not key:
            return render_template('kosong.html')
        v = get_res(key)
        if v is None:
            abort(404)
        promos = v['res']['promos']
        cnt = {}
        for p in promos:
            k = p['verdict'].split(' (')[0]
            cnt[k] = cnt.get(k, 0) + 1
        warn = [c for c in views.checks(v['md'], v['res'], v['master'], v['cogs'], v['st'], v['nrows']) if c['status'] == 'PERIKSA']
        chart_sales = [(f"{p['id']} {p['nama']}", p['sales']) for p in promos]
        chart_kontrib = [(f"{p['id']} {p['nama']}", p['kontrib']) for p in promos]
        return render_template('ringkasan.html', key=key, ms=ms, promos=promos, cnt=cnt, warn=warn, st=v['st'], chart_sales=chart_sales, chart_kontrib=chart_kontrib)

    @app.route('/promo/<pid>')
    @need()
    def promo(pid):
        key, ms = month_arg()
        v = get_res(key) if key else None
        if v is None:
            abort(404)
        det = views.promo_detail(v['res'], v['md'], pid, v['st'])
        p = next((x for x in v['res']['promos'] if x['id'] == pid), None)
        if det is None or p is None:
            flash('Promo tidak aktif di bulan ini.', 'err')
            return redirect(url_for('ringkasan', bulan=key))
        return render_template('promo.html', key=key, ms=ms, p=p, d=det)

    @app.route('/profit')
    @need()
    def profit():
        key, ms = month_arg()
        v = get_res(key) if key else None
        if v is None:
            return render_template('kosong.html')
        return render_template('profit.html', key=key, ms=ms, promos=v['res']['promos'])

    @app.route('/perbandingan')
    @need()
    def perbandingan():
        c = dbm.get_db()
        ms = dbm.months_list(c)
        if not ms:
            return render_template('kosong.html')
        st = dbm.get_settings(c)
        base = request.args.get('mulai') or ms[0]['month']
        metric = request.args.get('metrik', 'perhari')
        master, _ = dbm.load_master(c)
        infos = {}
        for m in ms:
            k = (m['month'], 'tot', m['uploaded_at'], st['floor'], st['ver'])
            with _LOCK:
                hit = _RES.get(k)
            if hit is None:
                md, _n = get_md(m['month'], st)
                hit = views.month_totals(md, mdate(m['month']), master['lines'], st['src_single'])
                with _LOCK:
                    _RES[k] = hit
            infos[mdate(m['month'])] = hit
        months, rows = views.perbandingan(infos, master['lines'], mdate(base))
        sel = request.args.get('promo') or (rows[0]['id'] if rows else '')
        # hanya promo yang punya data di salah satu bulan
        rows = [r for r in rows if any(x['hari'] for x in r['m'])]
        selrow = next((r for r in rows if r['id'] == sel), rows[0] if rows else None)
        return render_template('perbandingan.html', ms=ms, base=base, months=months, rows=rows, metric=metric, sel=selrow)

    @app.route('/cek')
    @need()
    def cek():
        key, ms = month_arg()
        v = get_res(key) if key else None
        if v is None:
            return render_template('kosong.html')
        return render_template('cek.html', key=key, ms=ms, items=views.checks(v['md'], v['res'], v['master'], v['cogs'], v['st'], v['nrows']))

    # ---------------------------------------------------------------- data RM
    def process_upload(path, month, filename, email):
        jid = JOBS_CUR[path]
        cc = dbm.connect(app.config['DB_PATH'])
        try:
            JOBS[jid].update(msg='Membaca file Excel (bisa 1-3 menit)...')
            df = rmload.parse_xlsx(path)
            rm = rmload.df_to_rm(df)
            del df
            y, m = int(month[:4]), int(month[5:7])
            D = engine.days_in(dt.date(y, m, 1))
            if rm['D'] != D:
                raise ValueError(f'File punya {rm["D"]} kolom tanggal, tapi bulan {month} seharusnya {D} hari. Pastikan bulan yang dipilih benar.')
            st = dbm.get_settings(cc)
            if not (rm['florr'] == st['floor']).any():
                raise ValueError(f'Floor "{st["floor"]}" tidak ada di file. Floor yang ada: {sorted(set(rm["florr"].tolist()))[:6]}')
            rmload.save_rm(os.path.join(app.config['DATA_DIR'], 'rm', month + '.npz'), rm)
            cc.execute('INSERT INTO months(month,filename,nrows,days,uploaded_by,uploaded_at) VALUES(?,?,?,?,?,?) ON CONFLICT(month) DO UPDATE SET '
                       'filename=excluded.filename,nrows=excluded.nrows,days=excluded.days,uploaded_by=excluded.uploaded_by,uploaded_at=excluded.uploaded_at',
                       (month, filename, int(rm['qty'].shape[0]), D, email, dt.datetime.now().isoformat(timespec='seconds')))
            dbm.bump(cc)
            cc.commit()
            JOBS[jid].update(status='ok', msg=f'Selesai: {rm["qty"].shape[0]:,} baris data bulan {month} tersimpan.'.replace(',', '.'))
        except Exception as e:
            JOBS[jid].update(status='error', msg=f'Gagal: {e}')
        finally:
            cc.close()
            try:
                os.remove(path)
            except OSError:
                pass

    JOBS_CUR = {}

    @app.route('/data', methods=['GET', 'POST'])
    @need('editor')
    def data():
        c = dbm.get_db()
        if request.method == 'POST':
            f = request.files.get('file')
            month = request.form.get('bulan', '')
            if not f or not f.filename.lower().endswith('.xlsx') or len(month) != 7:
                flash('Pilih bulan dan file Excel (.xlsx) data RM.', 'err')
                return redirect(url_for('data'))
            jid = uuid.uuid4().hex[:10]
            path = os.path.join(app.config['DATA_DIR'], 'tmp', jid + '.xlsx')
            f.save(path)
            JOBS[jid] = dict(status='run', msg='Mengunggah...')
            JOBS_CUR[path] = jid
            threading.Thread(target=process_upload, args=(path, month, f.filename, me()['email']), daemon=True).start()
            return redirect(url_for('job', jid=jid))
        return render_template('data.html', ms=dbm.months_list(c), st=dbm.get_settings(c))

    @app.route('/data/job/<jid>')
    @need('editor')
    def job(jid):
        return render_template('job.html', jid=jid, j=JOBS.get(jid, dict(status='error', msg='Proses tidak ditemukan (server di-restart?).')))

    @app.route('/data/job/<jid>/status')
    @need('editor')
    def job_status(jid):
        return jsonify(JOBS.get(jid, dict(status='error', msg='Proses tidak ditemukan.')))

    @app.route('/data/hapus', methods=['POST'])
    @need('editor')
    def data_hapus():
        month = request.form.get('bulan', '')
        c = dbm.get_db()
        c.execute('DELETE FROM months WHERE month=?', (month,))
        dbm.bump(c)
        c.commit()
        try:
            os.remove(os.path.join(app.config['DATA_DIR'], 'rm', month + '.npz'))
        except OSError:
            pass
        flash(f'Data bulan {month} dihapus.', 'ok')
        return redirect(url_for('data'))

    # ---------------------------------------------------------------- master
    LF = master_io.LINE_FIELDS

    def parse_line(form):
        d = {}
        for k in LF:
            v = (form.get(k) or '').strip()
            if k in master_io.DATE_FIELDS:
                d[k] = v or None
            elif k == 'disc':
                d[k] = (float(v.replace(',', '.')) / 100) if v else None
            elif k in ('hn', 'hp'):
                d[k] = float(v.replace(',', '.')) if v else None
            else:
                d[k] = v
        return d

    def save_line(c, d, line_id=None):
        cols = ['pid', 'nama', 'tipe', 'status', 'src', 'menu', 'kode_normal_reg', 'kode_normal_xp', 'kode_promo_reg', 'kode_promo_xp', 'hn', 'disc', 'hp', 'rm_diskon',
                'start', '"end"', 'scope', 'base_start', 'base_end', 'ex_date', 'note']
        vals = [d[k] for k in LF]
        if line_id:
            c.execute('UPDATE lines SET ' + ','.join(f'{x}=?' for x in cols) + ' WHERE id=?', vals + [line_id])
        else:
            c.execute('INSERT INTO lines(' + ','.join(cols) + ') VALUES(' + ','.join('?' * len(cols)) + ')', vals)
        dbm.bump(c)
        c.commit()

    @app.route('/master/promo')
    @need()
    def master_promo():
        c = dbm.get_db()
        master, cogs = dbm.load_master(c)
        q = request.args.get('q', '').strip().lower()
        lines = [l for l in master['lines'] if not q or q in (l['id'] + l['nama'] + l['menu'] + l['kode_normal_reg'] + l['kode_promo_reg']).lower()]
        return render_template('master_promo.html', lines=lines, q=q, total=len(master['lines']))

    @app.route('/master/promo/edit', methods=['GET', 'POST'])
    @need('editor')
    def master_promo_edit():
        c = dbm.get_db()
        lid = request.values.get('lid', type=int)
        if request.method == 'POST':
            try:
                d = parse_line(request.form)
                if not d['id'] or not d['menu']:
                    raise ValueError('ID Promo dan Nama Menu wajib diisi.')
            except ValueError as e:
                flash(f'Isian tidak valid: {e}', 'err')
                return redirect(request.url)
            save_line(c, d, lid)
            flash('Baris promo disimpan.', 'ok')
            return redirect(url_for('master_promo'))
        row = None
        if lid:
            r = c.execute('SELECT * FROM lines WHERE id=?', (lid,)).fetchone()
            row = dict(r) if r else None
            if row:
                row['id'] = row.pop('pid')
        elif request.args.get('dup'):
            r = c.execute('SELECT * FROM lines WHERE id=?', (request.args.get('dup', type=int),)).fetchone()
            row = dict(r) if r else None
            if row:
                row['id'] = row.pop('pid')
        return render_template('master_promo_edit.html', r=row, lid=lid if row and lid else None)

    @app.route('/master/promo/hapus', methods=['POST'])
    @need('editor')
    def master_promo_hapus():
        c = dbm.get_db()
        c.execute('DELETE FROM lines WHERE id=?', (request.form.get('id', type=int),))
        dbm.bump(c)
        c.commit()
        flash('Baris dihapus.', 'ok')
        return redirect(url_for('master_promo'))

    @app.route('/master/outlet', methods=['GET', 'POST'])
    @need('viewer')
    def master_outlet():
        c = dbm.get_db()
        if request.method == 'POST':
            if ROLES.index(me()['role']) < 1:
                abort(403)
            act = request.form.get('act')
            if act == 'hapus':
                c.execute('DELETE FROM outlets WHERE id=?', (request.form.get('id', type=int),))
            else:
                name = request.form.get('name', '').strip()
                if not name:
                    flash('Nama outlet wajib diisi.', 'err')
                    return redirect(url_for('master_outlet'))
                vals = (name, request.form.get('kode', '').strip(), request.form.get('tipe', 'REGULER'), request.form.get('pavelle', 'N'), request.form.get('buka_override') or None)
                oid = request.form.get('id', type=int)
                try:
                    if oid:
                        c.execute('UPDATE outlets SET name=?,kode=?,tipe=?,pavelle=?,buka_override=? WHERE id=?', vals + (oid,))
                    else:
                        c.execute('INSERT INTO outlets(name,kode,tipe,pavelle,buka_override) VALUES(?,?,?,?,?)', vals)
                except Exception as e:
                    flash(f'Gagal menyimpan: {e}', 'err')
                    return redirect(url_for('master_outlet'))
            dbm.bump(c)
            c.commit()
            flash('Tersimpan.', 'ok')
            return redirect(url_for('master_outlet'))
        return render_template('master_outlet.html', rows=[dict(r) for r in c.execute('SELECT * FROM outlets ORDER BY name COLLATE NOCASE')])

    @app.route('/master/cogs', methods=['GET', 'POST'])
    @need('viewer')
    def master_cogs():
        c = dbm.get_db()
        if request.method == 'POST':
            if ROLES.index(me()['role']) < 1:
                abort(403)
            if request.form.get('act') == 'hapus':
                c.execute('DELETE FROM cogs WHERE code=?', (request.form.get('code'),))
            else:
                try:
                    code = request.form.get('code', '').strip()
                    cg = float(request.form.get('cogs', '').replace(',', '.'))
                    if not code:
                        raise ValueError('Kode wajib diisi')
                    c.execute('INSERT INTO cogs(code,nama,cogs,sumber) VALUES(?,?,?,?) ON CONFLICT(code) DO UPDATE SET nama=excluded.nama,cogs=excluded.cogs,sumber=excluded.sumber',
                              (code, request.form.get('nama', '').strip(), cg, request.form.get('sumber', 'Manual').strip() or 'Manual'))
                except ValueError as e:
                    flash(f'Isian tidak valid: {e}', 'err')
                    return redirect(url_for('master_cogs'))
            dbm.bump(c)
            c.commit()
            flash('Tersimpan.', 'ok')
            return redirect(url_for('master_cogs', q=request.args.get('q', '')))
        q = request.args.get('q', '').strip()
        rows = c.execute('SELECT * FROM cogs WHERE code LIKE ? OR nama LIKE ? ORDER BY code LIMIT 300', (f'%{q}%', f'%{q}%')).fetchall()
        return render_template('master_cogs.html', rows=[dict(r) for r in rows], q=q, total=c.execute('SELECT COUNT(*) FROM cogs').fetchone()[0])

    @app.route('/master/import', methods=['POST'])
    @need('editor')
    def master_import():
        f = request.files.get('file')
        if not f or not f.filename.lower().endswith('.xlsx'):
            flash('Pilih file Excel template (.xlsx).', 'err')
            return redirect(request.referrer or url_for('master_promo'))
        path = os.path.join(app.config['DATA_DIR'], 'tmp', uuid.uuid4().hex + '.xlsx')
        f.save(path)
        try:
            m = master_io.read_template(path)
        except Exception as e:
            flash(f'File tidak bisa dibaca: {e}', 'err')
            return redirect(request.referrer or url_for('master_promo'))
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        c = dbm.get_db()
        what = request.form.getlist('apa')
        n = []
        if 'promo' in what:
            c.execute('DELETE FROM lines')
            for ln in m['lines']:
                d = {k: (v.isoformat() if hasattr(v, 'isoformat') else v) for k, v in ln.items()}
                for k in master_io.DATE_FIELDS:
                    d[k] = d[k] or None
                save_line(c, d)
            n.append(f"{len(m['lines'])} baris promo")
        if 'outlet' in what:
            c.execute('DELETE FROM outlets')
            for o in m['outlets']:
                c.execute('INSERT OR REPLACE INTO outlets(name,kode,tipe,pavelle,buka_override) VALUES(?,?,?,?,?)',
                          (o['name'], o['kode'], o['tipe'], o['pavelle'], o['buka_override'].isoformat() if o['buka_override'] else None))
            n.append(f"{len(m['outlets'])} outlet")
        if 'cogs' in what:
            c.execute('DELETE FROM cogs')
            for g_ in m['cogs']:
                c.execute('INSERT OR REPLACE INTO cogs(code,nama,cogs,harga,gm,sumber) VALUES(?,?,?,?,?,?)', (g_['code'], g_['nama'], g_['cogs'], g_['harga'], g_['gm'], g_['sumber']))
            n.append(f"{len(m['cogs'])} kode COGS")
        if 'setting' in what:
            for k, v in m['settings'].items():
                dbm.set_setting(c, k, v)
            c.execute('DELETE FROM holidays')
            for d in m['holidays']:
                c.execute('INSERT OR REPLACE INTO holidays(d,note) VALUES(?,?)', (d.isoformat(), ''))
            n.append('pengaturan & hari libur')
        dbm.bump(c)
        c.commit()
        flash('Diimpor: ' + (', '.join(n) if n else 'tidak ada yang dipilih') + '.', 'ok' if n else 'err')
        return redirect(request.referrer or url_for('master_promo'))

    @app.route('/master/export.xlsx')
    @need()
    def master_export():
        import xlsxwriter
        c = dbm.get_db()
        master, _ = dbm.load_master(c)
        st = dbm.get_settings(c)
        bio = io.BytesIO()
        wb = xlsxwriter.Workbook(bio, {'in_memory': True})
        dfmt = wb.add_format({'num_format': 'dd-mmm-yyyy'})
        hf = wb.add_format({'bold': True, 'bg_color': '#D9E1F2', 'text_wrap': True})
        ws = wb.add_worksheet('MASTER_PROMO')
        for j, h in enumerate(master_io.LINE_HEADERS):
            ws.write(4, 1 + j, h, hf)
        for i, ln in enumerate(master['lines']):
            for j, k in enumerate(LF):
                v = ln[k] if k != 'id' else ln['id']
                if v is None or v == '':
                    continue
                if k in master_io.DATE_FIELDS:
                    ws.write_datetime(5 + i, 1 + j, dt.datetime.combine(v, dt.time()), dfmt)
                else:
                    ws.write(5 + i, 1 + j, v)
        ws = wb.add_worksheet('MASTER_OUTLET')
        for j, h in enumerate(['Nama Outlet', 'Kode Store', 'Tipe', 'Pavelle', 'Tgl Buka override']):
            ws.write(4, 1 + j, h, hf)
        for i, o in enumerate(master['outlets']):
            ws.write(5 + i, 1, o['name']); ws.write(5 + i, 2, o['kode'] or ''); ws.write(5 + i, 3, o['tipe']); ws.write(5 + i, 4, o['pavelle'])
            if o['buka_override']:
                ws.write_datetime(5 + i, 5, dt.datetime.combine(o['buka_override'], dt.time()), dfmt)
        ws = wb.add_worksheet('MASTER_COGS')
        for j, h in enumerate(['Kode Menu', 'Nama Menu', 'COGS per porsi', 'Harga existing', 'GM%', 'Sumber']):
            ws.write(4, j, h, hf)
        for i, r in enumerate(c.execute('SELECT * FROM cogs ORDER BY code')):
            for j, k in enumerate(('code', 'nama', 'cogs', 'harga', 'gm', 'sumber')):
                if r[k] is not None:
                    ws.write(5 + i, j, r[k])
        ws = wb.add_worksheet('SETTING')
        for r_, v in ((6, st['floor']), (7, st['src_single']), (8, st['src_group']), (10, st['ambang_naik']), (11, st['ambang_turun']), (12, st['toleransi_harga'])):
            ws.write(r_ - 1, 1, v)
        for i, d in enumerate(sorted(st['holidays'])):
            ws.write_datetime(15 + i, 0, dt.datetime.combine(d, dt.time()), dfmt)
        wb.close()
        bio.seek(0)
        return send_file(bio, as_attachment=True, download_name='master_promo_dcost.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    @app.route('/export/hasil.xlsx')
    @need()
    def export_hasil():
        import xlsxwriter
        key, ms = month_arg()
        v = get_res(key) if key else None
        if v is None:
            abort(404)
        bio = io.BytesIO()
        wb = xlsxwriter.Workbook(bio, {'in_memory': True})
        hf = wb.add_format({'bold': True, 'bg_color': '#D9E1F2', 'text_wrap': True})
        ws = wb.add_worksheet('RINGKASAN')
        heads = ['ID', 'Promo', 'Hari promo', 'Outlet berlaku', 'Outlet jual', 'Qty item', 'Sales item', 'Adopsi', 'Kontribusi', 'Uplift qty item', 'Uplift sales total outlet',
                 'Sales inkremental', 'Biaya diskon', 'Kesimpulan', 'Catatan']
        for j, h in enumerate(heads): ws.write(0, j, h, hf)
        for i, p in enumerate(v['res']['promos']):
            row = [p['id'], p['nama'], p['hari'], p['berlaku'], p['jual'], p['qty'], p['sales'], p['adopsi'], p['kontrib'], p['up_item'], p['up_outlet'], p['incr'], p['biaya'], p['verdict'], p['catatan']]
            for j, x in enumerate(row):
                if x is not None: ws.write(1 + i, j, x)
        ws = wb.add_worksheet('PROFIT')
        for j, h in enumerate(['ID', 'Promo', 'Sales item', 'Cakupan COGS', 'COGS', 'Gross profit', 'GM% promo', 'Biaya diskon', 'GM% harga normal', 'Break-even qty', 'Uplift qty aktual', 'Kesimpulan']): ws.write(0, j, h, hf)
        for i, p in enumerate(v['res']['promos']):
            f = p['profit']
            row = [p['id'], p['nama'], f['sales'], f['cakupan'], f['cogs'], f['gp'], f['gm'], f['biaya'], f['gm_norm'], f['be'], p['up_item'], f['kes']]
            for j, x in enumerate(row):
                if x is not None: ws.write(1 + i, j, x)
        ws = wb.add_worksheet('PER_OUTLET')
        for j, h in enumerate(['ID', 'Outlet', 'Tipe', 'Hari promo', 'Qty item', 'Sales item', 'Sales button promo', 'Adopsi', 'Kontribusi', 'Uplift sales item', 'Uplift sales total outlet', 'Status']): ws.write(0, j, h, hf)
        for i, a in enumerate(sorted(v['res']['po'].values(), key=lambda a: (a['id'], -a['sf']))):
            row = [a['id'], a['outlet'], a['tipe'], a['nP'], a['qf'], a['sf'], a['sp'], a['adopsi'], a['kontrib'], a['upS'], a['upT'], a['status']]
            for j, x in enumerate(row):
                if x is not None: ws.write(1 + i, j, x)
        wb.close()
        bio.seek(0)
        return send_file(bio, as_attachment=True, download_name=f'hasil_promo_{key}.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    # ---------------------------------------------------------------- pengaturan & user
    @app.route('/pengaturan', methods=['GET', 'POST'])
    @need('editor')
    def pengaturan():
        c = dbm.get_db()
        if request.method == 'POST':
            try:
                dbm.set_setting(c, 'floor', request.form.get('floor', 'Main').strip())
                dbm.set_setting(c, 'src_single', request.form.get('src_single', 'UNGROUP').strip())
                dbm.set_setting(c, 'src_group', request.form.get('src_group', 'GROUP').strip())
                dbm.set_setting(c, 'ambang_naik', float(request.form.get('ambang_naik', '5').replace(',', '.')) / 100)
                dbm.set_setting(c, 'ambang_turun', float(request.form.get('ambang_turun', '0').replace(',', '.')) / 100)
                dbm.set_setting(c, 'toleransi_harga', float(request.form.get('toleransi', '3').replace(',', '.')) / 100)
                c.execute('DELETE FROM holidays')
                for line in request.form.get('holidays', '').splitlines():
                    line = line.strip()
                    if line:
                        d, _, note = line.partition(' ')
                        c.execute('INSERT OR REPLACE INTO holidays(d,note) VALUES(?,?)', (dt.date.fromisoformat(d).isoformat(), note.strip()))
            except ValueError as e:
                flash(f'Isian tidak valid (tanggal harus YYYY-MM-DD): {e}', 'err')
                return redirect(url_for('pengaturan'))
            dbm.bump(c)
            c.commit()
            flash('Pengaturan disimpan.', 'ok')
            return redirect(url_for('pengaturan'))
        st = dbm.get_settings(c)
        hol = '\n'.join(f"{r['d']} {r['note'] or ''}".strip() for r in c.execute('SELECT * FROM holidays ORDER BY d'))
        return render_template('pengaturan.html', st=st, hol=hol)

    @app.route('/admin/users', methods=['GET', 'POST'])
    @need('admin')
    def users():
        c = dbm.get_db()
        if request.method == 'POST':
            act = request.form.get('act')
            if act == 'tambah':
                em = request.form.get('email', '').strip().lower()
                role = request.form.get('role', 'viewer')
                if '@' not in em or role not in ROLES:
                    flash('Email atau peran tidak valid.', 'err')
                elif c.execute('SELECT 1 FROM users WHERE email=?', (em,)).fetchone():
                    flash('Email sudah terdaftar.', 'err')
                else:
                    pw = secrets.token_urlsafe(8)
                    c.execute('INSERT INTO users(email,name,role,pw_hash,must_change,created_at) VALUES(?,?,?,?,1,?)',
                              (em, request.form.get('name', '').strip(), role, generate_password_hash(pw), dt.datetime.now().isoformat(timespec='seconds')))
                    c.commit()
                    flash(f'Akun {em} dibuat. Kata sandi sementara (tampil sekali, kirimkan ke orangnya): {pw}', 'ok')
            else:
                uid = request.form.get('id', type=int)
                if uid == me()['id'] and act in ('nonaktif', 'peran'):
                    flash('Tidak bisa mengubah akun sendiri di sini.', 'err')
                elif act == 'nonaktif':
                    c.execute('UPDATE users SET active=1-active WHERE id=?', (uid,)); c.commit(); flash('Status akun diubah.', 'ok')
                elif act == 'peran' and request.form.get('role') in ROLES:
                    c.execute('UPDATE users SET role=? WHERE id=?', (request.form.get('role'), uid)); c.commit(); flash('Peran diubah.', 'ok')
                elif act == 'reset':
                    pw = secrets.token_urlsafe(8)
                    c.execute('UPDATE users SET pw_hash=?, must_change=1 WHERE id=?', (generate_password_hash(pw), uid)); c.commit()
                    flash(f'Kata sandi sementara baru (tampil sekali): {pw}', 'ok')
            return redirect(url_for('users'))
        return render_template('users.html', rows=[dict(r) for r in c.execute('SELECT * FROM users ORDER BY email')])

    return app


app = create_app() if os.environ.get('DCOST_AUTOSTART', '1') == '1' else None

if __name__ == '__main__':
    create_app().run(host='0.0.0.0', port=int(os.environ.get('PORT', '8000')))
