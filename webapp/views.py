"""Turunan hasil analisa untuk halaman detail & perbandingan antar bulan."""
import datetime as dt
import numpy as np
import engine


def promo_detail(res, md, pid, settings):
    D = res['D']
    lines = [l for l in res['lines'] if l['id'] == pid]
    if not lines:
        return None
    f = lines[0]
    src_single = settings.get('src_single', 'UNGROUP')
    menu = []
    for ln in lines:
        if not ln['_active']:
            continue
        rows = [r for r in res['LO'] if r['line'] is ln]
        qp = sum(r['QP_P'] for r in rows); sp = sum(r['SP_P'] for r in rows)
        qn = sum(r['QN_P'] for r in rows); sn = sum(r['SN_P'] for r in rows)
        aq = sum(r['ActQ'] for r in rows); eq = sum(r['ExpQ_v'] for r in rows)
        as_ = sum(r['ActS'] for r in rows); es = sum(r['ExpS_v'] for r in rows)
        menu.append(dict(menu=ln['menu'], hn=ln['_hn'], hp=ln['_hp'], disc=ln['_disc_eff'], jual=sum(r['jalan'] for r in rows), qp=qp, sp=sp, qn=qn,
                         adopsi=(qp / (qp + qn)) if (promo_has(ln) and qp + qn > 0) else None, sales=sp + sn,
                         up_q=(aq / eq - 1) if eq > 0 else None, up_s=(as_ / es - 1) if es > 0 else None,
                         gm_norm=ln['_gm_norm'], gm_promo=ln['_gm_promo'], scope=ln['scope']))
    po = [a for a in res['po'].values() if a['id'] == pid]
    tipe = []
    for t in ('REGULER', 'XPRESS', 'AYUMMY'):
        rr = [a for a in po if (a['tipe'] or '').upper() == t]
        if not rr:
            continue
        T_P = sum(a['T_P'] for a in rr); sf = sum(a['sf'] for a in rr)
        es = sum(a['ExpS'] for a in rr); et = sum(a['ExpT'] for a in rr)
        tipe.append(dict(tipe=t, jual=sum(a['jalan'] for a in rr), berlaku=sum(1 for a in rr if a['nP'] > 0), qty=sum(a['qf'] for a in rr), sales=sf,
                         sales_btn=sum(a['sp'] for a in rr), kontrib=(sf / T_P) if T_P > 0 else None,
                         up_s=(sum(a['ActS'] for a in rr) / es - 1) if es > 0 else None, up_t=(sum(a['ActT'] for a in rr) / et - 1) if et > 0 else None))
    outlets = sorted(po, key=lambda a: -a['sf'])
    # tren harian (semua outlet)
    qp = np.zeros(D); qn = np.zeros(D); sp = np.zeros(D); sn = np.zeros(D)
    for ln in lines:
        if not ln['_active']:
            continue
        for c in (ln['kode_promo_reg'], ln['kode_promo_xp']):
            if c:
                q, s = md.code_sum(ln['src'], c); qp += q; sp += s
        for c in (ln['kode_normal_reg'], ln['kode_normal_xp']):
            if c:
                q, s = md.code_sum(ln['src'], c); qn += q; sn += s
    tot = np.zeros(D)
    for o in res['outlets']:
        tot += o['T']
    days = np.arange(1, D + 1)
    flag = ((days >= max(f['_sday'], 1)) & (days <= min(f['_eday'], D)) & (days != f['_exday'])).astype(int)
    return dict(first=f, menu=menu, tipe=tipe, outlets=outlets, trend=dict(days=list(days), qp=qp.tolist(), qn=qn.tolist(), sp=sp.tolist(), sn=sn.tolist(), total=tot.tolist(), flag=flag.tolist()))


def promo_has(ln):
    return bool(ln['kode_promo_reg'] or ln['kode_promo_xp'])


def month_totals(md, month, lines, src_single):
    """total satu bulan penuh tiap baris master (semua outlet) untuk PERBANDINGAN"""
    D = md.D
    som = month
    eom = som + dt.timedelta(days=D - 1)
    out = {}
    seen = set()
    for i, ln in enumerate(lines):
        if not ln['id']:
            continue
        key = (ln['id'], ln['src'], ln['kode_normal_reg'], ln['kode_normal_xp'], ln['kode_promo_reg'], ln['kode_promo_xp'])
        hit = key not in seen
        seen.add(key)
        active = (ln['start'] is None or ln['start'] <= eom) and (ln['end'] is None or ln['end'] >= som)
        if not (hit and active):
            continue
        qp = sp = qn = sn = 0.0
        for c in (ln['kode_promo_reg'], ln['kode_promo_xp']):
            if c:
                q, s = md.code_sum(ln['src'], c); qp += q.sum(); sp += s.sum()
        for c in (ln['kode_normal_reg'], ln['kode_normal_xp']):
            if c:
                q, s = md.code_sum(ln['src'], c); qn += q.sum(); sn += s.sum()
        out[i] = (qp, sp, qn, sn)
    total = sum(float(v.sum()) for v in md.all_totals(src_single).values())
    return dict(per_line=out, total=total, D=D, som=som, eom=eom)


