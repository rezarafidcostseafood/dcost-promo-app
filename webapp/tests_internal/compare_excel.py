import sys, datetime as dt, warnings, openpyxl, pandas as pd
warnings.filterwarnings('ignore')
sys.path.insert(0, '/home/claude/webapp'); sys.path.insert(0, '/home/claude/webapp/tests')
import engine, rmload, master_io
mst = master_io.read_template('/home/claude/pc_template.xlsx')
cogs = {c['code']: c['cogs'] for c in mst['cogs']}
st = dict(mst['settings']); st['holidays'] = set(mst['holidays'])
rm = rmload.df_to_rm(pd.read_pickle('/home/claude/data_sep.pkl'))
md = engine.MonthData(rm, 'Main')
res = engine.analyze(dt.date(2026, 9, 1), md, dict(lines=[dict(l) for l in mst['lines']], outlets=[dict(o) for o in mst['outlets']]), st, cogs)
P = {p['id']: p for p in res['promos']}
wb = openpyxl.load_workbook('/home/claude/pc_demo.xlsx', data_only=True, read_only=True)
bad = 0; n = 0
def cmp(name, a, b, tol=1e-6):
    global bad, n
    n += 1
    if isinstance(b, (int, float)) and isinstance(a, (int, float)):
        ok = abs(a - b) <= max(tol, abs(b) * 1e-6)
    else:
        ok = (a in (None, 'n/a', '') and b in (None, 'n/a', '')) or a == b
    if not ok:
        bad += 1; print('  BEDA', name, 'python=', a, 'excel=', b)
for row in wb['RINGKASAN'].iter_rows(min_row=8, max_row=47, min_col=2, max_col=24, values_only=True):
    if not row[0]: continue
    p = P.get(row[0])
    if p is None: print('promo hilang di python', row[0]); bad += 1; continue
    x = lambda v: None if v in ('n/a', '') else v
    f = {'hari': row[4], 'berlaku': row[5], 'jual': row[6], 'qty': row[8], 'sales': row[9], 'sales_btn': row[10], 'adopsi': x(row[11]), 'kontrib': x(row[12]), 'up_item': x(row[13]),
         'up_outlet': x(row[14]), 'incr': x(row[15]), 'biaya': row[16], 'eff': x(row[17]), 'cek': row[18], 'verdict': row[19], 'hari_pemb': row[20], 'pos': x(row[21])}
    print(row[0], 'dicek', len(f), 'kolom')
    for k, v in f.items():
        a = p[k]
        cmp(f'{row[0]}.{k}', a, v, 1e-3 if k in ('adopsi','kontrib','up_item','up_outlet','pos','eff','hari_pemb') else 1.0)
print('PROFIT')
for row in wb['PROFIT'].iter_rows(min_row=8, max_row=47, max_col=15, values_only=True):
    if not row[0]: continue
    p = P[row[0]]['profit']
    x = lambda v: None if v in ('n/a', '') else v
    for k, v in (('cakupan', x(row[3])), ('cogs', row[4]), ('gp', x(row[5])), ('gm', x(row[6])), ('biaya', row[7]), ('gm_norm', x(row[9])), ('be', x(row[11])), ('kes', row[13])):
        cmp(f'profit {row[0]}.{k}', p[k], v, 1.0 if k in ('cogs', 'gp', 'biaya') else 1e-3)
print('dibandingkan', n, 'nilai; beda', bad)
