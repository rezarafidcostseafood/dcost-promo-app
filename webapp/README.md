# Analisa Promo D'Cost & A'Yummy (aplikasi web)

Aplikasi web untuk tim marketing: unggah data RM bulanan, lihat efektivitas promo, margin (GM%), dan perbandingan antar bulan.
Perhitungannya adalah pindahan dari template Excel, dan sudah diuji identik dengan Excel (250 nilai RINGKASAN & PROFIT bulan September: 0 selisih).

## Fitur
- Login email + kata sandi. **Admin yang mendaftarkan email siapa saja yang boleh masuk** (menu Pengguna). Peran: viewer (lihat), editor (unggah data & ubah master), admin (+kelola pengguna).
- **Data RM**: unggah file RM apa adanya, pilih bulannya di formulir (tidak perlu kolom bulan). Format kolom Kelompok yang tertukar dan bulan 28-31 hari dikenali otomatis.
- **Ringkasan**: uplift like-for-like (hari promo vs hari non-promo sejenis), adopsi, kontribusi, biaya diskon, kesimpulan EFEKTIF/CUKUP/TIDAK EFEKTIF.
- **Detail promo**: per menu, per tipe outlet, per outlet, tren harian. **Profit**: GM%, break-even diskon. **Perbandingan Bulan**: promo yang sama antar bulan. **Cek Data**: menyebut nama outlet/kode yang bermasalah.
- **Master** (promo, outlet, COGS) bisa diedit di web dan diimpor/diekspor ke Excel. Pengaturan: floor, ambang kesimpulan, hari libur.

## Cara pakai pertama kali
1. Jalankan aplikasi (lihat di bawah), buka alamatnya, login dengan ADMIN_EMAIL / ADMIN_PASSWORD (wajib ganti sandi).
2. Menu **Master > Impor dari Excel**: pilih `seed/master_awal.xlsx` (isi: 98 baris promo Agu-Sep 2026, 64 outlet, 484 kode COGS, pengaturan), centang semua, Impor.
3. Menu **Data RM**: pilih bulan + unggah file RM (proses 1-3 menit). Ulangi untuk tiap bulan.
4. Menu **Pengguna**: tambahkan email anggota tim + peran. Sistem membuat kata sandi sementara (tampil sekali) yang Anda kirim ke orangnya; mereka diminta menggantinya.
5. Tiap bulan: unggah RM baru, tambahkan promo baru di Master > Promo (promo lama jangan dihapus), cek menu **Cek Data**, baca Ringkasan.

## Menjalankan
**A. Di komputer sendiri (uji coba / dipakai di jaringan kantor)** - butuh Python 3.10+ terpasang.
- Windows: edit 2 baris atas `start.bat` (email & sandi admin), klik dua kali. Mac/Linux: edit `start.sh`, jalankan `./start.sh`.
- Buka http://localhost:8000 . Rekan sekantor: http://IP-KOMPUTER-ANDA:8000 (komputer harus menyala; mungkin perlu izin firewall).
- Ini http biasa (tanpa enkripsi): cukup untuk jaringan kantor, jangan dibuka ke internet.

**B. Online (hosting)** - pakai Docker image dari `Dockerfile`. Syarat yang tidak boleh dilewat:
- **Disk permanen** dipasang ke `/data` (isi: database & data RM). Tanpa disk, data hilang tiap restart.
- Akses lewat **https** (hosting biasanya menyediakan otomatis) dan set `COOKIE_SECURE=1`.
- Isi variabel lingkungan: `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `SECRET_KEY`, `DATA_DIR=/data` (lihat `.env.example`).
- Jalankan **1 worker** (sudah di Dockerfile) karena cache & proses unggah ada di memori.
- `render.yaml` adalah contoh untuk Render.com (belum diuji). Platform lain (Railway, Fly.io, VPS) prinsipnya sama.
- Perkiraan sumber daya: RAM >= 1 GB (disarankan 2 GB), disk 5 GB cukup untuk beberapa tahun.

## Keamanan & perawatan
- Data berisi penjualan perusahaan. Gunakan sandi kuat, nonaktifkan akun anggota yang keluar (Pengguna > Nonaktifkan).
- Percobaan login gagal dibatasi (5x / 15 menit). Form dilindungi token CSRF. Tidak ada kirim email: lupa sandi = admin reset.
- **Backup**: salin folder `DATA_DIR` secara berkala (berisi `app.db` dan `rm/*.npz`). Pulihkan dengan menaruhnya kembali.
- Pembaruan aplikasi: ganti file kode, jalankan ulang; data di `DATA_DIR` tetap.

## Batasan yang perlu diketahui
- Login memakai kata sandi, bukan "Login dengan Google". Pembatasan domain email tidak otomatis: hanya email yang didaftarkan admin yang bisa masuk.
- Tanpa kirim email (butuh SMTP): belum ada "lupa kata sandi" mandiri.
- Promo yang jalan sebulan penuh tanpa hari pembanding tetap "BELUM BISA DINILAI" (keterbatasan metode, bukan bug). Gross profit belum menghitung biaya lain.
- Aplikasi ini sudah diuji di mesin pengembangan (HTTP lokal), belum diuji di hosting sungguhan.

## Struktur kode
`app.py` (rute & login), `engine.py` (mesin hitung), `views.py` (detail, perbandingan, cek data), `rmload.py` (baca RM), `master_io.py` (impor Excel), `db.py`, `charts.py`, `templates/`, `static/`.
`tests_internal/` berisi skrip uji (butuh data RM asli; path di dalamnya perlu disesuaikan).
