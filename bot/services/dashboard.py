"""bot/services/dashboard.py — Web admin status & dashboard service (feature #14)."""
from __future__ import annotations

import asyncio
from aiohttp import web
from loguru import logger

from bot.database.service import db


async def handle_dashboard(request: web.Request) -> web.Response:
    try:
        stats = await db.get_dashboard_stats()
        new_today = await db.get_new_users_today()
        top_books = await db.get_top_downloaded_books(limit=5)
    except Exception as e:
        logger.warning(f"Error fetching dashboard stats: {e}")
        stats = {"total_users": 0, "active_users": 0, "total_books": 0, "total_downloads": 0, "total_favorites": 0}
        new_today = 0
        top_books = []

    book_rows = "".join(
        f"<tr><td>{idx}</td><td>{b.title[:45]}</td><td>{b.author or 'N/A'}</td><td><b>{b.download_count}</b></td></tr>"
        for idx, b in enumerate(top_books, 1)
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Digital Library Bot — Admin Dashboard</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 2rem; }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        h1 {{ color: #38bdf8; display: flex; align-items: center; gap: 0.5rem; }}
        .badge {{ background: #10b981; color: white; padding: 0.2rem 0.6rem; border-radius: 999px; font-size: 0.8rem; font-weight: bold; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin: 2rem 0; }}
        .card {{ background: #1e293b; padding: 1.5rem; border-radius: 0.75rem; border: 1px solid #334155; }}
        .card .title {{ font-size: 0.85rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }}
        .card .value {{ font-size: 2rem; font-weight: bold; color: #f8fafc; margin-top: 0.5rem; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; background: #1e293b; border-radius: 0.75rem; overflow: hidden; }}
        th, td {{ padding: 0.75rem 1rem; text-align: left; border-bottom: 1px solid #334155; }}
        th {{ background: #334155; color: #94a3b8; font-size: 0.85rem; text-transform: uppercase; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📚 Telegram Book Bot <span class="badge">LIVE</span></h1>
        <p style="color: #94a3b8;">Real-time system telemetry and content metrics.</p>

        <div class="grid">
            <div class="card"><div class="title">Total Users</div><div class="value">{stats['total_users']:,}</div></div>
            <div class="card"><div class="title">Active Users</div><div class="value">{stats['active_users']:,}</div></div>
            <div class="card"><div class="title">New Today</div><div class="value">{new_today:,}</div></div>
            <div class="card"><div class="title">Indexed Books</div><div class="value">{stats['total_books']:,}</div></div>
            <div class="card"><div class="title">Total Downloads</div><div class="value">{stats['total_downloads']:,}</div></div>
            <div class="card"><div class="title">Total Favorites</div><div class="value">{stats['total_favorites']:,}</div></div>
        </div>

        <h2>🔥 Top Downloaded Books</h2>
        <table>
            <thead><tr><th>#</th><th>Title</th><th>Author</th><th>Downloads</th></tr></thead>
            <tbody>{book_rows or '<tr><td colspan="4">No download records yet.</td></tr>'}</tbody>
        </table>
    </div>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


async def handle_api_stats(request: web.Request) -> web.Response:
    try:
        stats = await db.get_dashboard_stats()
        new_today = await db.get_new_users_today()
        return web.json_response({"status": "ok", "stats": stats, "new_users_today": new_today})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)}, status=500)


async def start_web_dashboard(host: str = "127.0.0.1", port: int = 8085) -> Optional[web.AppRunner]:
    """Start web dashboard server non-blockingly."""
    try:
        app = web.Application()
        app.router.add_get("/", handle_dashboard)
        app.router.add_get("/api/stats", handle_api_stats)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        logger.info(f"Admin Web Dashboard running on http://{host}:{port}")
        return runner
    except Exception as e:
        logger.warning(f"Could not start Web Dashboard on port {port}: {e}")
        return None
