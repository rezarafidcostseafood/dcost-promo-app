"""Mesin analisa promo (port dari template Excel). Semua angka sebelum PB1."""
import calendar
import datetime as dt
import numpy as np
import pandas as pd


def days_in(m):
    return calendar.monthrange(m.year, m.month)[1]


def to_date(v):
    if v is None or v == '':
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if isinstance(v, str):
        for f in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
            try:
                return dt.datetime.strptime(v.strip(), f).date()
            except ValueError:
                pass
    return None


def num(v):
    if v is None or v == '':
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class MonthData:
    """Data RM satu bulan, difilter ke floor dine-in dan dijumlah per (kelompok, store, kode)."""

    def __init__(self, rm, floor):
        self.D = rm['D']
        m = rm['florr'] == floor
        store, kel, code = rm['store'][m], rm['kel'][m], rm['code'][m]
        Q, S = rm['qty'][m], rm['sales'][m]
        key = pd.Series(kel).astype(str) + '|' + pd.Series(store).astype(str) + '|' + pd.Series(code).astype(str)
        ids, uniq = pd.factorize(key)
        self.idx = {k: i for i, k in enumerate(uniq)}
        n = len(uniq)
        self.Q = np.zeros((n, self.D))
        self.S = np.zeros((n, self.D))
        if len(ids):
            np.add.at(self.Q, ids, Q)
            np.add.at(self.S, ids, S)
        self.zero = np.zeros(self.D)
        self.by_code = {}
        for k, i in self.idx.items():
            kk, st_, cd = k.split('|', 2)
            self.by_code.setdefault((kk, cd), []).append(i)
        self.stores = set(pd.unique(store))
        self.kels = set(pd.unique(kel))

    def get(self, kel, store, code):
        if not code:
            return self.zero, self.zero
        i = self.idx.get(f'{kel}|{store}|{code}')
        if i is None:
            return self.zero, self.zero
        return self.Q[i], self.S[i]

    def outlet_total(self, kel, store):
        # jumlah sales semua kode untuk 1 store (kelompok tunggal)
        pre = f'{kel}|{store}|'
        tot = np.zeros(self.D)
        for k, i in self.idx.items():
            if k.startswith(pre):
                tot += self.S[i]
        return tot

    def all_totals(self, kel):
        out = {}
        for k, i in self.idx.items():
            kk, st, _ = k.split('|', 2)
            if kk == kel:
                if st not in out:
                    out[st] = np.zeros(self.D)
                out[st] += self.S[i]
        return out

    def code_sum(self, kel, code):
        """total semua store untuk 1 kode: (qty[D], sales[D])"""
        ii = self.by_code.get((kel, code))
        if not ii:
            return self.zero, self.zero
        return self.Q[ii].sum(axis=0), self.S[ii].sum(axis=0)


def scope_ok(scope, outlet):
    sc = (scope or '').strip()
    u = sc.upper()
    t = (outlet['tipe'] or '').upper()
    if u in ('', 'ALL'):
        return True
    if u == 'XPRESS':
        return t == 'XPRESS'
    if u == 'REGULER':
        return t == 'REGULER'
    if u == 'AYUMMY':
        return t == 'AYUMMY'
    if u == 'NONXPRESS':
        return t != 'XPRESS'
    if u == 'PAVELLE':
        return (outlet['pavelle'] or '').upper() == 'Y'
    return (';' + outlet['name'].lower() + ';') in (';' + sc.lower() + ';')


def line_days(line, som, D):
    """hari mulai/selesai promo (indeks hari ke-n dalam bulan, bisa di luar 1..D)"""
    s = line['start']
    e = line['end']
    sday = 1 if s is None else (s - som).days + 1
    eday = D if e is None else (e - som).days + 1
    return sday, eday


def promo_has_code(line):
    return bool(line['kode_promo_reg'] or line['kode_promo_xp'])


