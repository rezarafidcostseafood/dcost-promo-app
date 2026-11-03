import json
import sqlite3
import datetime as dt
from flask import g, current_app

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT, role TEXT NOT NULL DEFAULT 'viewer',
  pw_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, must_change INTEGER NOT NULL DEFAULT 0, created_at TEXT, last_login TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS holidays(d TEXT PRIMARY KEY, note TEXT);
CREATE TABLE IF NOT EXISTS outlets(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, kode TEXT, tipe TEXT DEFAULT 'REGULER', pavelle TEXT DEFAULT 'N', buka_override TEXT);
CREATE TABLE IF NOT EXISTS lines(id INTEGER PRIMARY KEY, pid TEXT, nama TEXT, tipe TEXT, status TEXT, src TEXT, menu TEXT,
  kode_normal_reg TEXT, kode_normal_xp TEXT, kode_promo_reg TEXT, kode_promo_xp TEXT, hn REAL, disc REAL, hp REAL, rm_diskon TEXT,
  start TEXT, "end" TEXT, scope TEXT, base_start TEXT, base_end TEXT, ex_date TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS cogs(code TEXT PRIMARY KEY, nama TEXT, cogs REAL, harga REAL, gm REAL, sumber TEXT);
CREATE TABLE IF NOT EXISTS months(month TEXT PRIMARY KEY, filename TEXT, nrows INTEGER, days INTEGER, uploaded_by TEXT, uploaded_at TEXT);
"""

DEFAULTS = dict(floor='Main', src_single='UNGROUP', src_group='GROUP', ambang_naik=0.05, ambang_turun=0.0, toleransi_harga=0.03, ver=1)
DATE_COLS = ('start', 'end', 'base_start', 'base_end', 'ex_date')


def connect(path):
    c = sqlite3.connect(path, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA foreign_keys=ON')
    return c


def get_db():
    if 'db' not in g:
        g.db = connect(current_app.config['DB_PATH'])
    return g.db


def close_db(e=None):
    d = g.pop('db', None)
    if d is not None:
        d.close()


def init_db(path):
    c = connect(path)
    c.executescript(SCHEMA)
    for k, v in DEFAULTS.items():
        c.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)', (k, json.dumps(v)))
    c.commit()
    c.close()


def get_settings(c):
    s = {r['key']: json.loads(r['value']) for r in c.execute('SELECT * FROM settings')}
    for k, v in DEFAULTS.items():
        s.setdefault(k, v)
    s['holidays'] = {dt.date.fromisoformat(r['d']) for r in c.execute('SELECT d FROM holidays')}
    return s


def set_setting(c, key, value):
    c.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, json.dumps(value)))


def bump(c):
    set_setting(c, 'ver', int(get_settings(c)['ver']) + 1)


def _d(v):
    return dt.date.fromisoformat(v) if v else None


def load_master(c):
    lines = []
    for r in c.execute('SELECT * FROM lines ORDER BY id'):
        d = dict(r)
        d['line_id'] = d.pop('id')
        d['id'] = d.pop('pid') or ''
        for k in DATE_COLS:
            d[k] = _d(d[k])
        for k in ('nama', 'tipe', 'status', 'src', 'menu', 'kode_normal_reg', 'kode_normal_xp', 'kode_promo_reg', 'kode_promo_xp', 'rm_diskon', 'scope', 'note'):
            d[k] = (d[k] or '').strip()
        lines.append(d)
    outlets = []
    for r in c.execute('SELECT * FROM outlets ORDER BY name COLLATE NOCASE'):
        d = dict(r)
        d['buka_override'] = _d(d['buka_override'])
        outlets.append(d)
    cogs = {r['code']: r['cogs'] for r in c.execute('SELECT code,cogs FROM cogs')}
    return dict(lines=lines, outlets=outlets), cogs


def months_list(c):
    return [dict(r) for r in c.execute('SELECT * FROM months ORDER BY month')]
