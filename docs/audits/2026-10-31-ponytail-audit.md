# Ponytail audit — 2026-10-31

Base: `a27cff0` (`origin/main`, 2026-10-31). Read-only audit; no code was changed.
"Ponytail" is the retired `/ponytail` lazy-senior-dev discipline
(`docs/audits/PONYTAIL_PLUGIN_6.29.md`; the plugin was removed in #1351, so the
`ponytail:ponytail-audit` skill no longer exists and this run follows the method
the last audit recorded): YAGNI, stdlib-first, minimal abstraction (abstract at
four or more call sites), no dead code, no speculative generality, correctness
over cleverness. The previous run is `docs/audits/2026-10-13-ponytail-audit.md`
at `6519135`; its rows are re-checked at the end. Between the two bases, 226
commits deleted about 37,500 Python lines, mostly the agentic GitHub layer,
coding loop, executor, harness optimizer and `sqlconnect` (#1699).

## Method and scope

Three static passes over the 168 tracked non-test Python files (65,906 lines;
`git ls-files '*.py'` minus `tests/` and `tools/lora_finetune/tests/`), with
references counted over all 916 tracked files:

1. **Dead code** — a stdlib `ast` name-count of every def, class, method and
   ALL_CAPS constant, with references split into code, tests and docs. Then
   `vulture` 2.16 run twice, once with the tests as part of the reference set
   and once without, so the diff lists the names only tests reach. `vulture`
   ran ad hoc through `uvx`; it is not a project dependency.
2. **Abstraction** — 8-line sliding-window duplicate hashes (whitespace
   stripped, comments and blanks dropped), a 6-line pass limited to the core
   and shared modules, one-use private helpers, pure forwarders, and Protocols
   or base classes with fewer than two implementations.
3. **Speculative generality** — `config.yaml` leaf keys with no reader (a
   path-aware match: the key must appear near its parent section's name),
   `CYCLAW_*` env vars read but undocumented or documented but unread,
   `ruff --select ARG,B006,B008` unused parameters, `ERA001` commented-out code,
   and runtime dependencies with two or fewer import sites.

Each row below was then confirmed by reading the consumer. Wherever a row
claims a behavior, the code was run directly. Known blind spot: a dead symbol
that shares its name with a live one (`run`, `close`) is invisible to a
name-count, so the dead-code list is a floor.

## Ponytail audit and selection

Line counts estimate possible cuts; they are not a recommendation to apply
every candidate. Nothing was applied; selection is the owner's call. Tiers
follow `CLAUDE.md` §7: Tier 1 is Low (local, reversible), Tier 2 is Medium
(shared paths, tests move with the code), Tier 3 needs an owner decision.

The headline is that duplication has already cost correctness here. Three rows
below are copies where a fix landed on one side only: the Codex Sandbox smoke
script's false-green pytest verdict, the service generators' claim about
`gate.py`'s port rule, and the atomic writers that #1785 hardened in four
places but not in the other five.

### Tier 1 — safe, local (about 40 source lines cut, one fix)

- `fix:` `.agents/skills/cyclaw-sandbox/smoke.sh:436-452` section F (full
  pytest suite) still reports pass/fail by grepping for `N failed`. With
  `pyproject.toml:152` `addopts = "-q --tb=short"` plus the script's own `-q`,
  pytest runs at `-qq` and prints no count line, so `FAILED_C` falls back to
  `0` and the section passes. **Reproduced:** the section's own lines, sourced
  against a one-test failing suite under the same `addopts`, print
  `PASS Full pytest suite (passed=0 skipped=0)` while pytest exits 1. The
  `.claude` copy (`.claude/skills/CyClaw-Sandbox/smoke.sh:437-486`) was fixed
  to use pytest's exit code. Run as a control against the same suite, it
  prints `FAIL Full pytest suite (pytest exit 1; ...)`. Port that block, or
  shim the file (Tier 3 row below). **~+10 lines**, a correctness fix rather
  than a cut. The `.agents` SKILL.md calls these "legacy helpers" and says not
  to chain them as one automatic gate, but a Codex agent that runs `smoke.sh`
  still reads a green section F for a red suite.
- `shrink:` `utils/launchd_plist.py:225-243` `bootout()` has no production
  caller; only `tests/test_utils_launchd_plist.py:138-157` calls it. The one
  real unload, `sync/scheduler.py:555-574` `LaunchdScheduler.remove`, carries
  its own inline copy, and that copy is the sturdier one: it passes
  `env=child_environment("filesystem")` and tolerates
  `OSError`/`SubprocessError`, including a `TimeoutExpired` from a wedged
  `launchctl`, which the helper would raise. Delete the helper and its two
  tests, and drop the `'[launchctl, "bootout"'` marker from the otel-hardening
  T13 row at `.claude/skills/otel-hardening/check_otel.py:1151`. T13 checks
  that marker in `utils/launchd_plist.py`, so leaving the row in place turns
  the cut into a T13 finding. `shutil.which("launchctl")` stays, in
  `launchctl_bin`. **~19 source lines.**
- `shrink:` `telegram/runner.py` `poll_forever` (`:504`) clamps
  `retry_after` against `_POLL_RETRY_SLEEP_CAP_SEC` twice with the same
  four-condition guard, once for retryable handler results (`:558-566`) and
  once for a retryable `TelegramRuntimeError` (`:575-583`). Extract
  `_retry_delay(retry_after, floor) -> float`. **~8 lines.**
- `shrink:` `guardrails/boundary.py:31-43` `_FORBIDDEN_DECISION_KEYS` is the
  same nine-key frozenset as `guardrails/metrics.py:42-54`
  `FORBIDDEN_METRIC_KEYS`. Import it, if `boundary.py` stays (owner-retained
  scaffold, Tier 3). **~11 lines.**
- `test:` `_FORWARDING_HEADERS` is the same five-header tuple at `gate.py:1571`
  and `gate_auth.py:67` (whose comment says "same set as gate.py"), and no test
  pins them equal. This set is what stops a reverse proxy on the host from
  turning every remote caller into a loopback peer for the
  `api_key_optional` bypass. If a header is added to one copy and not the
  other, one route family is exposed. A stdlib AST test that parses both
  literals and asserts equality costs ~15 test lines, imports neither module
  (so it avoids the `import gate` trap in `CLAUDE.md` §4), and touches no auth
  code. A single source of truth is the Tier 3 row.
- `shrink:` skill-script nits: unused `label` on
  `.claude/skills/CyClaw-Sandbox/terminal_emulation.py:63` `show_response`,
  unused `name` on `.agents/skills/cyclaw-sandbox-test/scripts/run_sandbox_test.py:149`
  `_start_process`, and the usage line at
  `.agents/skills/cyclaw-sandbox/test_terminal_consoles.py:10`, which points
  at a `scripts/test_terminal_consoles.py` that does not exist. **~3 lines.**

### Tier 2 — worth doing, tests move with the code (about 200 source lines)

- `shrink:` + `fix:` `_read_gate_port` is byte-identical in
  `macos/generate_service_plist.py:125-152` and
  `windows/generate_service_task.py:99-126`, both added by #1773 to "read
  api.port exactly as gate.py binds it". Their shared docstring says gate.py
  "silently falls back to 8787 for anything else (a quoted "9000", a bool, a
  float)". That is wrong for a bool. **Executed:** `gate._listen_port`
  (`gate.py:2067-2085`), extracted by `ast` and run, maps `port: true` to `1`
  and `port: false` to `0` (an OS-assigned random port), because `bool` is an
  `int` subclass. It also passes `99999` and `-1` straight through, and no
  boot validation of `api.port` exists. The generators refuse a bool with a
  message naming the wrong fallback; gate.py would bind port 1 or a random
  port. Two pieces: (a) move one copy into a shared stdlib+PyYAML helper both
  generators import (**~27 lines**); (b) the owner decides whether gate.py
  rejects a bool and an out-of-range `api.port` the way it already rejects a
  bad `CYCLAW_GATE_PORT`, or whether the docstring changes. (b) is a core-file
  behavior change, so it needs sign-off.
- `shrink:` + `fix:` atomic writes are implemented by hand in about ten
  places, and #1785 (fsync before rename, unlink a failed temp) hardened four:
  `retrieval/indexer.py`, `agentic/fsconnect/indexer.py`, `sync/filters.py`
  and `utils/spend.py`. The plain write-content-to-path writers it did not
  reach:
  `utils/launchd_plist.py:161-173` `write_plist` and
  `utils/win_schtasks.py:149-151` / `:267-272` (a fixed `.tmp` name, no fsync,
  no cleanup; **probed:** `write_plist({"Label": None}, ...)` raises
  `TypeError`, keeps the old target intact, and leaves a 189-byte
  `job.plist.tmp` behind); `sync/scheduler.py:173-200` `_write_posix_launcher`
  (no fsync); `sync/scheduler.py:239-241` `_write_windows_launcher` (writes in
  place, not atomic at all). `telegram/state.py:92-112` and
  `sync/filters.py:164-180` are already complete and would be callers too. One
  stdlib `utils/atomic_write.py` (`mkstemp` in the target directory, a mode,
  fsync, `os.replace`, unlink on failure) has six or more callers, so it
  clears the four-site bar. **~40-50 lines net**, plus durability for five
  sites. Keep out of scope: `utils/personality.py`
  `_atomic_write_owner_only`, since I5 and
  `.claude/skills/invariant-guard/check_invariants.py:474` look for
  `os.replace(` in that file; `agentic/fsconnect/pathsafe.py` (fd-relative
  replaces, its TOCTOU contract); `utils/gen_cert.py` (a paired cert/key
  rollback); and the numbat rollover rename.
- `shrink:` `sync/scheduler.py:203-242` `_write_windows_launcher` re-implements
  `utils/win_schtasks.write_cmd_launcher` (`:113-151`, which the module
  already imports `bat_quote` and `python_executable` from). It adds a
  `cd /d <root>` line and drops the env-name/value validation. Routing it
  through `write_cmd_launcher` with an optional working directory closes the
  atomicity gap above in passing. **~25 lines** (overlaps the atomic-write
  row). Tests that move: `tests/test_sync_scheduler.py:692-698`,
  `tests/test_telemetry_env_delivery.py:264`.
- `shrink:` `agentic/fsconnect/cli.py` `cmd_trash_empty_plist` (`:304`) and
  `cmd_trash_empty_task` (`:381`) repeat the same 24-line preflight: load,
  enabled check, weekday/hour/minute range checks, writable-root pick
  (`:315-338` vs `:389-412`), plus the same 11-token argv
  (`:347-359` vs `:417-427`). Extract `_trash_schedule_preflight(args)`; the
  platform checks and the writer calls stay per-command, with the same
  `0/2/3` exit codes. **~20 lines.**
- `shrink:` (carried over, still open) the load-config / `EXIT_ENV` /
  `_disabled_notice()` preamble in six `telegram/cli.py` commands and two
  `opentweet/cli.py` commands. Extract `_load_enabled_cfg(args)`, with the
  same exclusions as last time (OpenTweet `cmd_post`, `cmd_status`,
  `cmd_test`). **~24 lines.**
- `shrink:` (carried over, low priority) 26 two-line print helpers (`_err`,
  `_heading`, `_ok`, `_kv`, `_warn`) across seven CLIs, down from 30. Same
  caveats: telemetry-kill-first import order (G1) for `clear_cache`, and
  OpenTweet's redacting `_kv` stays local. **~70 lines.**
- `shrink:` (optional) `opentweet/config.py` `_validate_loopback_url` (`:84`)
  and `_validate_https_base` (`:120`) share a 12-line prefix: shell
  metacharacters, `urlparse` plus a `.port` probe, userinfo rejection. This is
  a security validator in an out-of-band channel, so extract
  `_parse_checked_url(url, field_name)` only together with its tests.
  **~10 lines.**

### Tier 3 — owner decision or retained on purpose

- **Codex Sandbox forks.** `.agents/skills/cyclaw-sandbox/` carries full
  copies of seven `.claude/skills/CyClaw-Sandbox/` files, 2,778 lines in all
  (line count, then differing diff lines): `run_full_verification.py` 1,380
  (801; the `.claude` copy is 1,351), `smoke.sh` 502 (56), `verify.sh` 282
  (14), `macos-smoke.sh` 215 (4), `test_terminal_consoles.py` 205 (67),
  `windows-smoke.ps1` 119 (4) and `gate_runtime_check.py` 75 (25). The four
  smallest diffs are mostly path and privacy-skill-name lines. Fixes have
  landed on one side only, in both directions:
  - the smoke false green (Tier 1);
  - `.claude` `gate_runtime_check.py:55-78` lists the ops, auth and memory
    routes and asserts the retired `/ops/agentic` and `/ops/sqlconnect` stay
    unregistered, while the `.agents` copy (`:55-58`) checks seven routes;
  - `.agents` `test_terminal_consoles.py:36-40` has a loopback-only
    `_local_url` guard on `CYCLAW_URL` and asserts header values
    case-insensitively (`:108-120`), and the `.claude` copy has neither.
  - `run_full_verification.py` has diverged in features, not just text:
    `.claude` alone has `_probe_ollama_tier`; `.agents` alone has
    `_install_deps`, `phase_audit_integrity` and `MockLocalLLMClient`.

  The `.agents` SKILL.md (`:54-55`) already sets the policy for
  `mock_ollama.py` and `terminal_emulation.py`: "delegate to the maintained
  Claude implementations; update those implementations rather than restoring
  copies". Both are 9-11 line `runpy` shims. Ponytail recommends extending the
  same policy: merge the one-sided fixes into `.claude`, then shim
  `macos-smoke.sh`, `windows-smoke.ps1`, `verify.sh`, `gate_runtime_check.py`
  and `test_terminal_consoles.py`. `smoke.sh` needs a `CYCLAW_REPORT_DIR` knob
  in the `.claude` copy first, because the Codex copy writes its report to a
  temp directory, not `.claude/`. `run_full_verification.py` needs a merge
  decision on the Codex-only phases. Up to **~2,700 lines**. A third,
  separate mock Ollama lives at
  `.agents/skills/cyclaw-sandbox-test/scripts/mock_ollama.py` (133 lines),
  next to the `.claude` one and the shim. `tests/test_cyclaw_sandbox_skill.py`
  parametrizes over both `verify.sh` copies and would follow a shim. The
  bot-patch refusal rules (#1734, #1764) cover agent configuration paths, so
  this is an owner change, not a bot patch.
- **Forwarding-header and same-origin sources.** Besides the duplicated
  `_FORWARDING_HEADERS` (Tier 1 test), the same-origin predicate
  (hostname, allow-list, port and scheme match) is repeated at
  `gate.py:1652-1658` and `gate_auth.py:306-312`, and `gate_auth.py:186`
  defines its own `_host_matches_allow_list`. Moving them into one stdlib
  module both import removes the drift. It touches `gate_auth.py`, a
  protected path, and auth is High tier, so the owner decides; the test is
  the interim guard.
- `utils/numbat_emitter.py:1023` `emit_numbat_event` repeats all 28 keyword
  parameters of `build_event` (`:387`) and forwards each by name, so adding a
  field means editing three places. `**fields: Unpack[_EventFields]` with one
  `TypedDict` saves ~45 lines and keeps mypy's keyword checking, but trades
  away a signature readers can see at a glance. This is a matter of taste.
- `metrics.py:355-363` (plus the counters at `:405-409`, the branch at
  `:438-456`, the summary at `:519-525` and the CLI print at `:627-640`)
  aggregates `agentic_context_injection_finding`, whose only producer was
  removed on 2026-10-18. Its comment keeps it on purpose, so audit logs
  written before the removal still summarize and `GET /audit/summary` keeps
  its `injection_findings` shape. Ponytail's call: give it an exit date.
  Retire it, with `tests/test_metrics_injection_findings.py` (187 lines),
  once no retained `audit.jsonl` predates 2026-10-18, and note the API shape
  change. **~45 source lines.**
- Production code that only tests use, unchanged from last time and still
  owner retentions: `guardrails/profiles.py` (240 lines), `guardrails/boundary.py`
  (138) with `guardrails/qwen_registry.py:117` `provenance_ids_for_docs`
  (its docstring records the owner decision), `memory/store.py:297`/`:469`
  `get_fact`/`get_proposal`, `AuthManager.count_enabled_admins`
  (`utils/authn_manager.py:431`) and `RateLimiter.tracked_ips`
  (`utils/ratelimit.py:575`). Not candidates: `utils/spend.py:515`
  `ticks_mismatch` (used by the operator-run `tests/spend_live_probe.py:119`),
  the `LocalLLMClient.backend_source` attribute (observability, read by tests),
  and the test seams `reset_rails_singleton`, `reset_local_backend_cache`,
  `reset_embedding_cache` and `utils/logger.reset_config_cache` (the last is
  also called by both `smoke.sh` copies).
- Validated-only config keys: `policy.fallback.require_user_confirm` (boot
  rejects anything but `true`, a deliberate placeholder) and
  `sync.include_soul` (a deprecated no-op that warns at `sync/cli.py:131`;
  drop it when its window ends). Everything else in `config.yaml` has a reader:
  #1750 removed the four unread keys the last audit listed.
- Look-alikes that are different contracts, so keep them: `AuthManager.login`
  vs `change_password` (`utils/authn_manager.py:650-663` vs `:690-702`, a
  timing-equalized credential prefix); the three bounded writer threads
  (`utils/logger.py` notes and lines, `utils/numbat_emitter.py`; I4); the
  Grok/Claude client init (`llm/client.py:875-888` vs `:947-960`);
  `graph.py:613`/`:914` `assert_local_destination` (an explicit per-node I3
  backstop); `telegram/media.py:377`/`:408`; the
  `agentic/fsconnect/cli.py` vs `agentic/netconnect/cli.py` exception ladders
  (different typed hierarchies and exit codes); the three
  `fsconnect_skipped_stat` audit sinks (client, indexer, writer; each binds
  its own `config_path`); the scaffolding shared by the `.claude/skills/*/check_*.py`
  checkers (stdlib-only standalone skills, no shared import by design); and
  `check_otel.py:71-92` against `utils/telemetry_kill.py` (an independent
  oracle, which is the point).
- Config-path resolvers: five copies now (`metrics.py:47`,
  `retrieval/clear_cache.py:63`, `retrieval/indexer.py:42`,
  `utils/authn_cli.py:62`, `utils/sanitizer.py:77`), down from six with the
  agentic removal. Keep them, for the reasons the 2026-10-13 audit gives.
- Forwarders that are real seams: `agentic/fsconnect/client.py:52`
  `build_injection_patterns` (imported by name in tests),
  `gate.check_rate_limit`, `llm.client.set_graph_deadline`,
  `utils/secret_policy.is_secret_name`, and
  `.claude/skills/verify-deps/extract_pins.py:43` `_load_requirements_reqs`
  (a named alias whose docstring states that the two file grammars are equal).
- One-use private helpers: 72 with three or fewer body statements and no test
  reference. They are not re-proposed. The 2026-10-13 apply pass judged
  inlining them a cost call: a reviewer reads many unrelated subsystems to
  save a few lines, and a named helper often reads better.
- Dependencies: none to drop. `rank-bm25` (one import site) is still the
  only plausibly stdlib-replaceable runtime dependency, and still should not
  be replaced, because `min_score` and the RRF tuning are calibrated to its
  `get_scores`. `nltk` provides the Porter stemmer. `langchain-core` and
  `websockets` (zero direct imports) are deliberate direct pins, and
  `pyproject.toml:53-54` explains the websockets floor.
- Abstractions: no empty ones. `_GeneratingClient` (`graph.py:39`) is a
  structural Protocol over three clients, `_PgVectorBase` has two
  subclasses, and `_BackgroundFileHandler` is used directly as well as by its
  console override. There are no factory classes.

Potential total: about 40 source lines in Tier 1 plus one correctness fix,
about 200 in Tier 2 (including the atomic-write durability fix and the port
rule drift), and in Tier 3 up to about 2,700 lines of forked Codex Sandbox
helpers plus about 90 lines of owner-taste or exit-dated code. No dependency
is added or removed.

## 2026-10-13 candidates, re-checked

Status of every 2026-10-13 row at `a27cff0`:

| Candidate | Status at `a27cff0` |
|---|---|
| `_source_agent` constant-returning clamp | Kept on purpose; now carries the "pinned on purpose" comment (`utils/numbat_emitter.py:329-338`) |
| Dead Sandbox mocks (`MockResponse`, `_verify_request_shape`), both copies | Gone (`b21e833`) |
| `_release_artifact_lock` duplicate | Gone with `agentic/harness_optimizer/` and `agentic/registry.py` (#1699) |
| fsconnect `_run_write` re-implementing `_run_writer` | Gone; write/append/mkdir/move now route through `_run_writer` lambdas |
| `guarded_generate` `label`, `win_schtasks` `allow_demand` | Still present, not applied on purpose (13 test call sites; cost call) |
| One-use helpers (`_tokens_for_provider`, `_is_pg_dsn`, `_is_hook_denied`, ...) | Still present, not applied on purpose; the agentic ones went with #1699 |
| `opentweet/cli.py` `_ok`, `envline.SECRET_SUFFIXES`, `terminal_emulation` `import json` | Gone |
| `authn_cli._resolve_config_path` drift | Not a defect (apply-pass correction); unchanged |
| Duplicate DB `connect()` in `authn_store` / `personality_db` | Done: one `personality_db.open_db` (#1772) |
| Telegram inbound gate duplicated in `runner.py` | Done: `_check_inbound_gate` (`telegram/runner.py:169`) |
| `agentic/cli.py` context-fetch copies | Folded (#1692), then the file was removed (#1699) |
| Telegram/OpenTweet CLI preamble | Still open (Tier 2 above) |
| 30 print helpers | 26 now; still open, low priority |
| Unread config keys (`app.name`, `app.env`, `models.embeddings.provider`, `policy.fallback.enabled`) | Done (#1750; `app.debug` went earlier) |
| Undocumented `CYCLAW_PYTHON` and the two local-LLM key env vars | Done (#1688); every `CYCLAW_*` env read in Python is now documented |
| `docs/memories/zOld/*` and the audit bundle export script | Removed from the tree (still reachable at `246e406`) |
| Test-only production code | Same retentions; `Scorecard.to_markdown` and `LoopResult.final_decision` went with #1699 |
| Validated-only `agentic.*` tripwire keys | Gone with their subsystems |

## Invariants

No code changed in this audit, so every invariant is as it was at `a27cff0`;
`check_invariants.py` reports 46 passed, 0 failed. For the candidates above:
none adds, removes or reroutes a graph edge, router, entry point or audit path
(I1, I2, I4). The one `graph.py`-adjacent idea, the unread `cfg` on two
nodes, stays an explicit keep (ARG001 still reports it; there are 12 external
callers, 7 positional and 5 by keyword, down from 13 last time). The `api.port` row touches `gate.py`'s bind-port helper,
not the I3 gate. No row writes the soul: the atomic-write helper excludes
`utils/personality.py` precisely so I5's static check keeps its anchor. No row
adds an import across the core-six / out-of-band boundary (I6): the shared
port helper and `utils/atomic_write.py` would live in `utils/` and be imported
by the generators, `sync/` and `telegram/`, never the reverse. The
forwarding-header row is guarded by a test first because a single-source
refactor would edit `gate_auth.py`, a protected path.

## Verification

Run directly in this session, all against `a27cff0`:

- The `ast` name-count, duplicate-window, one-use and forwarder scanners
  (stdlib `python3`), and `vulture` 2.16 through `uvx`, run with and without
  the tests as references.
- `ruff check` at the `constraints.txt` pin (0.17.1, through `uvx`):
  - `--select F401,F811,F841,B007 .` is clean.
  - `--select F,B,S .` (the `lint.yml` gate) is clean.
  - `--select ARG,B006,B008` without `tests/` reports 57 hits: 21 ARG001,
    22 ARG002, 2 ARG003, 12 ARG005. Of those, 16 are FastAPI `request`
    arguments; the rest are mock or interface signatures, the two
    `graph.py` keeps, `label` on `guarded_generate`, and the two skill nits
    in Tier 1.
  - `--select ERA001` reports 11 hits, all prose that parses as code, so the
    tree has no commented-out code.
- The `config.yaml` key scan, run under the session's Python 3.12 venv with
  PyYAML. The five keys it flagged were each traced to a reader by hand.
- The `CYCLAW_*` env-var diff between code and `*.md`.
- The dependency import-site count from `pyproject.toml`.
- Three behavior probes:
  - `gate._listen_port`, extracted and executed.
  - `utils.launchd_plist.write_plist` on an unencodable document.
  - Section F of both `smoke.sh` copies, sourced with stub `pass`/`fail`
    functions against a deliberately failing one-test suite under the repo's
    `addopts`: the Codex copy printed PASS, the `.claude` copy printed FAIL.
- `check_invariants.py` (46/0) and `doc_sync.py` (0 drift) before and after
  adding this report.

Not run: the test suite, `--cov`, `ci_rag_smoke.py`, or a live server; nothing
executable changed.

## Limits and rollback

Name-count dead-code detection misses dead symbols whose names collide with
live ones. The 8-line window pass covered every non-test file. The 6-line
pass covered only the core and shared modules, so 4-7 line repeats in skill
and channel code appear only where a reviewer noticed them. Line counts in
the forked Sandbox row come from `diff`, which overstates the effort for
whitespace-only reflows. Nothing to roll back: the audit changes no tracked
file other than adding this report.
