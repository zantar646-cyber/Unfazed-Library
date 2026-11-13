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
- `ANNAS_ARCHIVE_BASE_URL`: e.g. `https://annas-archive.org` (official domains rotate: `.org` / `.se` / `.li`)
- `ANNAS_ARCHIVE_SECRET_KEY`: Anna's Archive API secret (optional)
- `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`: Route source requests through a proxy if Cloudflare blocks Vercel's IPs
- `NO_PROXY`: Hosts that should bypass the proxy

### Optional Cache & Security
- `REDIS_URL`: Upstash Redis connection string (falls back to in-memory cache if omitted)
- `WEBHOOK_SECRET`: Secret string to authenticate Telegram updates
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
