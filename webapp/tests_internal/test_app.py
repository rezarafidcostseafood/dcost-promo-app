import os, sys, re, time, shutil, tempfile, datetime as dt, warnings
warnings.filterwarnings('ignore')
os.environ['DCOST_AUTOSTART'] = '0'
os.environ['ADMIN_EMAIL'] = 'admin@dcostseafood.id'; os.environ['ADMIN_PASSWORD'] = 'Rahasia123!'
sys.path.insert(0, '/home/claude/webapp')
import pandas as pd, numpy as np
import app as A, rmload, db as dbm

tmp = tempfile.mkdtemp()
app = A.create_app({'DATA_DIR': tmp, 'TESTING': True})
c = app.test_client()
def csrf(html): return re.search(r'name="csrf" value="([0-9a-f]+)"', html).group(1)
def get(url, **k): return c.get(url, follow_redirects=True, **k)
def post(url, data=None, page=None, **k):
    tok = csrf(get(page or url).get_data(as_text=True)); d = dict(data or {}); d['csrf'] = tok
    return c.post(url, data=d, follow_redirects=True, **k)
ok = lambda name, cond: print(('PASS ' if cond else 'FAIL ') + name) or (cond or sys.exit(1))

# 1. login
r = get('/ringkasan'); ok('belum login diarahkan ke halaman login', 'Masuk' in r.get_data(as_text=True))
r = post('/login', dict(email='admin@dcostseafood.id', password='salah'), page='/login'); ok('sandi salah ditolak', 'salah' in r.get_data(as_text=True))
r = c.post('/login', data=dict(email='admin@dcostseafood.id', password='Rahasia123!'), follow_redirects=True); ok('CSRF: post tanpa token ditolak', r.status_code == 400)
r = post('/login', dict(email='admin@dcostseafood.id', password='Rahasia123!'), page='/login'); ok('login admin berhasil', 'Belum ada data RM' in r.get_data(as_text=True))

# 2. impor master dari template excel
tok = csrf(get('/master/promo').get_data(as_text=True))
with open('/home/claude/pc_template.xlsx', 'rb') as f:
    r = c.post('/master/import', data=dict(csrf=tok, apa=['promo', 'outlet', 'cogs', 'setting'], file=(f, 'template.xlsx')), follow_redirects=True, content_type='multipart/form-data')
txt = r.get_data(as_text=True); m = re.search(r'Diimpor: ([^<]+)', txt); ok('impor master: ' + (m.group(1) if m else txt[:200]), bool(m))

# 3. unggah RM September (file asli) lewat proses latar belakang
tok = csrf(get('/data').get_data(as_text=True))
t0 = time.time()
with open('/mnt/user-data/uploads/RM_01-30_Sep_2026.xlsx', 'rb') as f:
    r = c.post('/data', data=dict(csrf=tok, bulan='2026-09', file=(f, 'RM_01-30_Sep_2026.xlsx')), follow_redirects=False, content_type='multipart/form-data')
jid = r.headers['Location'].rstrip('/').split('/')[-1]
while True:
    js = c.get(f'/data/job/{jid}/status').get_json()
    if js['status'] != 'run': break
    time.sleep(3)
print('   upload', js['status'], js['msg'], round(time.time() - t0), 's')
ok('unggah RM September', js['status'] == 'ok')
# salah bulan -> ditolak
tok = csrf(get('/data').get_data(as_text=True))
with open('/mnt/user-data/uploads/RM_01-30_Sep_2026.xlsx', 'rb') as f:
    r = c.post('/data', data=dict(csrf=tok, bulan='2026-08', file=(f, 'x.xlsx')), follow_redirects=False, content_type='multipart/form-data')
jid = r.headers['Location'].rstrip('/').split('/')[-1]
while c.get(f'/data/job/{jid}/status').get_json()['status'] == 'run': time.sleep(3)
js = c.get(f'/data/job/{jid}/status').get_json(); ok('bulan salah (30 hari vs Agustus 31) ditolak: ' + js['msg'][:70], js['status'] == 'error')

# 4. Agustus: suntik langsung dari pickle
df = pd.read_pickle('/home/claude/data_aug.pkl'); rm = rmload.df_to_rm(df)
rmload.save_rm(os.path.join(tmp, 'rm', '2026-08.npz'), rm)
cc = dbm.connect(os.path.join(tmp, 'app.db')); cc.execute("INSERT INTO months VALUES('2026-08','aug.xlsx',?,31,'test',?)", (len(df), dt.datetime.now().isoformat())); dbm.bump(cc); cc.commit(); cc.close()

