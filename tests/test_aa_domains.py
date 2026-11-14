"""Tests for Anna's Archive domain failover."""
from __future__ import annotations

from bot.sources.annas_archive import AnnasArchive


def test_candidate_bases_include_configured_and_fallbacks():
    aa = AnnasArchive()
    assert aa.base_url in aa._bases
    assert "https://annas-archive.gl" in aa._bases
    assert "https://annas-archive.pk" in aa._bases
    assert "https://annas-archive.gd" in aa._bases


def test_next_base_cycles_through_candidates():
    aa = AnnasArchive()
    seen = {aa.base_url}
    for _ in range(len(aa._bases) - 1):
        seen.add(aa._next_base())
    assert seen == set(aa._bases)
    assert aa._next_base() == aa.base_url


def test_rebase_url_keeps_path_and_query():
    aa = AnnasArchive()
    old = aa.base_url
    new = aa._next_base()

    rebased = aa._rebase_url(f"{old}/search?q=test&page=2", old, new)

    assert rebased == f"{new}/search?q=test&page=2"


def test_rebase_url_leaves_unrelated_urls_alone():
    aa = AnnasArchive()
    url = "https://example.com/book/1"
    assert aa._rebase_url(url, aa.base_url, "https://annas-archive.pk") == url
