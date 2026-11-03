"""Impor/ekspor master dari/ke file Excel template."""
import datetime as dt
import openpyxl

LINE_FIELDS = ['id', 'nama', 'tipe', 'status', 'src', 'menu', 'kode_normal_reg', 'kode_normal_xp', 'kode_promo_reg', 'kode_promo_xp', 'hn', 'disc', 'hp',
               'rm_diskon', 'start', 'end', 'scope', 'base_start', 'base_end', 'ex_date', 'note']
LINE_HEADERS = ['ID Promo', 'Nama Promo', 'Tipe Promo', 'Status Menu (New/Existing)', 'Sumber Data (UNGROUP/GROUP)', 'Nama Menu', 'Kode Normal Reguler', 'Kode Normal XPRESS',
                'Kode Promo Reguler', 'Kode Promo XPRESS / kode ke-2', 'Harga Normal (sebelum PB1)', 'Diskon %', 'Harga Promo (isi bila bukan %)', 'Sales di RM sudah diskon?',
                'Mulai', 'Selesai', 'Outlet berlaku', 'Baseline mulai', 'Baseline selesai', 'Tgl promo TIDAK berlaku', 'Catatan']
DATE_FIELDS = ('start', 'end', 'base_start', 'base_end', 'ex_date')
NUM_FIELDS = ('hn', 'disc', 'hp')


def _d(v):
    if v is None or v == '':
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return None


def _s(v):
    if v is None:
        return ''
    return str(v).strip()


def read_template(path):
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    out = {'lines': [], 'outlets': [], 'cogs': [], 'settings': {}, 'holidays': []}
    ws = wb['MASTER_PROMO']
    for row in ws.iter_rows(min_row=6, max_row=405, min_col=2, max_col=22, values_only=True):
        if not row[0]:
            continue
        ln = dict(zip(LINE_FIELDS, row))
        for k in LINE_FIELDS:
            if k in DATE_FIELDS:
                ln[k] = _d(ln[k])
            elif k in NUM_FIELDS:
                ln[k] = None if ln[k] in (None, '') else float(ln[k])
            else:
                ln[k] = _s(ln[k])
        out['lines'].append(ln)
    ws = wb['MASTER_OUTLET']
    for row in ws.iter_rows(min_row=6, max_row=105, min_col=2, max_col=6, values_only=True):
        if row[0]:
            out['outlets'].append(dict(name=_s(row[0]), kode=_s(row[1]), tipe=_s(row[2]) or 'REGULER', pavelle=_s(row[3]) or 'N', buka_override=_d(row[4])))
    if 'MASTER_COGS' in wb.sheetnames:
        ws = wb['MASTER_COGS']
        for row in ws.iter_rows(min_row=6, max_row=805, min_col=1, max_col=6, values_only=True):
            if row[0] and row[2] is not None:
                out['cogs'].append(dict(code=_s(row[0]), nama=_s(row[1]), cogs=float(row[2]), harga=row[3], gm=row[4], sumber=_s(row[5])))
    ws = wb['SETTING']
    g = lambda r: ws.cell(r, 2).value
    out['settings'] = dict(floor=_s(g(6)) or 'Main', src_single=_s(g(7)) or 'UNGROUP', src_group=_s(g(8)) or 'GROUP',
                           ambang_naik=float(g(10) or 0.05), ambang_turun=float(g(11) or 0.0), toleransi_harga=float(g(12) or 0.03))
    for r in range(16, 36):
        d = _d(ws.cell(r, 1).value)
        if d:
            out['holidays'].append(d)
    return out
