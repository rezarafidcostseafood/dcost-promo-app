import os, sys, re, time, tempfile, shutil, warnings, io
warnings.filterwarnings('ignore')
os.environ['DCOST_AUTOSTART'] = '0'; os.environ['ADMIN_EMAIL'] = 'admin@x.id'; os.environ['ADMIN_PASSWORD'] = 'Rahasia123!'
sys.path.insert(0, '/home/claude/webapp')
import app as A, master_io, db as dbm
tmp = tempfile.mkdtemp(); app = A.create_app({'DATA_DIR': tmp, 'TESTING': True}); c = app.test_client()
csrf = lambda h: re.search(r'name="csrf" value="([0-9a-f]+)"', h).group(1)
tok = csrf(c.get('/login').get_data(as_text=True)); c.post('/login', data=dict(csrf=tok, email='admin@x.id', password='Rahasia123!'))
def imp(path):
    tok = csrf(c.get('/master/promo').get_data(as_text=True))
    with open(path, 'rb') as f:
        r = c.post('/master/import', data=dict(csrf=tok, apa=['promo', 'outlet', 'cogs', 'setting'], file=(f, 'm.xlsx')), follow_redirects=True, content_type='multipart/form-data')
    return re.search(r'Diimpor: ([^<]+)', r.get_data(as_text=True)).group(1)
print('impor template :', imp('/home/claude/pc_template.xlsx'))
data = c.get('/master/export.xlsx').data
open('/home/claude/webapp/seed_master.xlsx', 'wb').write(data); open('/tmp/exp.xlsx', 'wb').write(data)
print('ekspor         :', len(data) // 1024, 'KB')
a = master_io.read_template('/home/claude/pc_template.xlsx'); 
print('impor ulang    :', imp('/tmp/exp.xlsx'))
b = master_io.read_template('/tmp/exp.xlsx')
same = all(x == y for x, y in zip(a['lines'], b['lines'])) and len(a['lines']) == len(b['lines']) and a['outlets'] == b['outlets'] and a['settings'] == b['settings'] and a['holidays'] == b['holidays'] and len(a['cogs']) == len(b['cogs'])
print('roundtrip master identik:', same)
shutil.rmtree(tmp, ignore_errors=True)
