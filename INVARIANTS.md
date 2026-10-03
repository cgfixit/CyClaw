# INVARIANTS.md — read this before touching `gate.py`, `soul.md` handling, or the scanner

This file is the load-bearing contract for the three surfaces that break CyClaw's
security posture if handled carelessly: the **FastAPI gate** (`gate.py`), **soul.md
handling** (`utils/personality.py` + the `/soul/*` routes), and the **injection
scanner/sanitizer** (`utils/sanitizer.py`, `policy.prompt_filter`). It states what
must never change, which test proves each rule, and — critically — where a guarantee
holds only by convention so you do not mistake a comment for an enforcement.

Authority order (from `CLAUDE.md`): running code wins over `config.yaml` wins over
docs. This file describes the code as it actually behaves, cross-checked against
`docs/audits/2026-07-08-due-diligence-invariants.md` (the original findings) and
resynced against the tree on 2026-10-03 (every claim and named test re-checked;
no rule changed since 2026-09-28). Every "proven by" reference is a test in
`tests/test_due_diligence_invariants.py` unless another file is named. `CLAUDE.md`
§2 summarizes Rule 6's API-key bypass and defers to this file for the detail.

Before editing any of the three surfaces, run:

```bash
GROK_API_KEY=dummy pytest tests/test_due_diligence_invariants.py -q
python3 .claude/skills/invariant-guard/check_invariants.py
```

---

## Rule 1 — `retrieve` is the unconditional graph entry (RAG-first)

**Must never change:** the compiled graph's single entry node is `retrieve`
(`graph.py` `set_entry_point("retrieve")`), and no node produces an answer before
retrieval has run. Do not add a pre-retrieval node (cache hit, greeting, classifier,
"fast path"). Do not add an entry point.

**Proven by:** `TestRagFirstEntry.test_graph_entry_point_is_retrieve` (AST) and
`test_retrieval_runs_before_any_answer_on_every_path` (the retriever is called on
every routing path). Also invariant-guard I1.

---

## Rule 2 — the external (Grok / Claude) call is triple-gated, and two gates live in `gate.py`, not the graph

**Must never change:** an external provider call (Grok **or** Claude — PR #441 added
Claude alongside Grok) requires **all three** of `app.mode == "hybrid"`,
`models.<provider>.enabled == true`, and `user_confirmed_online == true`, plus the
selected provider's usable client (`is_available()`, i.e. the provider's API key
present). The provider is chosen by `state.online_provider` (defaults to `"grok"`).

**Where each gate actually lives — do not assume "topology = policy" covers all
three:**

- `graph.user_gate_router` enforces only: confirmed, the selected `online_provider`
  matches, and that provider's client `is not None and is_available()`. It **does
  not read `app.mode` or `models.<provider>.enabled`.** Its return set is
  `{pre_action_hook_grok, pre_action_hook_claude, offline_best_effort, audit_logger}`.
  `confirmed is None` is the confirmation pause (routed to `audit_logger`; `gate.py`
  answers 200 with `needs_confirm=True`), `False` is a decline (`offline_best_effort`).
- `app.mode == "hybrid"` and `models.<provider>.enabled` are enforced **exclusively**
  by `gate.py`'s client construction: each of `grok` / `claude` stays `None` unless
  both hold. The `enabled` check requires the **literal boolean** `True` (`is True`),
  so a quoted YAML `"false"` fails closed rather than being truthy. A `None` client
  makes the router fall back to `offline_best_effort`.
- Because those two gates are config-plus-construction, the **shipped values** are
  part of the contract: `app.mode: hybrid`, `grok.enabled: true`, `claude.enabled:
  true` (armed since 2026-08-07, `docs/THREAT_MODEL.md` eighth amendment), with
  `policy.fallback.send_local_context_to_grok` / `_to_claude` both `false` so a
  confirmed call ships the bare query and never retrieved corpus text. Changing any
  of these silently changes what the graph can reach while every graph-side test
  stays green; the config tripwire below is what makes that change visible.

**Layers after the gate can only shrink the reachable space, never widen it:**

- The `pre_action_hook_<provider>` nodes (issue #963, `policy.fallback.pre_action_hook`,
  ships `enabled: false`) run after `user_gate_router` has already allowed the call.
  `pre_action_hook_router` sends an allow to exactly the provider the gate selected
  and a deny to `audit_logger` (`answer_model: hook-denied`). Once the hook is
  enabled, anything but an explicit allow is a deny.
- `utils/endpoint_trust.assert_online_destination` (called by both fallback nodes)
  pins Grok to `api.x.ai` and Claude to `api.anthropic.com` and re-refuses an explicit
  `confirmed is False`. It is a backstop to this rule, **not** a replacement for the
  gate: it never sees `app.mode` or `enabled` either.

