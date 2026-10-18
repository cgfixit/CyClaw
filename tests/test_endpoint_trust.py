"""Destination allowlist for generation clients."""

from __future__ import annotations

import pytest

from utils.endpoint_trust import (
    EndpointTrustError,
    assert_local_destination,
    assert_online_destination,
    hostname_of,
)


def test_hostname_of_strips_url() -> None:
    assert hostname_of("https://api.x.ai/v1") == "api.x.ai"
    assert hostname_of("http://127.0.0.1:11434/v1") == "127.0.0.1"


def test_online_requires_confirm() -> None:
    with pytest.raises(EndpointTrustError, match="user_confirmed_online"):
        assert_online_destination(provider="grok", base_url="https://api.x.ai/v1", confirmed=False)
    assert_online_destination(provider="grok", base_url="https://api.x.ai/v1", confirmed=None)


def test_online_allowlist() -> None:
    assert_online_destination(provider="grok", base_url="https://api.x.ai/v1", confirmed=True)
    assert_online_destination(provider="claude", base_url="https://api.anthropic.com/v1", confirmed=True)
    with pytest.raises(EndpointTrustError):
        assert_online_destination(provider="grok", base_url="https://evil.example/v1", confirmed=True)
    with pytest.raises(EndpointTrustError):
        assert_online_destination(provider="claude", base_url="https://api.x.ai/v1", confirmed=True)


def test_online_pinned_host_requires_https_on_443() -> None:
    # The pinned host alone let http:// send the API key and query in cleartext.
    assert_online_destination(provider="grok", base_url="https://api.x.ai:443/v1", confirmed=True)
    for url in (
        "http://api.x.ai/v1",  # DevSkim: ignore DS137138 - cleartext provider URL rejection; no connection
        "https://api.x.ai:8443/v1",
    ):
        with pytest.raises(EndpointTrustError, match="https on port 443"):
            assert_online_destination(provider="grok", base_url=url, confirmed=True)
    with pytest.raises(EndpointTrustError, match="malformed endpoint URL"):
        assert_online_destination(provider="grok", base_url="https://api.x.ai:99999/v1", confirmed=True)


@pytest.mark.parametrize("url", ["http://[::1", "http://[not-ip]/"])  # DevSkim: ignore DS137138 - malformed endpoint rejection fixtures
def test_malformed_url_is_typed(url):
    with pytest.raises(EndpointTrustError, match="malformed endpoint URL"):
        hostname_of(url)


@pytest.mark.parametrize("hosts", [[], "host.docker.internal", None, ["other.internal"], [None]])
def test_local_destination_rejects_untrusted_or_malformed_allowlist(hosts):
    with pytest.raises(EndpointTrustError):
        assert_local_destination("http://host.docker.internal:11434/v1", hosts)  # DevSkim: ignore DS137138 - untrusted container host rejection; no connection


def test_local_destination_explicit_host_is_exact():
    assert_local_destination("http://host.docker.internal:11434/v1", ["HOST.DOCKER.INTERNAL"])  # DevSkim: ignore DS137138 - exact trusted-host validation; no connection
    with pytest.raises(EndpointTrustError):
        assert_local_destination("http://host.docker.internal.evil:11434", ["host.docker.internal"])  # DevSkim: ignore DS137138 - suffix-spoofed host rejection; no connection
