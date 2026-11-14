"""Tests for the Z-Library proof-of-work challenge solver."""
from __future__ import annotations

import hashlib

from bot.utils.zl_challenge import (
    TARGET_FIRST,
    TARGET_SECOND,
    looks_like_challenge,
    solve_challenges,
)


def _reference_solution(token: str) -> int:
    index = int(token[0], 16)
    for i in range(2_000_000):
        digest = hashlib.sha1(f"{token}{i}".encode()).digest()
        if digest[index] == TARGET_FIRST and digest[index + 1] == TARGET_SECOND:
            return i
    raise AssertionError("reference solver failed")


def _challenge_page(token: str) -> str:
    # Mirrors the shape of the real page: a three-element array containing the
    # token, the cookie name, and the digest method.
    return (
        "<!DOCTYPE html><html><head><title>Checking your browser ...</title></head>"
        f"<body><script>const a0=['{token}','c_token=','array'];"
        "let c=a0[0];let i=0;let n1=parseInt('0x'+c[0x0]);</script></body></html>"
    )


def test_looks_like_challenge():
    assert looks_like_challenge('<title>Checking your browser ...</title>')
    assert looks_like_challenge("document.cookie='c_token='")
    assert not looks_like_challenge(b"%PDF-1.7 binary")
    assert not looks_like_challenge(b"PK\x03\x04epub")


def test_solver_finds_the_same_preimage_as_the_reference():
    token = "CB0293F3FBBC8F0C1054B04C159BB380D16663DB"
    expected = _reference_solution(token)

    solutions = solve_challenges(_challenge_page(token))

    assert len(solutions) == 1
    assert solutions[0]["c_token"] == f"{token}{expected}"
    assert float(solutions[0]["c_time"]) >= 0


def test_solver_uses_the_token_derived_index():
    token = "3F0293F3FBBC8F0C1054B04C159BB380D16663DB"
    expected = _reference_solution(token)
    solutions = solve_challenges(_challenge_page(token))

    assert solutions[0]["c_token"] == f"{token}{expected}"
    assert solutions[0]["c_token"].startswith(token)


def test_solver_ignores_pages_without_a_token():
    assert solve_challenges("<title>Checking your browser ...</title>") == []
    assert solve_challenges(b"") == []
