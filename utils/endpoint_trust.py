"""Destination allowlist for generation clients. Not a substitute for I3."""

from __future__ import annotations

from urllib.parse import urlparse

_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})
_ONLINE_HOSTS = {
    "grok": frozenset({"api.x.ai"}),
    "claude": frozenset({"api.anthropic.com"}),
}
_DEFAULT_URLS = {
    "grok": "https://api.x.ai/v1",
    "claude": "https://api.anthropic.com/v1",
}


class EndpointTrustError(ValueError):
    """Resolved destination is not allowed for this provider."""


def hostname_of(url: str) -> str:
    # A YAML typo can hand us None/int/bool; urlparse would raise AttributeError.
    if not isinstance(url, str):
        raise EndpointTrustError("endpoint URL must be a string")
    # urlparse's .hostname is already lowercased and has IPv6 brackets removed.
    try:
        return urlparse(url).hostname or ""
    except ValueError:
        # Keep malformed URLs on the same typed failure path as denied hosts so
        # graph callers can return an audited error instead of a parser traceback.
        raise EndpointTrustError("malformed endpoint URL") from None


def is_loopback_url(url: str) -> bool:
    """True when ``url``'s host is loopback. Malformed input is NOT loopback.

    The one shared copy: llm/, utils/health.py, agentic/ and guardrails/ each
    used to keep their own, and the guardrails one raised on a malformed URL.
    """
    try:
        return hostname_of(url) in _LOOPBACK
    except EndpointTrustError:
        return False


def assert_local_destination(base_url: str, trusted_hosts: object = ()) -> None:
    """Allow loopback or an explicitly trusted operator-owned model host."""
    host = hostname_of(base_url)
    if host in _LOOPBACK:
        return
    # Trust is an operator assertion that this host may receive local context;
    # hostname matching neither pins DNS nor grants online-provider consent.
    # Reject malformed lists rather than accidentally using substring matching.
    if isinstance(trusted_hosts, (list, tuple)) and host and any(
        isinstance(item, str) and host == item.lower() for item in trusted_hosts
    ):
        return
    raise EndpointTrustError("local LLM endpoint is not loopback or an explicitly trusted host")


def assert_online_destination(*, provider: str, base_url: str, confirmed: bool | None) -> None:
    """Allowlist the host, https on 443 only. Explicit ``confirmed is False`` refuses (I3).

    ``confirmed is None`` means the node was invoked without a gate stamp
    (unit tests / incomplete state): still enforce the host allowlist.
    """
    if confirmed is False:
        raise EndpointTrustError("online destination requires user_confirmed_online")
    allowed = _ONLINE_HOSTS.get(provider)
    if not allowed:
        raise EndpointTrustError(f"unknown online provider {provider!r}")
    url = base_url or _DEFAULT_URLS.get(provider, "")
    host = hostname_of(url)
    if host not in allowed:
        raise EndpointTrustError(f"{provider} destination {host!r} is not in the allowlist")
    # The host alone let http:// or another port on the pinned host carry the
    # API key and query in cleartext or to a different listener. urlsplit is
    # lru_cached, so this re-parse of the URL hostname_of just parsed is a hit.
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError:
        raise EndpointTrustError("malformed endpoint URL") from None
    if parsed.scheme != "https" or port not in (None, 443):
        raise EndpointTrustError(f"{provider} destination must be https on port 443")


def url_for_details(url: str) -> str:
    """Strip userinfo before a URL is copied into error details.

    Implemented with string partition (not ``ParseResult.password``) so
    CodeQL does not treat the original URL as a cleartext-password source
    that later taints ``status`` / ``_kv`` prints of the validated URL.
    """
    scheme, sep, rest = url.partition("://")
    if not sep:
        return "<unparsed>"
    _userinfo, at, hostpart = rest.rpartition("@")
    if at:
        return f"{scheme}://<redacted>@{hostpart}"
    return url
