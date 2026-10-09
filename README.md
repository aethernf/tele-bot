# Deploy AethBot ke Railway (24/7 gratis)

## Yang perlu disiapkan
1. Akun GitHub
2. Akun Railway (daftar pakai GitHub di railway.app)
3. Repo GitHub berisi `keylist.lua` (repo worker lo yang sekarang)
4. GitHub Personal Access Token (PAT) dengan akses `repo`

## Langkah

### 1. Upload file bot ke GitHub
Buat repo baru (misal `aethbot`), upload 4 file dari folder ini:
- `bot.py`
- `requirements.txt`
- `Procfile`
- `start.sh`

### 2. Buat GitHub PAT
- Buka github.com → Settings → Developer settings → Personal access tokens → Tokens (classic)
- Generate new token → centang `repo` → copy token-nya

### 3. Deploy di Railway
- railway.app → New Project → Deploy from GitHub repo → pilih repo `aethbot`
- Railway otomatis detect Python + jalanin `Procfile`

### 4. Set Environment Variables
Di Railway → project → Variables, isi:

| Variable | Isi |
|---|---|
| `AETH_BOT_TOKEN` | Token dari @BotFather |
| `AETH_ADMIN_ID` | ID numerik lo dari @userinfobot |
| `AETH_REPO_DIR` | `/app/worker-repo` |
| `GITHUB_TOKEN` | PAT dari langkah 2 |
| `GITHUB_KEYLIST_REPO` | `username/nama-repo-keylist` (tanpa https://) |
| `CLOUDFLARE_API_TOKEN` | (opsional, buat /online) |
| `CLOUDFLARE_ACCOUNT_ID` | (opsional) |
| `CLOUDFLARE_KV_NAMESPACE_ID` | (opsional) |

### 5. Selesai
Railway akan deploy otomatis. Bot jalan 24/7 selama kredit gratis $5/bulan cukup
(bot kecil kayak gini biasanya cuma kepakai ~$1-2/bulan).

## Catatan
- Tiap `/create`, `/revoke`, dll → bot edit `keylist.lua` → git push ke repo keylist lo
- Worker lo yang baca dari repo itu otomatis dapat update (sesuai setup deploy worker lo)
- Kalau Railway kirim notif kredit mau habis, tinggal top-up $5 (≈Rp80rb) — awet berbulan-bulan buat bot sekecil ini
