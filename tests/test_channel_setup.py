"""Tests for the storage-channel setup helper."""
from __future__ import annotations

from types import SimpleNamespace

from bot.handlers import channel


def test_channel_id_text_shows_numeric_id_and_env_var_name():
    text = channel.build_channel_id_text(-1001234567890, "Books Storage")
    assert "-1001234567890" in text
    assert "Books Storage" in text
    assert "STORAGE_CHANNEL_ID" in text


def test_trust_check_allows_bootstrap_without_admin_ids(monkeypatch):
    monkeypatch.setattr(channel, "settings", SimpleNamespace(admin_ids=[]))
    assert channel._is_trusted(123)


def test_trust_check_restricts_when_admin_ids_are_set(monkeypatch):
    monkeypatch.setattr(channel, "settings", SimpleNamespace(admin_ids=[42]))
    assert channel._is_trusted(42)
    assert not channel._is_trusted(99)
