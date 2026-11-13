"""api/sources_check.py — Vercel function entrypoint for GET /api/sources_check."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.index import app, handler  # noqa: E402,F401