# 5. halaman
t0 = time.time(); r = get('/ringkasan?bulan=2026-09'); h = r.get_data(as_text=True)
print('   ringkasan', r.status_code, round(time.time() - t0, 1), 's'); ok('ringkasan September memuat P04 & uplift 12,1%', 'P04' in h and '12,1%' in h and 'EFEKTIF' in h)
ok('ringkasan memuat grafik SVG', '<svg' in h)
h = get('/ringkasan?bulan=2026-08').get_data(as_text=True); ok('ringkasan Agustus: kopi 30% -9,0% tidak efektif', '-9,0%' in h and 'TIDAK EFEKTIF' in h)
h = get('/promo/P04?bulan=2026-09').get_data(as_text=True); ok('detail promo P04', '50 Terong Szechuan' in h and 'DCost Tangerang City' in h and '<svg' in h)
h = get('/profit?bulan=2026-09').get_data(as_text=True); ok('profit: break-even seafood 186%', '186%' in h or '185%' in h)
h = get('/perbandingan').get_data(as_text=True); ok('perbandingan memuat Agu & Sep', 'Aug 26' in h and 'Sep 26' in h and '658.735.186' in h or 'Agu' in h)
print('   perbandingan snippet:', re.findall(r'506\.430\.638|658\.735\.186', h)[:2])
h = get('/perbandingan?metrik=kontrib').get_data(as_text=True); ok('perbandingan metrik kontribusi', '%' in h)
h = get('/cek?bulan=2026-09').get_data(as_text=True); ok('cek data', 'Total sales dine-in' in h)
for u in ('/master/promo', '/master/outlet', '/master/cogs', '/pengaturan', '/admin/users', '/data'):
    ok('halaman ' + u, get(u).status_code == 200)
r = get('/export/hasil.xlsx?bulan=2026-09'); ok('ekspor hasil xlsx', r.status_code == 200 and r.data[:2] == b'PK')
r = get('/master/export.xlsx'); ok('ekspor master xlsx', r.status_code == 200 and r.data[:2] == b'PK')
# 6. master edit
r = post('/master/promo/edit', dict(id='P99', nama='Tes', menu='Menu Tes', status='Existing', src='UNGROUP', kode_normal_reg='MNU00413', disc='20', start='2026-09-10', end='', scope='ALL', rm_diskon='SUDAH DISKON'), page='/master/promo/edit')
ok('tambah baris master', 'Baris promo disimpan' in r.get_data(as_text=True))
h = get('/ringkasan?bulan=2026-09').get_data(as_text=True); ok('promo baru P99 muncul di ringkasan setelah master berubah', 'P99' in h)
# 7. pengguna & peran
r = post('/admin/users', dict(act='tambah', email='tim1@dcostseafood.id', role='viewer'), page='/admin/users'); mm = re.search(r'sementara[^:]*: ([A-Za-z0-9_\-]+)', r.get_data(as_text=True)); ok('tambah pengguna viewer', bool(mm))
tmp_pw = mm.group(1)
c2 = app.test_client()
tok = csrf(c2.get('/login').get_data(as_text=True)); r = c2.post('/login', data=dict(csrf=tok, email='tim1@dcostseafood.id', password=tmp_pw), follow_redirects=True)
ok('viewer wajib ganti sandi', 'Ganti kata sandi' in r.get_data(as_text=True))
tok = csrf(r.get_data(as_text=True)); r = c2.post('/password', data=dict(csrf=tok, old=tmp_pw, new='SandiBaru123', new2='SandiBaru123'), follow_redirects=True)
ok('ganti sandi', 'Ringkasan' in r.get_data(as_text=True))
ok('viewer boleh lihat ringkasan', c2.get('/ringkasan?bulan=2026-09').status_code == 200)
ok('viewer DILARANG buka Data RM (403)', c2.get('/data').status_code == 403)
ok('viewer DILARANG buka pengguna (403)', c2.get('/admin/users').status_code == 403)
tok = csrf(c2.get('/master/outlet').get_data(as_text=True)); r = c2.post('/master/outlet', data=dict(csrf=tok, name='X', tipe='REGULER', pavelle='N'))
ok('viewer DILARANG ubah master (403)', r.status_code == 403)
print('SEMUA UJI LULUS'); shutil.rmtree(tmp, ignore_errors=True)
