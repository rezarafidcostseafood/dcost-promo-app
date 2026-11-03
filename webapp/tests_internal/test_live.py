import os, sys, re, time, threading, tempfile, shutil, datetime as dt, warnings
warnings.filterwarnings('ignore')
os.environ['DCOST_AUTOSTART'] = '0'; os.environ['ADMIN_EMAIL'] = 'admin@x.id'; os.environ['ADMIN_PASSWORD'] = 'Rahasia123!'
sys.path.insert(0, '/home/claude/webapp')
import requests, pandas as pd
import app as A, rmload, db as dbm, master_io
tmp = tempfile.mkdtemp(); app = A.create_app({'DATA_DIR': tmp})
for mo, p in (('2026-08', 'data_aug.pkl'), ('2026-09', 'data_sep.pkl')):
    df = pd.read_pickle('/home/claude/' + p); rmload.save_rm(os.path.join(tmp, 'rm', mo + '.npz'), rmload.df_to_rm(df))
    cc = dbm.connect(os.path.join(tmp, 'app.db')); cc.execute("INSERT OR REPLACE INTO months VALUES(?,?,?,?,?,?)", (mo, p, len(df), 31, 'seed', dt.datetime.now().isoformat())); cc.commit(); cc.close()
from werkzeug.serving import make_server
srv = make_server('127.0.0.1', 8765, app, threaded=True); threading.Thread(target=srv.serve_forever, daemon=True).start(); time.sleep(1)
s = requests.Session(); B = 'http://127.0.0.1:8765'
tok = re.search(r'name="csrf" value="([0-9a-f]+)"', s.get(B + '/login').text).group(1)
r = s.post(B + '/login', data=dict(csrf=tok, email='admin@x.id', password='Rahasia123!')); print('login HTTP', r.status_code, r.url)
tok = re.search(r'name="csrf" value="([0-9a-f]+)"', s.get(B + '/master/promo').text).group(1)
with open('/home/claude/webapp/seed/master_awal.xlsx', 'rb') as f:
    r = s.post(B + '/master/import', data=dict(csrf=tok, apa=['promo', 'outlet', 'cogs', 'setting']), files=dict(file=('m.xlsx', f))); print('impor seed:', re.search(r'Diimpor: ([^<]+)', r.text).group(1))
css = s.get(B + '/static/style.css'); print('CSS', css.status_code, len(css.text), 'byte')
for u in ('/ringkasan?bulan=2026-08', '/ringkasan?bulan=2026-09', '/promo/P04?bulan=2026-09', '/profit?bulan=2026-09', '/perbandingan', '/cek?bulan=2026-09'):
    t = time.time(); r = s.get(B + u); print(f'{u:32s} HTTP {r.status_code}  {time.time() - t:5.2f} s  {len(r.text) // 1024} KB')
t = time.time(); r = s.get(B + '/promo/P09?bulan=2026-09'); print('detail promo 30 baris menu (P09)', r.status_code, f'{time.time() - t:.2f}s', 'menu rows:', r.text.count('Nasi Goreng') // 1)
srv.shutdown(); shutil.rmtree(tmp, ignore_errors=True)
