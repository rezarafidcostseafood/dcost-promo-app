"""Membaca file RM (xlsx) dan menyimpannya sebagai array numpy per bulan."""
import re
import zipfile
import numpy as np
import pandas as pd


def _col2n(c):
    n = 0
    for ch in c:
        n = n * 26 + ord(ch) - 64
    return n


def _sheet_files(z):
    wb = z.read('xl/workbook.xml').decode('utf8')
    rels = z.read('xl/_rels/workbook.xml.rels').decode('utf8')
    out = []
    for m in re.finditer(r'<sheet [^>]*?name="([^"]+)"[^>]*?r:id="([^"]+)"', wb):
        name, rid = m.groups()
        t = re.search(r'<Relationship [^>]*?Id="%s"[^>]*?Target="([^"]+)"' % rid, rels) or re.search(r'<Relationship [^>]*?Target="([^"]+)"[^>]*?Id="%s"' % rid, rels)
        if t:
            tgt = t.group(1)
            out.append((name, tgt if tgt.startswith('xl/') else 'xl/' + tgt.lstrip('/')))
    return out


def _parse_sheet(data, S):
    recs = []
    for m in re.finditer(r'<row [^>]*>(.*?)</row>', data, flags=re.S):
        d = {}
        for c in re.finditer(r'<c r="([A-Z]+)\d+"([^>]*?)(?:/>|>(.*?)</c>)', m.group(1), flags=re.S):
            ref, attr, body = c.groups()
            if not body:
                continue
            v = re.search(r'<v>(.*?)</v>', body)
            if not v:
                t = re.search(r'<is>.*?<t[^>]*>(.*?)</t>', body, flags=re.S)
                if t:
                    d[_col2n(ref)] = t.group(1)
                continue
            val = v.group(1)
            if 't="s"' in attr:
                val = S[int(val)]
            else:
                try:
                    val = float(val)
                except ValueError:
                    pass
            d[_col2n(ref)] = val
        recs.append(d)
    return recs


def parse_xlsx(path):
    """Cari sheet yang headernya memuat 'Store' dan 'Kode Menu', kembalikan DataFrame."""
    z = zipfile.ZipFile(path)
    ss = z.read('xl/sharedStrings.xml').decode('utf8') if 'xl/sharedStrings.xml' in z.namelist() else ''
    S = [''.join(re.findall(r'<t[^>]*>(.*?)</t>', i, flags=re.S)) for i in re.findall(r'<si>(.*?)</si>', ss, flags=re.S)]
    del ss
    for name, f in _sheet_files(z):
        raw = z.read(f).decode('utf8')
        head = _parse_sheet(raw[:200000].rsplit('</row>', 1)[0] + '</row>', S)[:1]
        if head and 'Store' in head[0].values() and 'Kode Menu' in head[0].values():
            recs = _parse_sheet(raw, S)
            del raw
            hdr = recs[0]
            cols = [str(hdr.get(i, f'c{i}')) for i in range(1, max(hdr) + 1)]
            df = pd.DataFrame([[r.get(i) for i in range(1, len(cols) + 1)] for r in recs[1:]], columns=cols)
            return df
        del raw
    raise ValueError('Sheet data RM tidak ditemukan (header harus memuat kolom "Store" dan "Kode Menu").')


def df_to_rm(df):
    cols = list(df.columns)
    tgl = [c for c in cols if re.fullmatch(r'Tgl \d+', str(c))]
    D = len(tgl)
    if D < 28 or D > 31:
        raise ValueError(f'Jumlah kolom "Tgl N" = {D}, seharusnya 28-31.')
    c0 = df.iloc[:, 0].astype(str)
    c1 = df.iloc[:, 1].astype(str)
    kel = np.where(c0.isin(['GROUP', 'UNGROUP']), c0, c1)
    fl = 'Florr' if 'Florr' in cols else cols[3]
    q = df[[f'Tgl {d}' for d in range(1, D + 1)]].apply(pd.to_numeric, errors='coerce').fillna(0).to_numpy(dtype=float)
    s = df[[f'Hrg {d}' for d in range(1, D + 1)]].apply(pd.to_numeric, errors='coerce').fillna(0).to_numpy(dtype=float)
    return dict(store=df['Store'].astype(str).to_numpy(), florr=df[fl].astype(str).to_numpy(), kel=kel, code=df['Kode Menu'].astype(str).to_numpy(), qty=q, sales=s, D=D)


def save_rm(path, rm):
    np.savez_compressed(path, store=np.asarray(rm['store'], dtype='U'), florr=np.asarray(rm['florr'], dtype='U'), kel=np.asarray(rm['kel'], dtype='U'), code=np.asarray(rm['code'], dtype='U'),
                        qty=rm['qty'], sales=rm['sales'], D=np.array(rm['D']))


def load_rm(path):
    z = np.load(path, allow_pickle=False)
    return dict(store=z['store'], florr=z['florr'], kel=z['kel'], code=z['code'], qty=z['qty'], sales=z['sales'], D=int(z['D']))
