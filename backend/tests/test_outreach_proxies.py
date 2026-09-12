"""Splitting a proxy URL into what a browser can use."""
from __future__ import annotations

import pytest

from services.outreach.proxies import Proxy, ProxyInvalid, parse


def test_credentials_are_separated_from_the_host():
    """Playwright takes them apart, and ignores them when passed whole.

    A URL handed over intact goes out unauthenticated, the proxy answers
    407, and the driver reports a page that would not load — which looks
    like a dead proxy rather than a misread one.
    """
    p = parse("http://user123:s3cret@gate.example.net:7000")
    assert p == Proxy(server="http://gate.example.net:7000",
                      username="user123", password="s3cret")
    assert p.playwright() == {
        "server": "http://gate.example.net:7000",
        "username": "user123",
        "password": "s3cret",
    }


def test_a_proxy_without_credentials_is_fine():
    """IP-authorised proxies are common, and have no user or password."""
    p = parse("http://gate.example.net:7000")
    assert p.playwright() == {"server": "http://gate.example.net:7000"}


def test_percent_encoded_passwords_are_decoded():
    """Proxy passwords are full of characters a URL has to escape."""
    p = parse("http://u:p%40ss%3Aword@gate.example.net:7000")
    assert p.password == "p@ss:word"


def test_nothing_means_no_proxy_not_an_error():
    """It is how an account goes back to the server's own address."""
    assert parse(None) is None
    assert parse("") is None
    assert parse("   ") is None


def test_a_scheme_a_browser_cannot_use_is_refused():
    with pytest.raises(ProxyInvalid):
        parse("ftp://gate.example.net:7000")
    with pytest.raises(ProxyInvalid):
        parse("gate.example.net:7000")


def test_socks5_with_credentials_is_refused_rather_than_half_accepted():
    """Chromium cannot authenticate to a SOCKS5 proxy.

    Accepting it would mean the account silently sends from the server's
    own IP — the exact thing the proxy was bought to prevent.
    """
    with pytest.raises(ProxyInvalid):
        parse("socks5://user:pass@gate.example.net:1080")
    assert parse("socks5://gate.example.net:1080").playwright() == {
        "server": "socks5://gate.example.net:1080"
    }


def test_the_safe_form_keeps_the_password_out():
    p = parse("http://user123:s3cret@gate.example.net:7000")
    assert "s3cret" not in p.safe
    assert p.safe == "http://user123@gate.example.net:7000"


def test_a_url_with_no_host_is_refused():
    with pytest.raises(ProxyInvalid):
        parse("http://")