**Consequence you must respect:** if you ever construct a `GrokClient` or
`ClaudeClient` outside its double-gated `if` in `gate.py` (a new entry point, a test
harness wired into production, an "always build the client" refactor), you will send
confirmed low-score queries to a paid external API in offline mode — the graph has no
backstop for mode/enabled. Keep both construction guards intact.

**Proven by:** `TestExternalCallGateRuntimeHalf` (no missing/unavailable/unconfirmed
/wrong-provider combination reaches Grok or Claude; each all-gates-pass case does),
`TestExternalCallGateConstructionHalf.test_external_client_construction_is_double_gated`
(AST, parametrized over `GrokClient` and `ClaudeClient`: each assignment is guarded by
an `if` mentioning `hybrid`, `enabled`, and `is True`), the tripwire
`test_graph_gate_does_not_consult_app_mode_by_design`, and
`TestShippedCoreConfigContract.test_app_mode_and_provider_enables_are_pinned` +
`test_local_context_is_never_shipped_to_a_provider` (the shipped `config.yaml`
posture). Also invariant-guard I3.

---

## Rule 3 — every path converges at `audit_logger` before END

**Must never change:** all eleven upstream nodes (`retrieve`, `route_by_score`,
`guardrail_input`, `local_llm`, `user_gate`, `pre_action_hook_grok`,
`pre_action_hook_claude`, `grok_fallback`, `claude_fallback`,
`offline_best_effort`, `guardrail_output`) reach `audit_logger`, and `audit_logger`'s
only outgoing edge is `END` (`add_edge("audit_logger", END)`). Since Phase 4 the four
answer nodes (`local_llm`, `grok_fallback`, `claude_fallback`, `offline_best_effort`)
converge through `guardrail_output`, whose single unconditional outbound edge is
`audit_logger` — one more hop, same convergence. Do not add an edge out of
`audit_logger`; do not add a node with a path to `END` that skips it. Every query —
including the `user_gate` pause, a `guardrail_input` block, and a pre-action-hook
deny — must emit an audit event.

**Proven by:** `TestAuditConvergence.test_every_path_emits_an_audit_event` (property
sweep over all five terminal path configurations),
`test_hook_denied_path_emits_audit_event`, `test_audit_logger_edges_to_end_only`,
`test_every_external_node_edges_to_audit_logger` (the four answer nodes edge to
`guardrail_output`, which edges to `audit_logger`), and
`TestGuardrailInputAuditConvergence` (a blocked input still audits, with the rail
name on the record). Also invariant-guard I4.

---

## Rule 4 — soul mutation via the HTTP path requires a human reason and passes the injection scan

