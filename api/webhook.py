"""api/webhook.py — Vercel function entrypoint for POST /api/webhook.

Each file in api/ becomes its own route. The shared ASGI app lives in
api/index.py so the path Vercel passes to the function is preserved
(rewriting every request to /api/index.py would make every route look
like /api/index.py).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.index import app, handler  # noqa: E402,F401
