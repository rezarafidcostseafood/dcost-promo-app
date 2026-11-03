#!/bin/bash
# Jalankan aplikasi di Mac/Linux. Ubah dua baris berikut dulu.
export ADMIN_EMAIL=emailanda@dcostseafood.id
export ADMIN_PASSWORD=GantiSandiIni123
export PORT=8000
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q -r requirements.txt
python serve.py
