"""Console operator session: trade CYCLAW_API_KEY for an HttpOnly cookie.

The browser console used to keep CYCLAW_API_KEY in a text field and send it
as a Bearer header on every Soul / ops / memory / audit call. A page reload
lost it, and the bearer secret itself lived in page JavaScript, where any
script running in the page could read it. POST /console/session trades the
key once for a signed cookie instead (gate.py). The cookie is HttpOnly, so
page script cannot read it, and it expires; the key never does.

The cookie is stateless: ``v2.<expiry>.<nonce>.<mac>``, where the MAC is an
HMAC-SHA256 under a key derived from CYCLAW_API_KEY. Nothing is stored
server-side. The MAC is bound to the issuing scheme and Host:port, so a cookie
validates only for that gateway audience. A cookie survives a gateway restart and works across uvicorn
workers, and rotating CYCLAW_API_KEY invalidates every cookie at once. An
unset key validates nothing, so the fail-closed default still holds. The
price of statelessness is that a cookie cannot be revoked one at a time
before it expires; security.console_session_ttl_sec bounds that window.

A state-changing request carrying the cookie must also carry its CSRF token
in X-CyClaw-Console-CSRF. That token is derived from the cookie's nonce, so
gate.py can hand it back to a same-origin page after a reload (GET
/console/session) without storing it.

The launchers (macos/invoke-cyclaw.sh, powershell/Invoke-CyClaw.ps1) can also
pass a one-time pairing code through CYCLAW_CONSOLE_PAIRING_CODE and open the
console at ``#pair=<code>``. The fragment never reaches the server or the
network. The page redeems the code once for the same cookie, so the operator
never handles the key at all. A code is single-use and expires
security.console_pairing_ttl_sec after the gateway starts serving: the clock
starts in gate.py's lifespan, not at import, so a slow boot (a large index
load) cannot spend the window before the code is redeemable.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from collections.abc import MutableMapping
from dataclasses import dataclass

COOKIE_NAME = "cyclaw_console"
SECURE_COOKIE_NAME = "__Host-cyclaw_console"
CSRF_HEADER = "x-cyclaw-console-csrf"
PAIRING_ENV = "CYCLAW_CONSOLE_PAIRING_CODE"

_VERSION = "v2"
# A shorter code is refused as too guessable. The launchers mint 32 URL-safe
# characters (about 190 bits).
MIN_PAIRING_CODE_CHARS = 16
# Guards the parser against an oversized cookie; a real token is about 110 chars.
_MAX_TOKEN_CHARS = 256


def _signing_key(api_key: str) -> bytes:
    # Derived, so no cookie MAC is ever computed directly under the API key.
    return hmac.new(api_key.encode("utf-8"), b"cyclaw-console-session-v1", hashlib.sha256).digest()


def _mac(api_key: str, message: str) -> str:
    return hmac.new(_signing_key(api_key), message.encode("utf-8"), hashlib.sha256).hexdigest()


def _csrf_for(api_key: str, nonce: str) -> str:
    return _mac(api_key, f"csrf.{nonce}")


@dataclass(frozen=True)
class ConsoleSession:
    """A minted or verified console cookie and the CSRF token bound to it."""

    token: str
    csrf: str
    expires_at: int


def mint(api_key: str, ttl_sec: int, now: float | None = None, *, audience: str = "") -> ConsoleSession:
    """Mint a cookie valid for ``ttl_sec`` seconds. Raises ValueError without a key."""
    if not api_key:
        raise ValueError("CYCLAW_API_KEY is not set")
    issued = time.time() if now is None else now
    expires_at = int(issued + ttl_sec)
    nonce = secrets.token_urlsafe(18)
    body = f"{_VERSION}.{expires_at}.{nonce}"
    return ConsoleSession(
        token=f"{body}.{_mac(api_key, f'session.{audience}.{body}')}",
        csrf=_csrf_for(api_key, nonce),
        expires_at=expires_at,
    )


def verify(api_key: str, token: str | None, now: float | None = None, *, audience: str = "") -> ConsoleSession | None:
    """Return the session a cookie value carries, or None if it is not valid now."""
    if not api_key or not token or len(token) > _MAX_TOKEN_CHARS:
        return None
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != _VERSION:
        return None
    _, expires_raw, nonce, mac = parts
    body = f"{_VERSION}.{expires_raw}.{nonce}"
    if not hmac.compare_digest(mac.encode("utf-8"), _mac(api_key, f"session.{audience}.{body}").encode("utf-8")):
        return None
    try:
        expires_at = int(expires_raw)
    except ValueError:
        return None
    current = time.time() if now is None else now
    if expires_at <= current:
        return None
    return ConsoleSession(token=token, csrf=_csrf_for(api_key, nonce), expires_at=expires_at)


def csrf_matches(session: ConsoleSession, supplied: str | None) -> bool:
    """Timing-safe check of an X-CyClaw-Console-CSRF header value."""
    if not supplied:
        return False
    return hmac.compare_digest(supplied.encode("utf-8"), session.csrf.encode("utf-8"))


class PairingCode:
    """The launcher's one-time code: redeemable once, until its deadline.

    Only a SHA-256 of the code is kept. With uvicorn workers each process
    reads its own copy of the environment, so the code is redeemable once per
    worker; the shipped launchers run a single process.
    """

    def __init__(self, code: str | None, ttl_sec: int, now: float | None = None) -> None:
        self._lock = threading.Lock()
        usable = isinstance(code, str) and len(code) >= MIN_PAIRING_CODE_CHARS
        self._digest = hashlib.sha256(code.encode("utf-8")).digest() if code is not None and usable else None
        self._ttl_sec = ttl_sec
        # The window opens at start() (gate.py's lifespan, once the gateway
        # serves), or at the first check if nothing called start(). Passing
        # ``now`` opens it at construction, which is what the tests do.
        self._deadline: float | None = None if now is None else now + ttl_sec
        self._used = False

    @classmethod
    def from_env(cls, ttl_sec: int, environ: MutableMapping[str, str] | None = None) -> PairingCode:
        """Take the code out of the environment, so no child process inherits it."""
        env = os.environ if environ is None else environ
        return cls(env.pop(PAIRING_ENV, None), ttl_sec)

    def start(self, now: float | None = None) -> None:
        """Open the redemption window. Idempotent: a later call never extends it."""
        with self._lock:
            self._open_locked(time.time() if now is None else now)

    def _open_locked(self, now: float) -> float:
        if self._deadline is None:
            self._deadline = now + self._ttl_sec
        return self._deadline

    @property
    def available(self) -> bool:
        current = time.time()
        with self._lock:
            return self._digest is not None and not self._used and current < self._open_locked(current)

    def redeem(self, supplied: str | None, now: float | None = None) -> bool:
        if not supplied:
            return False
        digest = hashlib.sha256(supplied.encode("utf-8")).digest()
        current = time.time() if now is None else now
        with self._lock:
            if self._digest is None or self._used or current >= self._open_locked(current):
                return False
            if not hmac.compare_digest(digest, self._digest):
                return False
            self._used = True
            return True
