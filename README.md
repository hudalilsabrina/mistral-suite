# Mistral Suite

Factory akun **Mistral AI** + panen **API key** (`mstrl_`) otomatis.
**Pure HTTP — tanpa browser.** Register → verify email → mint key.

> Bundle awal dari teman; diadaptasi ke tempik (self-hosted temp-mail) dan
> dirapikan jadi suite lengkap.

## Cara kerja

```
1. buat inbox tempik
2. Ory register:  GET  /self-service/registration/api
                  POST ui.action {csrf_token, traits.email, password, method=password}
                  -> session_token (ory_st_...)
3. verify:        GET  /self-service/verification/api  (X-Session-Token)
                  POST ui.action {email, method=code}  -> email berisi kode
4. baca kode dari inbox + ambil FLOW ID dari LINK EMAIL
   (PENTING: Ory mengikat kode ke flow di link email, BUKAN flow dari API)
5. submit kode:   POST /self-service/verification?flow=<flow_link> {code}
                  -> state = passed_challenge
6. login browser flow -> cookie ory_session_*
   -> GET /api/users/me (set csrftoken)
   -> POST /api/billing/api-keys -> key mstrl_...
```

## 🔑 Kunci keberhasilan (temuan penting)

1. **Flow ID dari link email** — kalau pakai flow dari API, hasilnya selalu
   `sent_email` (bukan `passed_challenge`). Kode terikat ke flow di link email.
2. **Login via browser flow** (bukan API) — butuh cookie `ory_session_*` +
   `csrftoken` (double-submit) untuk mint key.

## Free tier

Model yang **bisa dipakai** dengan key farm (gratis):
- `ministral-8b-latest`
- `open-mistral-nemo`
- `mistral-tiny`

Model besar (`mistral-large-latest`) → `tier_not_allowed`.

## Instalasi

```bash
python3 -m venv .venv
.venv/bin/pip install rich requests
cp config.example.toml config.toml   # isi endpoint tempmail Anda
```

Butuh `curl` di PATH (dipakai untuk HTTP).

## Command

```bash
./run.sh harvest 1     # buat 1 akun + panen API key
./run.sh harvest 5     # 5 akun
./run.sh test          # uji semua key (chat ke model free tier)
./run.sh report        # ringkasan akun
./run.sh sync          # inject key ke 9router
./run.sh probe         # cek API hidup
```

Batch (resume-safe):

```bash
.venv/bin/python batch.py 10 --delay 10
```

## Gateway

OpenAI-compatible: `https://api.mistral.ai/v1`

```bash
curl https://api.mistral.ai/v1/chat/completions \
  -H "Authorization: Bearer mstrl_..." \
  -H "Content-Type: application/json" \
  -d '{"model":"ministral-8b-latest","messages":[{"role":"user","content":"hi"}]}'
```

## Format akun (`accounts.txt`)

```
email:password:apikey:status
```

## ⚠️ Catatan

- **Rate limit** per key/IP bisa muncul (`rate_limited` 1300) — pakai jeda antar akun.
- Beberapa domain temp-mail **tanpa MX** → email tidak sampai; tempik dipilih
  karena domainnya punya MX aktif.
- Key hanya tampil **sekali** saat dibuat.

## Atribusi

- Bundle awal: dari teman (mistral_farm_bundle)
- Sumber kode temp-mail: **[hirotomasato/tempik](https://github.com/hirotomasato/tempik)**
  (lihat `src/tempmail.py`)

## Struktur

```
main.py            # CLI
batch.py           # batch runner (resume-safe)
src/mistral.py     # engine: register + verify + mint key
src/tempmail.py    # client temp-mail (tempik)
src/inboxstore.py  # riwayat inbox
src/router9.py     # sync ke 9router
config.example.toml
```

## Disclaimer

Untuk penggunaan pribadi/edukasi. Hormati Terms of Service Mistral AI.
