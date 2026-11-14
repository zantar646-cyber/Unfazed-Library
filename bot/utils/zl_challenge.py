"""Solve Z-Library's browser proof-of-work challenge.

Z-Library (and its mirrors) answer ``GET /dl/<token>`` with ``HTTP 503`` and a
small HTML page that asks the browser to compute a SHA-1 preimage before
setting two cookies and reloading:

    token = "<40 hex chars>"
    index = int(token[0], 16)
    find the smallest i where sha1(token + str(i))[index] == 0xB0 and
                              sha1(token + str(i))[index + 1] == 0x0B
    cookie c_token = token + str(i)
    cookie c_time  = seconds spent solving

A real browser solves this in milliseconds; the page only exists to filter out
naive HTTP clients. Serverless deployments have no browser, so we reproduce the
same calculation in pure Python and retry the request with the cookies set.

The work is deliberately stateless: this module never persists anything and
contains no credentials.
"""
from __future__ import annotations

import hashlib
import re
import time
from typing import Dict, List, Union

# Quoted 40-character hex token embedded in the challenge script.
TOKEN_RE = re.compile(r"['\"]([0-9A-Fa-f]{40})['\"]")

# Markers that identify the challenge without matching a real file response.
CHALLENGE_MARKERS = ("checking your browser", "c_token=", "checking your browser ...")

# The expected preimage is found after ~65k attempts on average. 2M leaves a
# very wide safety margin while keeping the worst case a few seconds.
MAX_ITERATIONS = 2_000_000

# SHA-1 digest bytes 12/13 are what the bundled script usually checks, but the
# index is derived from the token, so both are honoured below.
TARGET_FIRST = 0xB0
TARGET_SECOND = 0x0B


def looks_like_challenge(body: Union[bytes, str]) -> bool:
    """Return True when *body* looks like the Z-Library browser challenge page."""
    text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
    lowered = text[:4000].lower()
    return "c_token=" in lowered or "checking your browser" in lowered


def _solve_token(token: str) -> Dict[str, str] | None:
    token = token.upper()
    index = int(token[0], 16)
    if index + 1 >= 20:  # cannot be a SHA-1 digest offset
        return None

    started = time.monotonic()
    for i in range(MAX_ITERATIONS):
        digest = hashlib.sha1(f"{token}{i}".encode("ascii")).digest()
        if digest[index] == TARGET_FIRST and digest[index + 1] == TARGET_SECOND:
            return {
                "c_token": f"{token}{i}",
                "c_time": f"{time.monotonic() - started:.3f}",
            }
    return None


def solve_challenges(body: Union[bytes, str]) -> List[Dict[str, str]]:
    """Return candidate cookie sets for every solvable token in *body*.

    Usually exactly one solution is returned. Returning a list keeps the caller
    tolerant of pages that embed several candidate tokens.
    """
    text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
    if not looks_like_challenge(text):
        return []

    solutions: List[Dict[str, str]] = []
    seen = set()
    for token in TOKEN_RE.findall(text)[:3]:
        token = token.upper()
        if token in seen:
            continue
        seen.add(token)
        solution = _solve_token(token)
        if solution:
            solutions.append(solution)
    return solutions