**Must never change (write path):** `PersonalityManager.apply_evolution` refuses an
empty/whitespace `reason` (raises `ValueError`) and, with `scan=True` (the default,
used by `POST /soul/apply`), rejects a soul containing critical injection patterns
(`PromptInjectionError`) **before any file or DB write**. Writes are atomic
(`tmp` + `os.replace`). The only sanctioned `scan=False` caller is
`restore_from_backup` re-applying a previously vetted `.bak`; it still runs the scan
in **advisory** mode and audits any match as `soul_restore_scan_flags` (PR #99), so a
tripped `.bak` is visible without the restore being refused.

**Proven by:** `TestSoulReasonGate` (empty-reason sweep refuses; non-empty applies),
`TestSoulInjectionScanBoundary.test_apply_evolution_blocks_injection_at_write_boundary`,
and existing `tests/test_personality.py::TestApplyEvolutionInjectionGate`. Also
invariant-guard I5.

---

## Rule 5 — the soul injection scan is WRITE-PATH-ONLY; reload/drift adopt `soul.md` unscanned

**This is a sharp edge, not a feature to "fix" casually.** The injection scan runs
only in `apply_evolution`. Two other code paths change the live soul **without any
scan**:

- **Startup drift recovery** (`_load_soul`): if `soul.md` on disk differs from the
  newest `soul_versions` row, the on-disk content is adopted verbatim (a
  `DRIFT_RECOVERY` version row + `soul_drift_detected` audit event are recorded).
- **`reload()`** (`POST /soul/reload`): re-reads and adopts `soul.md` verbatim.

The adopted text is prepended to every local-LLM and offline prompt via
`get_system_prompt_additive()`. So a soul edited out-of-band (editor, restore,
drift) is trusted with no scan, by either consumer. Under the single-operator threat
model this is acceptable — but do not describe the soul as "always guarded by
the query-path banned list"; that is true only for `POST /soul/apply`.

**If you intend to add scanning to the reload/drift path** (a legitimate hardening):
update `test_reload_adopts_soul_without_scanning__scan_is_write_path_only` and this
rule deliberately — do not silently delete the tripwire.

**Proven by:** `TestSoulInjectionScanBoundary.test_reload_adopts_soul_without_scanning__scan_is_write_path_only`.

---

## Rule 6 — API-key routes fail closed; the one bypass is peer-bound; the scanner is CWD-independent

**Must never change (auth):** with `CYCLAW_API_KEY` unset, every route behind
`gate.py`'s `require_api_key` — `/soul/*`, `/ops/*`, `/audit/summary`, `/memory/*`,
and `/query/export/html` — returns 401 to every **key-based** credential, never
"open mode." Key comparison uses `hmac.compare_digest` (constant-time). Do not
reintroduce an unauthenticated fallback.

**The four credentials `require_api_key` accepts (any one is enough):**

1. the `security.api_key_optional` bypass below;
2. Bearer `CYCLAW_API_KEY`;
3. a console cookie (`cyclaw_console`) that `POST /console/session` minted
   in exchange for the key or a launcher's one-time pairing code
   (`utils/console_session.py`): an HMAC under a key derived from
   `CYCLAW_API_KEY`, so it validates nothing while the key is unset, and
   rotating the key revokes every cookie;
4. with `auth.enabled`, a login session of an **enabled `admin`**. This is
   the one credential that works with the key unset, because a login is a
   credential of its own. `operator` and `audit` sessions never pass.

Both cookie paths (3 and 4) are refused on a cross-site request, and on a
state-changing request they also need the cookie's CSRF token
(`X-CyClaw-Console-CSRF` or `X-CyClaw-CSRF`). A bad token is a 403, never a
fall-through to another credential. Do not let a non-admin role, a
cross-site request, or a CSRF-less write through either cookie path.
`docs/THREAT_MODEL.md`'s eighteenth amendment has the full boundary.

**The one deliberate bypass, and its four conditions:** `security.api_key_optional`
(ships `false`) lets `_api_key_bypass_allowed` skip the key for a request only when
**all four** hold — the flag is set; the **socket peer is loopback** (never the `Host`
header, never the bind address); **no reverse-proxy forwarding header** is present
(`X-Forwarded-For`, `X-Forwarded-Host`, `X-Forwarded-Proto`, `X-Real-IP`, and the
rest of `_FORWARDING_HEADERS`); and the request is **not cross-site**. Each condition
closes a hole the previous ones left (a proxy on this host makes every remote caller
look loopback; a page the operator visits is a loopback peer too). A remote caller
always needs the real key, however the process was launched. A missing ASGI `client`
reads as **not** loopback — the bypass fails closed on an unknown peer. Do not
collapse this to "loopback peer" alone. Defence in depth: `_require_loopback_bind`
refuses a non-loopback `api.host` while the flag is `true`
(`CYCLAW_ALLOW_NON_LOOPBACK_BIND` outranks the bind guard, never the peer check).

**What is *not* behind the API key, on purpose:**

- `POST /index/build` is gated by loopback peer + same-origin + no reverse-proxy
  forwarding header, not the key — an unset `CYCLAW_API_KEY` would otherwise
  brick first-run.
- The `/auth/*` routes and the Stage 3 credential on `POST /query`
  (`require_session_or_token`, attached only when `auth.enabled` is the literal
  `true`) are the separate session/RBAC system governed by `auth.enabled`;
  `api_key_optional` does not touch them, and they answer 503 (not 404) when auth
  is off so a route's presence never discloses whether the feature is on.

**Must never change (scanner path resolution):** `utils/sanitizer.check_input` /
`sanitize_chunk` resolve a non-absolute `config_path` against the repo root
(`_REPO_ROOT`), so the injection filter works from any working directory. Do not
revert to a bare `open("config.yaml")` — that reintroduces the CWD-relative crash
that took down the entire `/query` path when the server was launched from outside the
repo root (see finding F4). `gate.py` calls `check_input(req.query)` with no path and
relies on this anchoring. `mcp_hybrid_server.py`'s `hybrid_search` runs the same
`check_input` before retrieval (E3, #974).

**Proven by:** `tests/test_gate.py::TestSoulAndErrorPaths` (401 fail-closed),
`tests/test_security.py::TestAPIKeyAuth`, `tests/test_gate.py::TestApiKeyOptionalPeer`
(each of the four bypass conditions is necessary), `tests/test_gate.py::TestLoopbackBindGuard`
(the bind refusal and its env override), `tests/test_console_session.py` (console
cookie and admin session: CSRF, cross-site refusal, non-admin roles, unset-key
fail-closed, key rotation, single-use pairing), and `TestSanitizerCwdIndependence`
(injection blocked / clean input passes from a foreign CWD). Also invariant-guard G2.

---

## Rule 7 — audit query privacy depends on `include_query_hash: true`

**Must never change:** the shipped `config.yaml` keeps
`logging.audit_fields.include_query_hash: true`. With it true, `audit_log()` replaces
the `query` field with its SHA-256 hash and never persists raw query text. **Setting
it `false` makes the audit log persist the raw query string** (subject only to
email/IP/secret redaction) — turning `audit.jsonl` into a plaintext query log. Treat
this flag as a privacy control, not a verbosity toggle, and do not flip the shipped
default without a security review. The derived Numbat stream
(`utils/numbat_emitter.project_audit_record`) is fed the **already-redacted** record,
so it inherits this property rather than re-deriving it.

**Proven by:** `TestAuditQueryPrivacy.test_query_is_hashed_and_raw_text_never_persisted`
(property sweep), `test_distinctive_plaintext_query_is_absent_from_hashed_line`,
`test_shipped_config_enables_query_hashing` (config contract), and
`test_disabling_hashing_persists_raw_text__documented_leak`.

---

## Rule 8 — the MCP server has no LLM path (structurally, not by capability flag)

**Must never change:** `mcp_hybrid_server.py` imports no LLM client
(`LocalLLMClient`/`GrokClient`/`ClaudeClient` / anything under `llm/`) and never
calls `.generate()`. This — not the decorative `CAPABILITIES["sampling"] = None` —
is what makes the MCP server retrieval-only. `sampling` is a *client* capability in
MCP; a server declaring it `None` enforces nothing. Do not add an LLM import "because
the capability is already declared"; the flag is not a guard.

**Proven by:** `TestMcpNoLlmPath.test_mcp_server_imports_no_llm_client` and
`test_mcp_capabilities_declare_no_sampling`. Also invariant-guard G5.

---

## Rule 9 — the core request-path modules never import the out-of-band packages

**Must never change:** `gate.py`, `gate_ops.py`, `gate_auth.py`, `gate_memory.py`,
`graph.py`, and `mcp_hybrid_server.py` never import `agentic`, `sync`,
`guardrails`, `telegram`, or `opentweet` (and those packages never import the
core six). The `/ops/*` routes reach the out-of-band CLIs only through
`utils/ops_runner.py`, a `subprocess.run([...])` shim — never an import. The graph
reaches `guardrails/` only through `utils/guardrail_bridge.py`. This isolation is
what keeps the out-of-band subsystems from becoming a path around the security
invariants.

`memory/` is **not** in this out-of-band set. It is default-off and
lazy-imported (inside function bodies, never at module top) from `gate_memory.py`,
`graph.py`, and `retrieval/hybrid_search.py`. Its isolation contract is
`tests/test_memory_isolation.py`.

**Proven by:** invariant-guard I6 (AST, both directions, six core vs five OOB
packages). A narrower characterization (`gate` / `gate_ops` / `graph` / `mcp` vs
`agentic` / `sync` / `guardrails`) remains in
`TestCoreModuleIsolation.test_core_modules_never_import_out_of_band` and
`tests/test_agentic_isolation.py`.

---

## Signals that are weaker than their name suggests (do not rely on them)

- **`/health` `embeddings_local: healthy`** is a hardcoded literal, not a probe — a
  broken embedding model still reports healthy. Use `index_ready`/`graph_ready` for
  retrieval readiness. (`TestHealthEmbeddingsSignalIsStatic`.)
- **`policy.fallback.require_user_confirm`** is **unwired** — no production code
  reads it. The confirmation pause is hardcoded in `graph.user_gate_router`
  (`confirmed is None` pauses, `False` declines). It sits beside the real, wired
  `send_local_context_to_*` / `*_max_prompt_chars` knobs, which invites the wrong
  assumption that it gates the prompt; setting it `false` changes nothing.
  (`TestFallbackRequireUserConfirmIsUnwired`.)
- **`app.debug: true`** is shipped on and read by **no** code path in `gate.py`,
  `graph.py`, `utils/`, or `llm/`. It is pinned so that whoever wires it to
  something real (traceback echo, `FastAPI(debug=True)`) must confront the shipped
  value in the same diff. (`TestShippedCoreConfigContract.test_app_debug_is_pinned_and_currently_inert`.)
- **Gateway startup** does not require `GROK_API_KEY`; Grok reports unavailable
  when the key is absent.
- **`banned_patterns`** is best-effort regex over raw text (40 patterns in the
  shipped config). It is defense-in-depth, not a completeness guarantee; homoglyph /
  zero-width evasion is out of scope per the threat model.
- **`api.health_probe_external_providers`** ships `false` and must stay opt-in:
  `/health` is unauthenticated and un-rate-limited, so probing there would be
  operator-triggerable third-party egress on the operator's own key.
  (`TestShippedCoreConfigContract.test_health_does_not_probe_providers_by_default`.)
