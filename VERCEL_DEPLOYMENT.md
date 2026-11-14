# 🚀 Vercel Serverless Deployment Guide

This Telegram Book Bot is fully compatible with **Vercel Serverless Functions**.

---

## 🏗 Architecture on Vercel

```
Telegram API ──(HTTPS POST)──▶ Vercel Serverless (api/index.py)
                                     │
                                     ▼
                               Aiogram 3 Dispatcher (All 9 Routers)
                                     │
                  ┌──────────────────┴──────────────────┐
                  ▼                                     ▼
   Database (PostgreSQL / SQLite)             Redis / In-Memory Cache
```

---

## 📋 Step 1: Push Project to GitHub

```powershell
git add .
git commit -m "Add Vercel serverless compatibility"
git push origin main
```

---

## ⚡ Step 2: Import Project in Vercel

1. Log in to [Vercel](https://vercel.com).
2. Click **"Add New..."** > **"Project"** and select your GitHub repository.
3. Framework Preset: Leave as **Other** (Vercel automatically detects `vercel.json` and `api/index.py`).
4. Under **Environment Variables**, add:

### Required Variables
- `BOT_TOKEN`: Your Telegram Bot token from @BotFather
- `API_BASE_URL`: `https://z-library.ec`
- `SINGLELOGIN_URL`: `https://z-library.sk`
- `ZLIBRARY_REMIX_USERKEY`: Your Z-Library remix token
- `ZLIBRARY_REMIX_USERID`: Your Z-Library user ID

### Database for Vercel
> On Vercel, the root filesystem is read-only.
> For persistent storage across cold starts, connect a free PostgreSQL database (e.g., from Neon.tech or Supabase):
- `DATABASE_URL`: `postgresql://user:password@ep-xyz.neon.tech/neondb?sslmode=require`

*(If omitted and `USE_SQLITE=true`, the bot uses `/tmp/digital_library.db` which is writable).*

### Optional Search Sources & Proxy
- `ANNAS_ARCHIVE_BASE_URL`: Anna's Archive mirror. Current official domains are `.gl`, `.pk`, `.gd` (older `.org`/`.se`/`.li` are dead or parked). The client falls back across them automatically.
- `ANNAS_ARCHIVE_SECRET_KEY`: Anna's Archive API secret (optional)
- `API_BASE_URL` / `MIRRORS`: Z-Library mirror(s) to try. `https://z-library.ec` and `https://z-lib.gl` still answer `/eapi/book/search`.
- `ZLIBRARY_EMAIL`, `ZLIBRARY_PASSWORD`, `ZLIBRARY_REMIX_USERKEY`, `ZLIBRARY_REMIX_USERID`: Z-Library session. **Local `.env` values are not deployed to Vercel** — set them in the Vercel dashboard.
- `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`: Route source requests through a proxy if Cloudflare/DDoS-Guard blocks Vercel's IPs
- `NO_PROXY`: Hosts that should bypass the proxy

### File Converter Bot Bridge
The Library bot and the Converter bot never talk to each other. Downloaded files are stored in a **shared private Telegram channel**, and the Library bot sends the user to the Converter bot with a `?start=convert_<message_id>` deep link. The Converter bot uses `copyMessage` with that channel id, so no `file_id` crosses bots.

1. Create a private channel, add **both bots as administrators** (post messages is enough).
2. Set the same values in both projects:

Library bot (Vercel):
- `STORAGE_CHANNEL_ID`: numeric channel id, e.g. `-1001234567890`
- `CONVERTER_BOT_USERNAME`: converter username without `@` (default `Unfazed_File_Convertor_bot`)
- `DEEPLINK_SECRET`: optional shared HMAC secret; strongly recommended so users cannot enumerate channel message ids

Converter bot (`.env`):
- `STORAGE_CHANNEL_ID`: same channel id
- `DEEPLINK_SECRET`: same secret

Without `STORAGE_CHANNEL_ID`, downloads still work but the file card shows no Convert button. With `DEEPLINK_SECRET` set on only one side, links are rejected by design.

Z-Library's `/dl/<token>` pages ship a SHA-1 proof-of-work challenge instead of a normal file response. The bot solves it in pure Python (`bot/utils/zl_challenge.py`), so Z-Library downloads work on Vercel even though there is no browser runtime. Anna's Archive is still DDoS-Guard protected and falls back to LibGen.

### Source Diagnostics
After deploying, check which sources are actually reachable **from Vercel's network**:
```text
https://your-app-name.vercel.app/api/sources_check?token=YOUR_DIAG_TOKEN
```
`DIAG_TOKEN` falls back to `WEBHOOK_SECRET`. The report shows the egress IP/ASN, which Z-Library/Anna's Archive/LibGen endpoints respond, whether a proxy is configured, and which env vars are set (never their values).

### Optional Cache & Security
- `REDIS_URL`: Upstash Redis connection string (falls back to in-memory cache if omitted)
- `WEBHOOK_SECRET`: Secret string to authenticate Telegram updates
- `DIAG_TOKEN`: Token for `/api/sources_check` (falls back to `WEBHOOK_SECRET`)
- `ADMIN_IDS`: Comma-separated admin Telegram IDs

5. Click **Deploy**.

---

## 🔗 Step 3: One-Click Webhook Registration

Once Vercel deploys, open your browser and navigate to:
```text
https://your-app-name.vercel.app/api/set_webhook
```
You will receive a confirmation JSON indicating the Telegram webhook has been registered to `https://your-app-name.vercel.app/api/webhook`.

---

## 🔍 Step 4: Verification Endpoints

- **Live Status**: `https://your-app-name.vercel.app/`
- **Webhook Diagnostics**: `https://your-app-name.vercel.app/api/webhook_info`
- **Bot Telemetry**: `https://your-app-name.vercel.app/api/stats`
- **Cron Alerts**: Automatically run once a day via Vercel Cron at `/api/cron/alerts`
