"""The harness itself: no keys, no sockets, no HTTP."""

from __future__ import annotations

import os
import socket

import httpx
import pytest

from app.config import load_settings

from .conftest import SECRET_ENV, NetworkBlocked


@pytest.mark.parametrize("key", SECRET_ENV)
def test_keys_absent(key):
    assert not os.environ.get(key)


def test_settings_are_keyless_replay():
    s = load_settings()
    assert s.serpapi_key is None and s.llm_key is None and s.effective_mode == "replay"


def test_dns_blocked():
    with pytest.raises(NetworkBlocked):
        socket.getaddrinfo("serpapi.com", 443)


def test_sync_http_blocked():
    with pytest.raises(NetworkBlocked):
        httpx.get("https://serpapi.com/search.json")


async def test_async_http_blocked():
    async with httpx.AsyncClient() as c:
        with pytest.raises(NetworkBlocked):
            await c.get("https://generativelanguage.googleapis.com/v1beta/openai/")
