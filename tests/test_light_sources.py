from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from light.sources import ZLibrary


def _book(id: str = "1", title: str = "Test Book") -> dict:
    return {"id": id, "title": title, "author": "A", "language": "en"}


def test_mirrors_dedupe_and_include_primary():
    zl = ZLibrary(base_url="https://z-library.sk", mirrors=["https://1lib.fr", "https://1lib.fr"])
    assert zl.mirrors == ["https://z-library.sk", "https://1lib.fr"]


def test_mirrors_default_to_builtin_list():
    zl = ZLibrary(base_url="https://1lib.fr")
    assert zl.mirrors[0] == "https://1lib.fr"
    assert "https://z-library.sk" in zl.mirrors
    assert len(zl.mirrors) == len(set(zl.mirrors))


@pytest.mark.asyncio
async def test_search_fails_over_to_mirror_and_rotates():
    zl = ZLibrary(base_url="https://z-library.sk", mirrors=["https://1lib.fr"])
    book = zl._parse_book(_book(), base_url="https://1lib.fr")
    calls = []

    async def fake_try_domain(domain, *args, **kwargs):
        calls.append(domain)
        if domain == "https://z-library.sk":
            raise RuntimeError("HTTP 503 Service Unavailable")
        return [book], 1

    zl._try_domain = fake_try_domain
    zl.session = object()

    books, total = await zl.search("test")
    assert calls == ["https://z-library.sk", "https://1lib.fr"]
    assert books == [book]
    assert total == 1
    assert zl.base_url == "https://1lib.fr"


@pytest.mark.asyncio
async def test_search_returns_empty_when_all_mirrors_fail():
    zl = ZLibrary(base_url="https://z-library.sk", mirrors=["https://1lib.fr"])

    async def fake_try_domain(domain, *args, **kwargs):
        raise RuntimeError(f"HTTP 503 for {domain}")

    zl._try_domain = fake_try_domain
    zl.session = object()

    books, total = await zl.search("test")
    assert books == []
    assert total == 0
    assert zl.base_url == "https://z-library.sk"


@pytest.mark.asyncio
async def test_search_uses_cached_result_before_touching_mirrors():
    zl = ZLibrary(base_url="https://z-library.sk", mirrors=["https://1lib.fr"])
    book = zl._parse_book(_book(), base_url="https://z-library.sk")
    zl._cache.set("zl:test:title:1:10:any", ([book], 1))

    with patch.object(zl, "_try_domain", new_callable=AsyncMock) as mock:
        books, total = await zl.search("test")
        mock.assert_not_awaited()

    assert books == [book]
    assert total == 1


def test_parse_book_uses_domain_for_relative_download_url():
    zl = ZLibrary(base_url="https://z-library.sk")
    book = zl._parse_book({"id": "7", "title": "T", "dl": "/dl/abc.epub"}, base_url="https://1lib.fr")
    assert book.download_url == "https://1lib.fr/dl/abc.epub"
