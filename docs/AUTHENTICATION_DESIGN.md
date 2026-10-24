---
title: "CyClaw Authentication — Design"
date: 2026-08-08
status: landed
tags: [security, authentication, tls, threat-model, lan]
related:
  - docs/THREAT_MODEL.md
  - .github/SECURITY.md
  - config.yaml
---

# CyClaw Authentication — Design

**Status: all six stages landed.** Stage 1 (`utils/authn.py`, PR #829),
Stage 2 (sessions, login/logout, per-device tokens, `gate_auth.py`,
PR #830), Stage 3 (credential on `/query` + console login when
`auth.enabled` is true, PR #940), Stage 4 (TLS wired into `uvicorn.run` via
`gate._serve`, `cyclaw-gen-cert`, PR #940), Stage 5 (re-keying the #825
bind guard, landed as part of #825 itself), and Stage 6 (roles
`admin`/`operator`/`audit`, HTTP user admin, web Users panel + audit tab,
PR #940) have landed. `auth.enabled` and `api.tls.enabled` both still
ship `false`, so no existing install's behavior changed. Enabling TLS
without real cert files fails closed at boot instead of marking cookies
Secure on plaintext.

This document exists because the operator wrote the requirement down first, in
`docs/zIdeas/note.txt` (since removed from the tree):

> "Dont forget that curl requests or powershell api commands can still query
> cyclaw if on same lan - need to add authentication before truly considering
> this secure"

and then set the bar for answering it: **true authentication, or address it
later — no shortcuts.** The intent is to eventually let other machines on the
LAN reach CyClaw. This design is written to that bar.

---

## 1. Scope

**In scope.** Per-user authentication for the CyClaw gateway
(`gate.py`, `127.0.0.1:8787`) sufficient to allow non-loopback binding safely:
individual accounts, password verification, sessions for browsers, revocable
tokens for programmatic clients, lockout, audit attribution, and TLS so a
credential is not readable on the wire.

**Out of scope, deliberately.**

- **Multi-tenancy.** Accounts give *identity and revocation*, not isolation.
  Every authenticated user still reaches the same corpus, the same soul, and the
  same model. `docs/THREAT_MODEL.md` §1 stays single-tenant, and this document
  does not change that.
- **MCP server.** Separate app, stdio, `sampling: None`. Untouched.
- **Authorization / roles.** **Amended (Stage 6).** Accounts now carry a
  `role` of `admin`, `operator`, or `audit`. This is authorization on the
  same single-tenant corpus, not multi-tenancy. See §12.
- **Federation, SSO, OAuth, MFA.** Not now. §11 notes where MFA would attach if
  it is ever wanted.

---

## 2. Starting point and current state

At proposal time (2026-08-08) `/query`, `/`, `/health`, and `/static/*` took
no credential; `/soul/*`, `/audit/summary`, and `/ops/*` took one shared
bearer secret (`require_api_key`, constant-time compare, failing closed when
`CYCLAW_API_KEY` was unset, rate-limited *before* auth — pinned by
`TestFailedAuthDoesNotBypassRateLimit`); both real clients (the console and
Telegram) already sent `Authorization: Bearer`; and no password, session, or
TLS infrastructure existed. Two consequences drove the design: **the transport
was already built**, so requiring a credential on `/query` meant turning on a
check the clients already satisfied, and **what was missing was identity, not
authentication** — a shared secret cannot say *which* machine asked or revoke
one device without rotating every other, which is the gap that matters on a
LAN.

**Current state (Stages 1–6 landed, PRs #829/#830/#940).** Password, session,
and TLS infrastructure exist: `utils/authn.py`, the account/session/token
store, and `gate._serve` passing `ssl_certfile`/`ssl_keyfile` to
`uvicorn.run` when `api.tls.enabled` is the literal boolean `true` (missing or
unreadable files fail closed at boot). Every `/auth/*` route is registered
regardless of `auth.enabled` and answers 503 while it is false (the `/ops/*`
convention); `/auth/login` itself carries no credential, by necessity, behind
the rate limit and the same-origin check. Stage 3 attaches
`require_session_or_token` to `POST /query` when `auth.enabled` is the literal
`true` (session cookie or named device token; no CSRF on the query path); the
shipped default leaves `/query` open. `terminal.js` no longer sends the typed
API key on `/query` — with auth on, `/query` authenticates with the
`cyclaw_session` cookie and the key field serves `/soul/*` and `/ops/*` only;
Telegram still sends a bearer token, which must now be a named device token,
not the shared `CYCLAW_API_KEY`.

**The orthogonal escape hatch (2026-08-15).** `security.api_key_optional`
(ships `false`) bypasses `require_api_key` on every route it gates
(`/soul/*`, `/ops/*`, `/memory/*`, `/audit/summary`) and touches nothing in
this document — not `auth.enabled`, sessions, device tokens, or `/auth/*`; the
two can be on at once without affecting each other. The bypass is granted only
to a request that is simultaneously from a **loopback socket peer**, carries
**no reverse-proxy forwarding header** (`X-Forwarded-For`/`-Host`/`-Proto`,
`X-Real-IP`, `Forwarded` — a proxy on this host makes every remote caller a
loopback peer), and is **not cross-site** (the operator's own browser is a
loopback peer too, and a CORS-simple POST executes before CORS withholds the
response); `gate.py`'s `_api_key_bypass_allowed` treats each as necessary.
`config-guard`'s C13 warns when it is combined with a non-loopback `api.host`
(C13 ignores `security.allowed_hosts`, which filters `Host` headers and opens
no socket).

The one place the two systems interact, and must not compose: §7's bind rule
is satisfied by `auth.enabled` + `api.tls.enabled` + a real `/query`
credential, all properties of the SESSION system that say nothing about the
API-key routes `api_key_optional` opens. Composed, they would admit a LAN bind
on the strength of a session while `/soul/*` and the `/ops/*` shims sat
unauthenticated, so `_require_loopback_bind` refuses that route while
`api_key_optional` is true; `CYCLAW_ALLOW_NON_LOOPBACK_BIND` ("my own auth is
in front") still outranks it. That bind-time refusal is defence in depth; the
primary control is the per-request three-condition check, which holds however
the process was launched — including the container's
`uvicorn gate:app --host 0.0.0.0`, which reaches no bind guard at all.

---

## 3. What changes in the threat model

`docs/THREAT_MODEL.md` §1 currently assumes network exposure is *exclusively*
`127.0.0.1:8787`. Allowing a LAN bind changes the adversary from "a local
process on the operator's own machine" to "anything that can route to the port,
plus anything that can observe the segment." Concretely, three new adversaries:

1. **Another device on the LAN** — an IoT device, a guest phone, a compromised
   laptop. It can reach the port and attempt credentials.
2. **A passive observer of the segment** — anyone who can sniff wireless or a
   mirrored port. This is the adversary TLS exists for, and the reason a login
   form over plain HTTP would be theatre.
3. **A device that was trusted and no longer should be** — a lost laptop, a
   departed housemate. This is the adversary *revocation* exists for, and the
   one a shared secret cannot answer.

Everything else in the threat model is unchanged. Host root is still trusted.
The agentic layer is still out-of-band and default-off. This design does not
make CyClaw safe to expose to the internet, and says so in §11.

---

## 4. Scheme

### 4.1 Password hashing — `hashlib.scrypt`, not argon2

**stdlib, no new runtime dependency.** `hashlib.scrypt` (RFC 7914) is
memory-hard and ships with CPython against OpenSSL 1.1+. Current parameters:
n=2¹⁷, r=8, p=1 — the OWASP Password Storage Cheat Sheet's scrypt floor when
Argon2id isn't used (checked 2026-08-19), costing ~128 MiB and, measured on
this environment's CPU (Intel Xeon @2.80GHz, 4 cores), ~0.40 s per
verification (n=2¹⁴'s prior floor measured ~0.04 s here for comparison — both
figures are hardware-dependent, re-measure on the actual deployment target
before re-tuning). Slower than ideal for interactive login, but expensive
enough to make offline cracking costly, which is what this parameter buys.

This was chosen over argon2id specifically because `argon2-cffi` would be a new
runtime dependency, which CLAUDE.md §7 classifies High-tier and which would need
exact pins in both `pyproject.toml` and `constraints.txt` plus a `dep-guard`
pass. Stdlib-first is this repo's stated convention. argon2id is the stronger
primitive in the abstract; scrypt at these parameters is not the weak link in
this system, and the dependency cost is real.

Stored per user: `scrypt$n$r$p$<salt_b64>$<hash_b64>`. The parameters live in the
record so they can be raised later without invalidating existing accounts — a
verification that succeeds against outdated parameters transparently re-hashes.

### 4.2 Account store

Follows the same pattern as `utils/personality_db.py`: **SQLite by default**,
Postgres via a passwordless `auth.database_url` in `config.yaml` or the
`CYCLAW_AUTH_DB_URL` OS-keystore environment value. Inline URL passwords are
rejected before connecting. The store uses `CREATE TABLE IF NOT EXISTS`, umask-safe file
creation. No new storage technology. One deliberate deviation from an exact
mirror: the env var is `CYCLAW_AUTH_DB_URL`, not the shared `CYCLAW_DB_URL`
personality uses — auth data (password hashes, session ids, device-token
hashes) is higher-sensitivity, and a shared env var would silently comingle
the two into whatever database an operator pointed `CYCLAW_DB_URL` at for a
different subsystem.

```
users(username TEXT PRIMARY KEY, password_hash TEXT NOT NULL,
      created_ts REAL, disabled INTEGER DEFAULT 0,
      last_login_ts REAL, failed_count INTEGER DEFAULT 0,
      locked_until_ts REAL, role TEXT NOT NULL DEFAULT 'operator')
sessions(session_id TEXT PRIMARY KEY, username TEXT NOT NULL,
         created_ts REAL, expires_ts REAL, revoked INTEGER DEFAULT 0,
         label TEXT)
device_tokens(token_hash TEXT PRIMARY KEY, username TEXT NOT NULL,
              label TEXT NOT NULL, created_ts REAL, last_used_ts REAL,
              revoked INTEGER DEFAULT 0)
```

(`role` arrived with Stage 6; `ensure_users_role_column` adds the missing column
to pre-Stage-6 databases. Only when adding that column does `AuthManager` promote
`BOOTSTRAP_USERNAME` to `admin`; every other existing row defaults to `operator`.
Later opens preserve assigned roles, including bootstrap-account demotions.
The `sessions` block above is the
proposal-time sketch — the shipped table also carries `csrf_token` and
`last_seen_ts`, and no `label`; see `utils/authn_store.py` for the DDL of
record.)

Sessions are **server-side records**, not signed self-contained cookies. That is
the deliberate choice: a server-side row can be revoked instantly, which is the
whole point of per-user accounts. A stateless signed token cannot be withdrawn
before it expires without a revocation list, which is a session table wearing a
disguise.

### 4.3 Two credential paths, one identity

| Client | Credential | Why |
|---|---|---|
| Browser (`terminal.html`) | Session cookie (`HttpOnly`, `Secure`, `SameSite=Strict`) + CSRF token | A cookie is not readable by injected script; CSRF covers the state-changing routes |
| Programmatic (Telegram, smoke tests, `curl`, PowerShell) | `Authorization: Bearer <token>` | Already implemented on both real clients; no cookie jar needed |

Both resolve to a **username**, so the audit log can attribute every query. The
bearer path issues *named, per-device, individually revocable* tokens stored as
hashes — not the current single shared key. The existing `CYCLAW_API_KEY`
continues to govern `/soul/*` and `/ops/*` unchanged, so this is additive.

CSRF uses `secrets.token_urlsafe(32)` + `hmac.compare_digest`: the gate's
token is **per session**, minted at login and returned in the `/auth/login` response body,
then echoed back by the browser in the `X-CyClaw-CSRF` header on
state-changing routes.

At rest, `sessions.session_id` and `sessions.csrf_token` store
`utils.authn.hash_token()` of the values above, never the plaintext — the
same treatment `device_tokens.token_hash` already gets, for the same reason:
a copied or backed-up DB file must not hand out directly usable, live
credentials. `AuthManager.validate_session`/`logout` hash the caller's raw
cookie value before every lookup; `gate_auth.py` hashes the caller's raw
`X-CyClaw-CSRF` header before comparing it to the stored hash. The plaintext
values exist only in the login response body and the session cookie, never
in the database.

### 4.4 Lockout

Unknown, disabled, locked, stale, and incorrect credentials return the same
401 response and perform password-hash work. Password verification runs outside
the manager lock in a dedicated pool, limited by `auth.max_concurrent_password_ops`
(default 2). A full pool returns 503 without queuing another hash. Short SQL
transactions use the latest counter and a credential revision, so password
rotation or disable/enable cannot revive a stale verification.

Per-account exponential backoff on consecutive failures, recorded in
`failed_count`/`locked_until_ts`, cleared on success. This is *in addition to*
the existing per-IP rate limiter, which already runs before auth — the limiter
throttles a single source, lockout stops a distributed guess against one
account. Lockout is per-account, not per-IP, precisely because the LAN case
means many source addresses.

### 4.5 Ships disabled

`auth.enabled: false` by default, like `agentic`, `telegram`, and `fsconnect`.
NeMo Guardrails ships enabled independently of auth
([current reference](NeMo/README.md)). Nothing changes for an
existing loopback install until the operator turns it on. When enabled,
`/query` requires a credential **including on loopback** — a bypass for
`127.0.0.1` would be exactly the shortcut this design was asked to avoid, and
local processes are inside the stated adversary set. The smoke tests and
`CyClaw-Sandbox` get a token like any other programmatic client.

### 4.6 First password from the consoles (loopback only)

Turning `auth.enabled` on still seeds `admin` with an unusable `pending$`
hash (CodeQL #1057: no one-time password on stdout). `cyclaw-user passwd
admin` remains the local CLI path.

When the operator opens the terminal (`:8787`) with
auth on and that pending hash still in place, the UI shows a **Set admin
password** panel instead of login. `GET /auth/setup-status` reports `{enabled, needs_password, username}`
with no hashes. `POST /auth/bootstrap-password` accepts the new password
**only from a loopback peer** (the literal set `127.0.0.1` / `::1` / `localhost`, plus anything `ipaddress.ip_address(...).is_loopback` accepts) with no reverse-proxy
forwarding headers, then mints a session. A non-loopback or proxied caller
gets 403. Once a real hash is stored the POST returns
409. The bind guard also refuses a LAN bind while `needs_password_setup()`
is true, so enabling auth+TLS does not open that POST to the LAN.

---

## 5. TLS

Without it, the session cookie and bearer token cross the LAN in plaintext and
adversary (2) in §3 simply reads them. TLS is therefore part of the feature, not
an enhancement.

- `api.tls.enabled`, `api.tls.certfile`, `api.tls.keyfile` in `config.yaml`;
  passed to `uvicorn.run(ssl_certfile=..., ssl_keyfile=...)`.
- A `cyclaw-gen-cert` helper producing a self-signed cert with the machine's
  LAN IP and hostname in `subjectAltName` (browsers reject CN-only certs). The
  operator installs it as trusted on each client device once.
- The session cookie is named `__Host-cyclaw_session` and issued `Secure` when TLS is on.
  Cookies have no persistent Max-Age; the server enforces a one-hour idle default.
  Browsers can retain session cookies when restoring a session. **`Secure` is not sent
  over plain HTTP**, so enabling auth without TLS on a non-loopback bind must be
  refused rather than silently downgrading the cookie — see §7.
- `security.allowed_origins` gains the `https://` forms; the console's CSP
  `connect-src` follows.

Self-signed is the right default for a home LAN: no external CA, no renewal
daemon, no internet dependency, consistent with CyClaw's offline-first posture.

---

## 6. Migration for existing clients

| Client | Change |
|---|---|
| `static/terminal.js` | Login form; session cookie replaces the typed key for `/query`. The existing API-key field stays for `/soul/*` and `/ops/*`. |
| `telegram/client.py` | None to the code — it already sends a bearer token. The operator issues it a named token instead of the shared key. |
| `tests/ci_rag_smoke.py`, `CyClaw-Sandbox` | Only affected when `auth.enabled` is true. CI leaves it false; a token is provided where a job needs it on. |
| MCP server | None. Separate app, no `/query`. |
| `utils/health.py` / `/health` | Stays unauthenticated — it exposes no corpus content and the container healthcheck depends on it. Revisit if it ever reports more. |

---

## 7. Interaction with the `main()` bind guard (#825)

PR #825 refuses a non-loopback `api.host` unless
`CYCLAW_ALLOW_NON_LOOPBACK_BIND=1`. That guard was originally keyed on the
wrong condition: it refused **because there is no auth**. #825's 2026-08-08
update re-keyed it to this design (Stage 5, §8), and the rule as actually
implemented in `gate.py`'s `_require_loopback_bind`/`_auth_and_tls_enabled` is

> a non-loopback bind is allowed when authentication is enabled **and** TLS is
> enabled **and** `/query` demonstrably enforces a credential; otherwise
> refuse.

The third condition is load-bearing: the two flags state *intent*, and
`gate.py`'s `_request_path_enforcement_active()` probes the live FastAPI app
for the `/query` credential dependency rather than trusting them. Stage 3
attaches that dependency when `auth.enabled` is the literal boolean `true`, so
the path past loopback opens by itself once both flags are on, and the shipped
default (auth off) leaves the probe false. The guard therefore permits the
operator's goal (LAN + TLS + auth) and refuses LAN + no auth and LAN + auth
claimed but not enforced. Its TLS half is real too: `gate._serve` passes the
cert files to `uvicorn.run`, and missing or unreadable files refuse to boot
rather than fall back to plaintext. Residual gap: the Docker `CMD` and a
hand-run `uvicorn gate:app` bypass `_serve`, so the proof covers the
documented entry points (`python gate.py`, `cyclaw-server`) only — see
`docs/THREAT_MODEL.md`'s ninth amendment §5. `CYCLAW_ALLOW_NON_LOOPBACK_BIND`
remains only as the escape hatch for an operator fronting CyClaw with their own
reverse proxy.

---

## 8. Staged delivery

Each stage is independently reviewable and leaves the tree working.

| Stage | Content | Risk |
|---|---|---|
| **1** — landed, PR #829 | This document + `utils/authn.py` (scrypt hash/verify, lockout arithmetic) + tests. Pure functions only — no database, no HTTP, no CLI. **No request path touched.** | None at merge time; Stage 2 (below) is now the caller |
| **2** — landed, PR #830 | Account store (`utils/authn_store.py`), `AuthManager` (`utils/authn_manager.py`), `cyclaw-user` CLI (`add`/`list`/`disable`/`enable`/`passwd`/`token`), session store, `/auth/login`, `/auth/logout`, `/auth/whoami`, cookie issuance, CSRF, per-device bearer tokens | None while `auth.enabled: false` (ships false, unchanged) |
| **3** — landed, PR #940 | Enforce on `/query` and the console; audit log gains a `username` field | Behaviour change, gated by `auth.enabled` |
| **4** — landed, PR #940 | TLS config, `cyclaw-gen-cert`, origin/CSP updates, docs | Config surface only |
| **5** — landed, PR #825 | Re-key the #825 bind guard per §7; update `THREAT_MODEL.md` §1 and add an amendment | Docs + one condition (implemented as three — see §7) |
| **6** — landed, PR #940 | Roles (`admin`/`operator`/`audit`), HTTP user admin, shared web Users panel, audit tab | Gated by `auth.enabled` |

---

## 9. What could go wrong

- **Lockout as a denial-of-service.** An attacker who knows a username can lock
  it by failing repeatedly. Mitigated by exponential backoff with a ceiling
  rather than a permanent lock, and by the operator always retaining a local
  CLI path (`cyclaw-user`) that does not go through HTTP.
- **Self-signed certificate fatigue.** Browsers warn loudly, and operators learn
  to click through warnings — which trains exactly the wrong reflex. The
  `subjectAltName` + install-once-per-device flow exists to avoid a permanent
  warning state; if it is not followed, TLS degrades toward theatre.
- **Session fixation / theft.** Session id is `secrets.token_urlsafe(32)`,
  regenerated on login, `HttpOnly`, `SameSite=Strict`, and server-side
  revocable. XSS remains the realistic theft vector, which is why the strict CSP
  work in #818/#822 is load-bearing for this feature rather than incidental.
- **This does not make CyClaw internet-safe.** It makes a *trusted LAN* defensible.
  Internet exposure would additionally require rethinking rate limits, the
  unauthenticated `/health`, DoS budgets, and the chromadb CVE risk acceptance
  that is currently justified by local-only use.

---

## 10. Open decisions for the operator

1. **Username set.** Single account (`operator`), or one per person? One per
   device is handled by named bearer tokens regardless.
2. **Session lifetime.** **Resolved (2026-08-08):** 1 h (3600 s) idle / 7 d absolute,
   both configurable (`auth.session.idle_timeout_sec` /
   `absolute_timeout_sec` in `config.yaml`, 3600 / 604800 shipped). A session
   dies from either limit, whichever is reached first.
3. **Should `/health` stay open?** **Resolved: yes** (§6). It reports status,
   mode, and timeouts — no corpus content — and stays unauthenticated even
   with `auth.enabled: true`.
4. **Bootstrap.** **Resolved (2026-08-08, amended 2026-08-09):** first enable
   with an empty users table creates `admin` seeded with the hash of a random
   secret discarded inside the same call — never returned, printed, logged, or
   stored — so the account exists but cannot be logged into until
   `cyclaw-user passwd admin` (local `getpass`) or the loopback-only console
   panel in §4.6 sets a real password. The first iteration printed a one-time
   password to the server console; CodeQL #1057 flagged it, and rightly: a
   service's stdout persists in journald, Docker's log driver, and any log
   shipper, so "printed once" never was. No default credential ever exists.

---

## 11. Where MFA would attach, if ever wanted

A TOTP secret column on `users` and a second step between password verification
and session issuance. Deliberately not built now — it is the wrong thing to add
before per-user accounts and TLS exist, and adding it later requires no
redesign.

---

## 12. Roles (Stage 6)

Three canonical lowercase roles on `users.role`. Bootstrap `admin` is
`admin`. Existing rows without a column become `operator` except
`BOOTSTRAP_USERNAME`.

| Role | `/query` | Users panel | Audit tab | delete / set-role |
|---|---|---|---|---|
| `admin` | yes | yes | yes | yes (not the last enabled admin) |
| `operator` | yes | yes (no delete / set-role / touch admins) | no | no |
| `audit` | **denied** | no | yes | no |

HTTP admin lives on `gate_auth.py` (`/auth/users*`,
`/auth/audit/summary`, plus the self-service `POST /auth/password`, which any
authenticated role can call for its own account with `current_password` and the new
`password`, **over a session cookie + CSRF** — the
bearer path requires an admin token (`_require_write_actor`)). A successful change
revokes all existing sessions. Device tokens retain their separate revocation controls. Admin password reset is a separate
route and retains its role checks; `/auth/whoami` returns
`username` + `role`, and — on the session-cookie path only, never for a device token —
a freshly rotated `csrf_token`; the response is sent `Cache-Control: no-store`. The
rotate is load-bearing: without it a reload leaves logout and Users writes 403.
Telegram still uses a named
device token (`cyclaw-user token create <user> telegram`).

## TLS logout and public diagnostics

Both console and account logout expire their cookies with the same `Secure`,
`HttpOnly`, `SameSite=Strict`, and `Path=/` attributes used when creating them.
Under TLS this is required for browsers to accept deletion of `__Host-` cookies.
Cookies cannot be isolated by port; use a dedicated trusted hostname and TLS.
Public errors suppress whole local paths, including paths containing spaces, newlines
and Windows UNC paths, even when whitespace follows the path root. Redaction
consumes trailing diagnostic prose because filename boundaries in error text
are ambiguous; known rate-limit prose uses “per” instead of a slash. Degraded
model answers use token-level filtering so prose survives; they are content,
not operational diagnostics, and this is not a whole-filename privacy guarantee.
Citations retain distinct corpus-relative subpaths on Windows and POSIX; files outside the corpus expose only a basename.

`cyclaw-gen-cert` protects its empty temporary outputs before writing key bytes:
0600 on POSIX and a protected owner-rights-only DACL on Windows. Failure to set
permissions aborts generation, including replacement backups. A same-directory
rename preserves those permissions. This does not repair existing keys; regenerate
or explicitly secure them. Windows ACL behavior is checked by the native Windows
CI leg; POSIX mode checks alone are not Windows evidence.
