"""Unit tests for Vercel serverless integration and webhook handling."""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, patch

from api.index import app, handle_get_request, handle_webhook_update


@pytest.mark.asyncio
async def test_vercel_status_endpoint():
    status_code, data = await handle_get_request("/", {}, "test-bot.vercel.app")
    assert status_code == 200
    assert data["status"] == "online"
    assert data["platform"] == "Vercel Serverless"
    assert "endpoints" in data


@pytest.mark.asyncio
async def test_vercel_stats_endpoint():
    status_code, data = await handle_get_request("/api/stats", {}, "test-bot.vercel.app")
    assert status_code == 200
    assert "stats" in data


@pytest.mark.asyncio
async def test_vercel_webhook_invalid_json():
    status_code, data = await handle_webhook_update(b"not json", None)
    assert status_code == 400
    assert "error" in data


@pytest.mark.asyncio
async def test_vercel_webhook_secret_mismatch():
    mock_settings = patch("api.index.settings")
    with mock_settings as m:
        m.webhook_secret = "correct_secret"
        status_code, data = await handle_webhook_update(b'{"update_id": 1}', "wrong_secret")
        assert status_code == 403
        assert "Unauthorized" in data["error"]


@pytest.mark.asyncio
async def test_vercel_asgi_app_get():
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/health",
        "headers": [[b"host", b"test.vercel.app"]],
        "query_string": b"",
    }

    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)

    assert len(messages) == 2
    assert messages[0]["type"] == "http.response.start"
    assert messages[0]["status"] == 200

    body = json.loads(messages[1]["body"].decode("utf-8"))
    assert body["status"] == "online"
