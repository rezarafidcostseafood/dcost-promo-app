import sys, datetime as dt, pickle, time, numpy as np, pandas as pd, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, '/home/claude/webapp')
import engine, rmload, master_io
t0 = time.time()
mst = master_io.read_template('/home/claude/pc_template.xlsx')
print('master lines', len(mst['lines']), 'outlets', len(mst['outlets']), 'cogs', len(mst['cogs']), 'hol', mst['holidays'], mst['settings'])
cogs = {c['code']: c['cogs'] for c in mst['cogs']}
st = dict(mst['settings']); st['holidays'] = set(mst['holidays'])
def run(path, month):
    df = pd.read_pickle(path)
    if 'GROUP' in df.columns and 'Kelompok' not in df.columns:
        pass
    rm = rmload.df_to_rm(df)
    md = engine.MonthData(rm, 'Main')
    master = dict(lines=[dict(l) for l in mst['lines']], outlets=[dict(o) for o in mst['outlets']])
    res = engine.analyze(month, md, master, st, cogs)
    return res
for path, month in (('/home/claude/data_sep.pkl', dt.date(2026, 9, 1)), ('/home/claude/data_aug.pkl', dt.date(2026, 8, 1))):
    t = time.time(); res = run(path, month); print('\n===', month, 'detik', round(time.time() - t, 1))
    for p in res['promos']:
        f = lambda x, n=3: (round(x, n) if isinstance(x, float) else x)
        print(p['id'], p['hari'], p['berlaku'], p['jual'], round(p['qty']), round(p['sales']), f(p['adopsi']), f(p['kontrib']), f(p['up_item']), f(p['up_outlet']), f(p['incr'], 0), f(p['biaya'], 0), p['verdict'])

import views
print('\n--- views')
rm = rmload.df_to_rm(pd.read_pickle('/home/claude/data_sep.pkl')); md = engine.MonthData(rm, 'Main')
master = dict(lines=[dict(l) for l in mst['lines']], outlets=[dict(o) for o in mst['outlets']])
res = engine.analyze(dt.date(2026, 9, 1), md, master, st, cogs)
d = views.promo_detail(res, md, 'P04', st)
print('P04 menu', [(m['menu'], round(m['qp']), round(m['sp'])) for m in d['menu']][:3], 'tipe', [(t['tipe'], t['jual']) for t in d['tipe']], 'top outlet', d['outlets'][0]['outlet'], round(d['outlets'][0]['sf']))
infos = {}
for path, mo in (('/home/claude/data_aug.pkl', dt.date(2026, 8, 1)), ('/home/claude/data_sep.pkl', dt.date(2026, 9, 1))):
    m_ = engine.MonthData(rmload.df_to_rm(pd.read_pickle(path)), 'Main')
    infos[mo] = views.month_totals(m_, mo, master['lines'], 'UNGROUP')
months, pb = views.perbandingan(infos, master['lines'], dt.date(2026, 8, 1))
for r in pb:
    if r['id'] in ('P04', 'P08', 'P07', 'P09'):
        print(r['id'], [(round(c['sales']) if c['sales'] else None, c['hari']) for c in r['m'][:3]], 'mom', [round(c['mom'], 3) if c['mom'] is not None else None for c in r['m'][:3]])
