# PR #99 Backlog — Phase 3 Implementation Plan: Network & Auth Hardening

> **Scope:** Findings **#3** (no `TrustedHostMiddleware`), **#4** (`require_api_key` no-op in
> open mode), **#5** (`user_gate_router` escalates to Grok regardless of app mode).
> **Parent:** `docs/ACTION_PLAN_PR99_2026-06-20.md` (PR #106); findings in PR #99.
>
> **These change security posture and/or routing and touch tests that encode current
> behavior. They need explicit product decisions — flagged inline as `DECISION:`. This is a
> plan, not the implementation.**

---

## 0. TL;DR

- **#3** — add a Host allow-list so DNS-rebinding can't drive server-side soul writes; must
  include the LAN host `10.0.0.112` or the home-lab browser breaks.
- **#4** — open mode (no `CYCLAW_API_KEY`) leaves all `/soul/*` mutations unauthenticated.
  Fixing it is a **product decision** (fail-closed vs. auto-generate a startup token) and
  **requires updating `test_auth_disabled_when_no_env_var`**.
- **#5** — in offline mode the low-score path still *asks* "send to Grok?" but there is no
  Grok, so the confirm prompt is a **dead-end**. Route offline low-score straight to
  best-effort; **requires updating `test_low_score_signals_needs_confirm`**.

These interact: #3 (rebind defense) + #4 (auth) together close the "remote page silently
overwrites the soul" path, so plan them as a set, land in dependency order #3 → #5 → #4.

---

## 1. Finding #3 — Add `TrustedHostMiddleware`

### 1.1 Problem statement
Without a `Host` header check, a DNS-rebinding attack can point a victim browser at
`127.0.0.1:8787` and issue same-origin-looking requests; CORS blocks the attacker from
*reading* the response, but **state-changing** `POST /soul/*` still executes server-side
(especially in open mode — see #4).

### 1.2 Evidence (current code on `main`)
- `gate.py:156-163` — only `CORSMiddleware` is registered; there is no
  `TrustedHostMiddleware`.
- `config.yaml:174-181` — `allowed_origins` already enumerates the legitimate hosts incl.
  `http://10.0.0.112` (LAN) — the source of truth for who may talk to the server.

### 1.3 Root-cause analysis
CORS governs *response readability*, not *request execution*. A `Host` allow-list is the
correct control for rebinding; it is simply absent.

### 1.4 Proposed fix
```python
# gate.py — register BEFORE CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts)
```
where `_allowed_hosts` is derived from config (see §1.5), defaulting to
`["127.0.0.1", "localhost", "10.0.0.112"]`.

### 1.5 Design decisions
- **DECISION (host source):** derive `allowed_hosts` from a new
  `security.allowed_hosts` config key, **or** parse hostnames out of the existing
  `allowed_origins` (strip scheme/port). Prefer an explicit `security.allowed_hosts` list to
  avoid coupling CORS origins to Host matching and to keep the curly-quote `null` origin
  (config.yaml:175, left as-is per maintainer) from leaking in.
- **Port note:** `TrustedHostMiddleware` matches the host **without** port, so no `:8787`
  entries are needed. `*.localhost` style wildcards are supported if ever required.
- **Failure mode:** a mismatched Host yields HTTP 400 — make sure the default list covers
  every way the operator reaches the box (loopback name, loopback IP, LAN IP).

### 1.6 Implementation steps
1. Add `security.allowed_hosts` to `config.yaml` (with the three defaults + a comment).
2. Read it in `gate.py`; register `TrustedHostMiddleware` before CORS.
3. Update `docs/SETUP.md` / `README` to note: add your host here if you reach CyClaw by a
   new name/IP.

### 1.7 Test strategy
- `tests/test_gate.py` (TestClient): request with an **allowed** `Host` → 200; request with
  a **disallowed** `Host` (e.g. `evil.com`) → 400. TestClient lets you set the `Host` header.

### 1.8 Risk & rollback
- **Risk:** locking out a legitimate access path (e.g. operator uses a hostname not in the
  list) → 400s. Mitigate with conservative defaults + docs. **Rollback:** remove the
  middleware registration.

### 1.9 Acceptance criteria
- [ ] `TrustedHostMiddleware` registered before CORS, list sourced from config.
- [ ] LAN host `10.0.0.112`, `127.0.0.1`, `localhost` all still reach the server.
- [ ] Disallowed Host → 400 (test).

---

## 2. Finding #4 — `require_api_key` no-op in open mode

### 2.1 Problem statement
When `CYCLAW_API_KEY` is unset, `require_api_key` returns immediately, so **every**
soul-mutation endpoint (`/soul/propose`, `/soul/apply`, `/soul/reload`, `/soul/restore`) is
unauthenticated. Combined with #3, that is the unauthenticated-soul-overwrite path.

### 2.2 Evidence (current code on `main`)
- `gate.py:75-85` — `require_api_key`: `if not api_key: return` (open mode = no auth).
- `gate.py:136-141` — startup already **warns** about open mode.
- `tests/test_security.py:135-151` — `test_auth_disabled_when_no_env_var` **asserts** open
  mode returns 200 (current behavior is intentional today).

### 2.3 Root-cause analysis
"Open mode" was a deliberate convenience default, but it makes the mutation endpoints a
soft target the moment the Host/CORS controls are bypassed.

### 2.4 Proposed fix — DECISION REQUIRED
Two viable directions; product must choose:
- **Option A — auto-generate a startup token (recommended).** When `CYCLAW_API_KEY` is
  unset, generate a random token at startup, log it **once**, and enforce it. Local operator
  copies it from the log; remote rebind attacker never sees it. Preserves "works out of the
  box" while closing the gap.
  ```python
  api_key = os.environ.get("CYCLAW_API_KEY") or secrets.token_urlsafe(32)
  if not os.environ.get("CYCLAW_API_KEY"):
      logger.warning("Generated ephemeral API key for this run: %s", api_key)
  ```
- **Option B — fail-closed.** Refuse to start (or refuse `/soul/*`) without an explicit
  `CYCLAW_API_KEY`. Strongest, but breaks zero-config startup.

**DECISION:** pick A or B. This plan assumes **A** unless told otherwise.

### 2.5 Test impact (mandatory)
- `test_auth_disabled_when_no_env_var` **must be updated/replaced** — under Option A there is
  no "auth disabled" state. Replace with `test_ephemeral_key_enforced_when_env_unset`
  asserting that a request with no/garbage token → 401 and with the logged token → 200.
- Keep `test_protected_accepts_correct_key` / `…rejects_wrong_key` (still valid).

### 2.6 Implementation steps
1. Implement chosen option in `gate.py` (`require_api_key` + startup key resolution).
2. Update the startup warning to reflect the new behavior.
3. Update `test_security.py` per §2.5.
4. Document in `docs/SETUP.md` (how to grab/set the key).

### 2.7 Risk & rollback
- **Risk (A):** operators must read the token from the log for soul mutations; document
  clearly. **Rollback:** restore the early-return open-mode branch.

### 2.8 Acceptance criteria
- [ ] No code path leaves `/soul/*` unauthenticated.
- [ ] Tests updated to the new contract and green.
- [ ] SETUP docs explain the key lifecycle.

---

## 3. Finding #5 — `user_gate_router` ignores app mode (offline confirm dead-end)

### 3.1 Problem statement
In **offline** mode a low-score query is sent through the user-confirmation gate ("send to
Grok online?"), but there is no GrokClient, so confirming leads only to the offline
placeholder — the prompt is a dead-end that misrepresents capability.

### 3.2 Evidence (current code on `main`)
- `graph.py:347-361` — `user_gate_router` branches **only** on `user_confirmed_online`,
  never on `cfg["app"]["mode"]`.
- `graph.py:199-210` — `grok_fallback_node` None-guards and degrades to offline placeholder
  (so it doesn't crash, but the UX path is pointless offline).
- `gate.py:234-248` — the HTTP layer returns the "Vault miss … Send query to Grok online?"
  confirm message regardless of mode.
- `tests/test_graph.py` — `test_low_score_signals_needs_confirm` (offline default) asserts
  the confirm signal; `test_grok_not_called_in_offline_mode` documents the current
  None-guard degradation.

### 3.3 Root-cause analysis
Mode-gating is enforced **only** by whether `grok` is `None` at build time; the routing
*topology* still walks the confirm path even when escalation is impossible. The router has no
access to `cfg` (signature is `user_gate_router(state)`).

### 3.4 Proposed fix
Make the graph mode-aware so offline low-score queries skip the confirm gate and go straight
to `offline_best_effort`:
- Inject `mode` into `GraphState` at `route_by_score_node` (it already receives `cfg`), e.g.
  set `state["app_mode"] = cfg["app"]["mode"]`; **or**
- Branch in `route_by_score`/`user_gate_node`: if `mode != "hybrid"` (or `grok` unavailable),
  set `needs_user_confirm = False` and route low-score → `offline_best_effort` directly.
- Correspondingly, `gate.py` should not emit the "send to Grok" confirm message in offline
  mode.

### 3.5 Test impact (mandatory)
- **DECISION:** confirm the intended offline UX. If offline low-score should answer
  best-effort *without* a confirm round-trip, then `test_low_score_signals_needs_confirm`
  (which runs in offline default) **must be updated** to expect a direct best-effort answer,
  and a new `test_low_score_confirm_only_in_hybrid` should assert the confirm gate fires
  **only** in hybrid mode.
- `test_confirmed_hybrid_routes_to_grok` stays green (hybrid path unchanged).

### 3.6 Implementation steps
1. Thread `mode` into the routing decision (state injection at `route_by_score`).
2. Skip the confirm gate when escalation is impossible (offline or grok disabled/None).
3. Align `gate.py`'s confirm-message branch with the new routing.
4. Update/extend `test_graph.py` per §3.5.

### 3.7 Risk & rollback
- **Risk:** changes the offline low-score UX (no more confirm prompt). That is the intended
  fix, but it is user-visible — get product sign-off. **Rollback:** revert routing + message.

### 3.8 Acceptance criteria
- [ ] Offline mode: low-score query answers best-effort with no dead-end confirm prompt.
- [ ] Hybrid mode: confirm → Grok path unchanged.
- [ ] `test_graph.py` updated to the new offline contract; hybrid tests unchanged.

---

## 4. Sequencing, dependencies, effort

| Step | Depends on | Decision? | Est. |
|------|-----------|-----------|------|
| #3 TrustedHost + config + test | — | host-source key | 30 min |
| #5 mode-aware routing + tests | — | offline UX | 45 min |
| #4 auth in open mode + tests | best after #3 | A vs B | 45 min |

**Land order:** #3 → #5 → #4. #4 last because it carries the biggest product decision and is
most valuable once #3's rebind defense is in place. Could be one "network/auth hardening" PR
or three small ones; given the test churn, **three reviewable PRs** is cleaner.

## 5. Verification commands
```bash
GROK_API_KEY=dummy pytest tests/test_gate.py tests/test_security.py tests/test_graph.py \
                          -q --tb=short
```

## 6. Out of scope (tracked elsewhere)
- Retrieval scoring (#1/#6) → Phase 1.
- Injection-defense parity (#2/#7/#12) → Phase 2.
- Audit redaction consolidation (#10) → Phase 4.
