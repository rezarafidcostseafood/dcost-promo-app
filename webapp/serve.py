"""Menjalankan aplikasi. Windows/Mac/Linux: python serve.py  (butuh variabel lingkungan, lihat README)."""
import os
from app import create_app

app = create_app()
port = int(os.environ.get('PORT', '8000'))
if __name__ == '__main__':
    try:
        from waitress import serve
        print(f'Berjalan di http://0.0.0.0:{port}  (tekan Ctrl+C untuk berhenti)')
        serve(app, host='0.0.0.0', port=port, threads=4)
    except ImportError:
        print('waitress tidak terpasang, memakai server bawaan Flask (cukup untuk uji coba).')
        app.run(host='0.0.0.0', port=port, threaded=True)