def perbandingan(month_infos, lines, base_month, n_months=12):
    """month_infos: {month_date: month_totals}; hasil: list promo dengan metrik per bulan"""
    months = []
    y, m = base_month.year, base_month.month
    for k in range(n_months):
        yy, mm = y + (m - 1 + k) // 12, (m - 1 + k) % 12 + 1
        months.append(dt.date(yy, mm, 1))
    order = []
    first = {}
    for i, ln in enumerate(lines):
        if ln['id'] and ln['id'] not in first:
            first[ln['id']] = i
            order.append(ln['id'])
    res = []
    for pid in order:
        i0 = first[pid]
        f = lines[i0]
        pl = [i for i, l in enumerate(lines) if l['id'] == pid]
        has_code = any(promo_has(lines[i]) for i in pl)
        row = dict(id=pid, nama=f['nama'], m=[])
        prev = None
        for mo in months:
            info = month_infos.get(mo)
            cell = dict(month=mo, sales=None, hari=None, perhari=None, kontrib=None, qty=None, adopsi=None, mom=None)
            if info is not None:
                som, eom = info['som'], info['eom']
                s = som if f['start'] is None else max(f['start'], som)
                e = eom if f['end'] is None else min(f['end'], eom)
                hari = max(0, (e - s).days + 1)
                ex = f['ex_date']
                if hari > 0 and ex and s <= ex <= e:
                    hari -= 1
                cell['hari'] = hari
                if hari > 0:
                    qp = sp = qn = sn = 0.0
                    for i in pl:
                        v = info['per_line'].get(i)
                        if v:
                            qp += v[0]; sp += v[1]; qn += v[2]; sn += v[3]
                    cell['sales'] = sp if has_code else sn
                    cell['qty'] = qp if has_code else qn
                    cell['perhari'] = cell['sales'] / hari
                    cell['kontrib'] = (cell['sales'] / info['total']) if info['total'] > 0 else None
                    cell['adopsi'] = (qp / (qp + qn)) if (has_code and qp + qn > 0) else None
                    if prev and prev > 0:
                        cell['mom'] = cell['perhari'] / prev - 1
                    prev = cell['perhari']
                else:
                    prev = None
            row['m'].append(cell)
        res.append(row)
    return months, res


def checks(md, res, master, cogs, settings, nrows):
    """Pemeriksaan data (setara sheet CEK_DATA, tapi menyebut nama yang bermasalah)."""
    out = []
    def add(label, value, status, note, items=None):
        out.append(dict(label=label, value=value, status=status, note=note, daftar=items or []))
    add('Baris data RM (semua floor) di bulan ini', f'{nrows:,}'.replace(',', '.'), 'OK' if nrows > 0 else 'PERIKSA', 'Jumlah baris yang berhasil dibaca dari file.')
    floor_rows = int((md.Q.shape[0]))
    add('Kombinasi store-kelompok-kode di floor dine-in', f'{floor_rows:,}'.replace(',', '.'), 'OK' if floor_rows > 0 else 'PERIKSA',
        'Nol berarti nama floor di Pengaturan tidak sama dengan isi kolom Florr di data RM.')
    src_s, src_g = settings.get('src_single', 'UNGROUP'), settings.get('src_group', 'GROUP')
    ts = sum(float(v.sum()) for v in md.all_totals(src_s).values())
    tg = sum(float(v.sum()) for v in md.all_totals(src_g).values())
    diff = abs(ts - tg) / ts if ts else 0
    add('Total sales dine-in: kelompok tunggal vs paket', f'{ts:,.0f} vs {tg:,.0f}'.replace(',', '.'), 'OK' if diff < 0.001 else 'PERIKSA',
        'Keduanya harus sama (hanya cara memecah menu yang beda). Selisih > 0,1% berarti data tidak lengkap atau salah copy.')
    names = {o['name'] for o in master['outlets']}
    unknown = sorted(s for s in md.all_totals(src_s) if s not in names)
    add('Outlet di data RM yang belum terdaftar di master outlet', len(unknown), 'OK' if not unknown else 'PERIKSA',
        'Daftarkan di Master > Outlet dengan nama persis sama seperti kolom Store, atau perbaiki ejaannya.', unknown)
    nosales = sorted(o['name'] for o in res['outlets'] if o['total'] == 0)
    add('Outlet di master tanpa penjualan bulan ini', len(nosales), 'OK' if not nosales else 'INFO', 'Outlet tutup / belum buka / salah nama. Tidak masuk perhitungan.', nosales)
    nocode = []
    for ln in res['active']:
        for f in ('kode_normal_reg', 'kode_normal_xp', 'kode_promo_reg', 'kode_promo_xp'):
            c = ln[f]
            if c and (ln['src'], c) not in md.by_code:
                nocode.append(f"{ln['id']} {ln['menu']}: {c}")
    add('Kode di master promo yang tidak terjual di data bulan ini', len(nocode), 'OK' if not nocode else 'PERIKSA',
        'Bisa salah ketik kode, salah pilih sumber (UNGROUP/GROUP), atau memang belum terjual bulan ini.', nocode)
    nocogs = sorted({f"{ln['id']} {ln['menu']}" for ln in res['active'] if ln['_cogs_reg'] is None})
    add('Baris menu promo aktif tanpa COGS (margin tidak terhitung)', len(nocogs), 'OK' if not nocogs else 'INFO', 'Isi COGS menu itu di Master > COGS agar GM% dan break-even muncul.', nocogs)
    nodate = sorted({f"{ln['id']} {ln['menu']}" for ln in res['lines'] if ln['id'] and ln['start'] and ln['end'] and ln['start'] > ln['end']})
    add('Baris promo dengan tanggal mulai > selesai', len(nodate), 'OK' if not nodate else 'PERIKSA', '', nodate)
    return out