def analyze(month, md, master, settings, cogs):
    """month: date tgl 1; md: MonthData; master: dict(lines, outlets); hasil: dict"""
    D = md.D
    som = month
    floor_src = settings.get('src_single', 'UNGROUP')
    tol = float(settings.get('toleransi_harga', 0.03))
    naik = float(settings.get('ambang_naik', 0.05))
    turun = float(settings.get('ambang_turun', 0.0))
    holidays = set(settings.get('holidays', []))
    days = np.arange(1, D + 1)
    dates = [som + dt.timedelta(days=i) for i in range(D)]
    HL = np.array([1 if (d.weekday() >= 5 or d in holidays) else 0 for d in dates])

    # --- outlet
    totals_all = md.all_totals(floor_src)
    outlets = []
    for o in master['outlets']:
        tot = totals_all.get(o['name'], np.zeros(D))
        first = int(np.argmax(tot > 0)) + 1 if (tot > 0).any() else 0
        ov = o.get('buka_override')
        if ov:
            od = max(1, (ov - som).days + 1)
        else:
            od = 99 if first == 0 else first
        outlets.append(dict(o, T=tot, first=first, open=od, total=float(tot.sum())))

    # --- baris master aktif
    lines = master['lines']
    act = []
    for ln in lines:
        sday, eday = line_days(ln, som, D)
        ln['_sday'], ln['_eday'] = sday, eday
        ln['_active'] = bool(ln['id']) and sday <= D and eday >= 1
        ln['_exday'] = ((ln['ex_date'] - som).days + 1) if ln.get('ex_date') else 0
        if ln['_active']:
            act.append(ln)

    # --- pass 1: array tiap (baris, outlet)
    LO = []
    seen_main = set()
    qn_tot = {}
    sn_tot = {}
    for ln in act:
        for o in outlets:
            if not scope_ok(ln['scope'], o):
                continue
            kel = ln['src']
            arr = {c: md.get(kel, o['name'], ln[c]) for c in ('kode_normal_reg', 'kode_normal_xp', 'kode_promo_reg', 'kode_promo_xp')}
            qn = arr['kode_normal_reg'][0] + arr['kode_normal_xp'][0]
            sn = arr['kode_normal_reg'][1] + arr['kode_normal_xp'][1]
            qp = arr['kode_promo_reg'][0] + arr['kode_promo_xp'][0]
            sp = arr['kode_promo_reg'][1] + arr['kode_promo_xp'][1]
            key = (ln['id'], o['name'])
            main = key not in seen_main
            seen_main.add(key)
            LO.append(dict(line=ln, o=o, qn=qn, sn=sn, qp=qp, sp=sp, main=main))
            li = id(ln)
            qn_tot[li] = qn_tot.get(li, 0.0) + float(qn.sum())
            sn_tot[li] = sn_tot.get(li, 0.0) + float(sn.sum())

    # --- HN / HP per baris
    for ln in act:
        li = id(ln)
        est = (sn_tot[li] / qn_tot[li]) if qn_tot.get(li, 0) > 0 else None
        hn = num(ln['hn'])
        hn = hn if hn is not None else est
        ln['_hn_est'] = est
        disc = num(ln['disc'])
        hpo = num(ln['hp'])
        if hpo is not None:
            hp = hpo
        elif hn is not None and disc is not None:
            hp = hn * (1 - disc)
        else:
            hp = None
        ln['_hn'], ln['_hp'] = hn, hp
        ln['_disc_eff'] = (1 - hp / hn) if (hn and hp is not None) else (disc if disc is not None else 0.0)
        # COGS
        def cg(code):
            c = cogs.get(code) if code else None
            return None if c is None else c
        reg = cg(ln['kode_normal_reg'])
        if reg is None:
            reg = cg(ln['kode_promo_reg'])
        xp = cg(ln['kode_normal_xp'])
        if xp is None:
            xp = cg(ln['kode_promo_xp'])
        if xp is None:
            xp = reg
        ln['_cogs_reg'], ln['_cogs_xp'] = reg, xp
        ln['_gm_norm'] = (1 - reg / hn) if (reg is not None and hn) else None
        ln['_gm_promo'] = (1 - reg / hp) if (reg is not None and hp) else None

    # --- pass 2: metrik
    for r in LO:
        ln, o = r['line'], r['o']
        s_eff = max(ln['_sday'], o['open'], 1)
        e_eff = min(ln['_eday'], D)
        ex = ln['_exday']
        P = (days >= s_eff) & (days <= e_eff) & (days != ex)
        nP = int(P.sum())
        pm = P if nP > 0 else np.zeros(D, bool)
        b_s = o['open']
        if ln['base_start']:
            b_s = max(1, o['open'], (ln['base_start'] - som).days + 1)
        b_e = D
        if ln['base_end']:
            b_e = min(D, (ln['base_end'] - som).days + 1)
        B = (days >= b_s) & (days <= b_e) & (~pm)
        hl = HL == 1
        nPHL = int((pm & hl).sum())
        nB = int(B.sum())
        nBHL = int((B & hl).sum())
        uHK = (nP - nPHL > 0) and (nB - nBHL > 0)
        uHL = (nPHL > 0) and (nBHL > 0)
        qf = r['qn'] + r['qp']
        sf = r['sn'] + r['sp']
        QP_P, SP_P = float(r['qp'][pm].sum()), float(r['sp'][pm].sum())
        QN_P, SN_P = float(r['qn'][pm].sum()), float(r['sn'][pm].sum())
        QF_PHL, SF_PHL = float(qf[pm & hl].sum()), float(sf[pm & hl].sum())
        QF_B, SF_B = float(qf[B].sum()), float(sf[B].sum())
        QF_BHL, SF_BHL = float(qf[B & hl].sum()), float(sf[B & hl].sum())

        def expect(tot, hlv):
            if nP == 0 or not (uHK or uHL):
                return None
            v = 0.0
            if uHK:
                v += (nP - nPHL) * (tot - hlv) / (nB - nBHL)
            if uHL:
                v += nPHL * hlv / nBHL
            return v
        ExpQ, ExpS = expect(QF_B, QF_BHL), expect(SF_B, SF_BHL)
        new = ln['status'] == 'New'
        ActS = ExpS_v = ActQ = ExpQ_v = 0.0
        if ExpS is not None and not new and ExpS > 0:
            ActS = (SP_P + SN_P - SF_PHL) * uHK + SF_PHL * uHL
            ExpS_v = ExpS
        if ExpQ is not None and not new and ExpQ > 0:
            ActQ = (QP_P + QN_P - QF_PHL) * uHK + QF_PHL * uHL
            ExpQ_v = ExpQ
        T_P = T_PHL = T_B = T_BHL = 0.0
        ExpT = None
        ActT = ExpT_v = 0.0
        if r['main'] and nP > 0:
            T = o['T']
            T_P, T_PHL = float(T[pm].sum()), float(T[pm & hl].sum())
            if nB > 0:
                T_B, T_BHL = float(T[B].sum()), float(T[B & hl].sum())
            ExpT = expect(T_B, T_BHL)
            if ExpT is not None and ExpT > 0:
                ActT = (T_P - T_PHL) * uHK + T_PHL * uHL
                ExpT_v = ExpT
        has_pc = promo_has_code(ln)
        jalan = 0
        if nP > 0:
            jalan = 1 if ((QP_P > 0) if has_pc else (QN_P > 0)) else 0
        if has_pc:
            avg = (SP_P / QP_P) if QP_P > 0 else None
        else:
            avg = (SN_P / QN_P) if QN_P > 0 else None
        hp = ln['_hp']
        cek = 1 if (avg is not None and hp and abs(avg / hp - 1) > tol) else 0
        if ln['rm_diskon'] == 'HARGA NORMAL':
            biaya = (SP_P + SN_P) * ln['_disc_eff']
        elif ln['_hn'] is not None and hp is not None:
            biaya = (QP_P if has_pc else QP_P + QN_P) * max(0.0, ln['_hn'] - hp)
        else:
            biaya = 0.0
        cg = ln['_cogs_xp'] if (o['tipe'] or '').upper() == 'XPRESS' else ln['_cogs_reg']
        cogs_ada = cg is not None
        r.update(nP=nP, nB=nB, nPHL=nPHL, QP_P=QP_P, SP_P=SP_P, QN_P=QN_P, SN_P=SN_P, ActS=ActS, ExpS_v=ExpS_v, ActQ=ActQ, ExpQ_v=ExpQ_v,
                 T_P=T_P, ActT=ActT, ExpT_v=ExpT_v, jalan=jalan, avg=avg, cek=cek, biaya=biaya,
                 cogs_p=((QP_P + QN_P) * cg) if cogs_ada else 0.0, sales_cogs=(SP_P + SN_P) if cogs_ada else 0.0,
                 biaya_cogs=biaya if cogs_ada else 0.0, cogs_ada=cogs_ada, qf_p=QP_P + QN_P, sf_p=SP_P + SN_P)

    # --- agregasi promo x outlet
    po = {}
    for r in LO:
        k = (r['line']['id'], r['o']['name'])
        a = po.setdefault(k, dict(id=k[0], outlet=k[1], tipe=r['o']['tipe'], pavelle=r['o']['pavelle'], aktif=1, nP=0, nB=0, jalan=0, qf=0.0, sf=0.0, qp=0.0, sp=0.0,
                                  ActS=0.0, ExpS=0.0, ActQ=0.0, ExpQ=0.0, ActT=0.0, ExpT=0.0, T_P=0.0, biaya=0.0, cek=0, cogs=0.0, sales_cogs=0.0, biaya_cogs=0.0))
        if r['main']:
            a['nP'], a['nB'] = r['nP'], r['nB']
        a['jalan'] = 1 if (a['jalan'] or r['jalan']) else 0
        a['qf'] += r['qf_p']; a['sf'] += r['sf_p']; a['qp'] += r['QP_P']; a['sp'] += r['SP_P']
        a['ActS'] += r['ActS']; a['ExpS'] += r['ExpS_v']; a['ActQ'] += r['ActQ']; a['ExpQ'] += r['ExpQ_v']
        a['ActT'] += r['ActT']; a['ExpT'] += r['ExpT_v']; a['T_P'] += r['T_P']
        a['biaya'] += r['biaya']; a['cek'] += r['cek']
        a['cogs'] += r['cogs_p']; a['sales_cogs'] += r['sales_cogs']; a['biaya_cogs'] += r['biaya_cogs']
    for a in po.values():
        a['upS'] = (a['ActS'] / a['ExpS'] - 1) if a['ExpS'] > 0 else None
        a['upT'] = (a['ActT'] / a['ExpT'] - 1) if a['ExpT'] > 0 else None
        a['kontrib'] = (a['sf'] / a['T_P']) if a['T_P'] > 0 else None
        a['adopsi'] = (a['qp'] / a['qf']) if a['qf'] > 0 else None
        a['status'] = ('TIDAK ADA HARI PROMO' if a['nP'] == 0 else ('JALAN' if a['jalan'] else 'BELUM JALAN'))

    # --- ringkasan promo (urutan = baris pertama master yang aktif)
    order = []
    first_idx = {}
    for i, ln in enumerate(lines):
        if ln['id'] and ln['id'] not in first_idx:
            first_idx[ln['id']] = i
    for pid, i in first_idx.items():
        if lines[i]['_active']:
            order.append(pid)
    promos = []
    for pid in order:
        f = lines[first_idx[pid]]
        rows = [a for a in po.values() if a['id'] == pid]
        pl = [l for l in lines if l['id'] == pid]
        sd, ed = max(f['_sday'], 1), min(f['_eday'], D)
        hari = max(0, ed - sd + 1 - (1 if (f['_exday'] and sd <= f['_exday'] <= ed) else 0))
        berlaku = sum(1 for a in rows if a['nP'] > 0)
        jual = sum(a['jalan'] for a in rows)
        qf = sum(a['qf'] for a in rows); sf = sum(a['sf'] for a in rows)
        qp = sum(a['qp'] for a in rows); sp = sum(a['sp'] for a in rows)
        has_code = any(promo_has_code(l) for l in pl)
        T_P = sum(a['T_P'] for a in rows)
        eq = sum(a['ExpQ'] for a in rows); aq = sum(a['ActQ'] for a in rows)
        et = sum(a['ExpT'] for a in rows); at = sum(a['ActT'] for a in rows)
        upq = (aq / eq - 1) if eq > 0 else None
        upt = (at / et - 1) if et > 0 else None
        incr = (at - et) if upt is not None else None
        biaya = sum(a['biaya'] for a in rows)
        eff = (incr / biaya) if (incr is not None and biaya > 0) else None
        cek = sum(a['cek'] for a in rows)
        nbsum = sum(a['nB'] for a in rows if a['nP'] > 0)
        hari_pemb = (nbsum / berlaku) if berlaku > 0 else 0
        upn = [a['upT'] for a in rows if a['upT'] is not None]
        pos = (sum(1 for x in upn if x > 0) / len(upn)) if upn else None
        if hari == 0:
            verdict = 'DI LUAR PERIODE'
        elif upt is not None:
            verdict = 'EFEKTIF' if upt >= naik else ('CUKUP' if upt >= turun else 'TIDAK EFEKTIF')
        elif upq is not None:
            verdict = ('EFEKTIF' if upq >= naik else ('CUKUP' if upq >= turun else 'TIDAK EFEKTIF')) + ' (level item)'
        else:
            verdict = 'BELUM BISA DINILAI'
        adopsi = ((qp / qf) if qf > 0 else None) if has_code else None
        notes = []
        if hari > 0 and upt is None and upq is None:
            notes.append('Tidak ada hari non-promo sbg pembanding bulan ini.')
        if hari > 0 and jual < berlaku:
            notes.append(f'{berlaku - jual} dari {berlaku} outlet belum jual promo.')
        if cek > 0:
            notes.append(f'Harga di {cek} baris outlet-menu beda dari master.')
        if adopsi is not None and adopsi < 0.5 and qf > 0:
            notes.append(f'Button promo kurang dipakai (adopsi {adopsi:.0%}).')
        if upt is not None and upq is not None and upt < naik and upq >= naik:
            notes.append('Qty item naik tapi sales total outlet tidak ikut naik: indikasi kanibalisasi / diskon menggerus nilai.')
        if upt is not None and hari_pemb < 7:
            notes.append(f'Hanya {hari_pemb:.0f} hari pembanding per outlet: hasil indikatif.')
        # profit
        sc = sum(a['sales_cogs'] for a in rows); cg_ = sum(a['cogs'] for a in rows); bc = sum(a['biaya_cogs'] for a in rows)
        prof = dict(sales=sf, cakupan=(sc / sf if sf > 0 else None), cogs=cg_, gp=(sc - cg_) if cg_ > 0 else None,
                    gm=((sc - cg_) / sc) if (cg_ > 0 and sc > 0) else None, biaya=bc, sales_norm=(sc + bc) if cg_ > 0 else None)
        prof['gm_norm'] = ((prof['sales_norm'] - cg_) / prof['sales_norm']) if (prof['sales_norm'] and prof['sales_norm'] > 0) else None
        prof['gp_norm'] = (prof['sales_norm'] - cg_) if prof['sales_norm'] is not None else None
        if prof['gp'] is not None and bc > 0:
            prof['be'] = (prof['gp_norm'] / prof['gp'] - 1) if prof['gp'] > 0 else 'GP promo <= 0'
        else:
            prof['be'] = None
        if prof['gp'] is None:
            prof['kes'] = 'COGS belum ada di MASTER_COGS'
        elif bc == 0:
            prof['kes'] = ('Promo gratis: biaya COGS {:,.0f}'.format(-prof['gp']) if prof['gp'] < 0 else 'Tanpa diskon harga')
        elif isinstance(prof['be'], str):
            prof['kes'] = 'GP promo <= 0: harga promo di bawah COGS'
        elif upq is not None:
            prof['kes'] = 'IMPAS TERCAPAI (GP naik/tetap)' if upq >= prof['be'] else 'GP TURUN (uplift < break-even)'
        else:
            prof['kes'] = 'BUTUH kenaikan qty {:.0%} agar GP tidak turun'.format(prof['be'])
        pnote = []
        if prof['cakupan'] is not None and prof['cakupan'] < 0.99:
            pnote.append(f"COGS baru mencakup {prof['cakupan']:.0%} sales; sisanya belum ada di MASTER_COGS.")
        if prof['gm'] is not None and prof['gm_norm'] is not None:
            pnote.append(f"Diskon menurunkan GM {(prof['gm_norm'] - prof['gm']) * 100:.1f} poin.")
        prof['catatan'] = ' '.join(pnote)
        promos.append(dict(id=pid, nama=f['nama'], tipe=f['tipe'], start=f['start'], end=f['end'], hari=hari, berlaku=berlaku, jual=jual,
                           penetrasi=(jual / berlaku) if berlaku else None, qty=qf, sales=sf,
                           sales_btn=(sp if has_code else sf), adopsi=adopsi, kontrib=(sf / T_P) if T_P > 0 else None,
                           up_item=upq, up_outlet=upt, incr=incr, biaya=biaya, eff=eff, cek=cek, verdict=verdict,
                           hari_pemb=hari_pemb, pos=pos, catatan=' '.join(notes), has_code=has_code, profit=prof, upS=((sum(a['ActS'] for a in rows) / sum(a['ExpS'] for a in rows) - 1) if sum(a['ExpS'] for a in rows) > 0 else None)))
    return dict(month=month, D=D, dates=dates, HL=HL, outlets=outlets, lines=lines, active=act, LO=LO, po=po, promos=promos)
