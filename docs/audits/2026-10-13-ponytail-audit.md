# Ponytail audit — 2026-10-13

Base: `6519135` (`origin/main`, 2026-10-13). Read-only audit; no code was changed.
"Ponytail" is the retired `/ponytail` lazy-senior-dev discipline
(`docs/audits/PONYTAIL_PLUGIN_6.29.md`): YAGNI, stdlib-first, minimal
abstraction (abstract at four or more call sites), no dead code, no speculative
generality, correctness over cleverness. The last run is
`docs/audits/2026-09-11-metrics-reader-refactor.md`; its five deferred
candidates are re-checked at the end.

## Method and scope

Three independent static passes over the 227 tracked non-test Python files
(`git ls-files '*.py'` minus `tests/` and `tools/lora_finetune/tests/`), each
built on stdlib `ast` plus word-boundary grep over all 1,049 tracked files:

1. **Dead code** — every def, class, method and ALL_CAPS constant with zero
   references outside its own definition, after filtering FastAPI handlers,
   LangGraph nodes, `unittest`/`http.server` name-dispatched hooks,
   `reset_*_for_tests` helpers, Protocol stubs and `[project.scripts]` entries.
2. **Abstraction** — one-use helpers, 8-line sliding-window duplicate hashes
   (whitespace stripped, comments and blanks dropped), and pure forwarders.
3. **Speculative generality** — `config.yaml` leaf keys with no reader,
   `CYCLAW_*` env vars read-but-undocumented or documented-but-unread,
   `ruff --select ARG,B006,B008` unused parameters, and runtime dependencies
   with two or fewer import sites.

Every row below was confirmed by reading the consumer, and the headline rows
were re-verified by the coordinating session (`ruff` ARG001 output, `diff` of
the two Telegram gates, the `_source_agent` body, the two resolver bodies).
Known blind spot: a dead symbol whose name is shared with a live one (`run`,
`close`) is invisible to a name-count method, so the lists are a floor.

## Ponytail audit and selection

Line counts are estimates of possible cuts, not a recommendation to apply
every candidate. Nothing was applied; selection is the owner's call. Tiers
follow `CLAUDE.md` §7: Tier 1 is Low (local, reversible), Tier 2 is Medium
(shared paths, tests move with the code), Tier 3 needs an owner decision.

### Tier 1 — safe cuts (about 135 source lines, zero dependencies)

- `shrink:` `utils/numbat_emitter.py:329` `_source_agent` reads
  `numbat.source_agent` and then returns `DEFAULT_SOURCE_AGENT` on every path
  (`value if value == DEFAULT else DEFAULT`). Replace the one call at `:438`
  with the constant; `tests/test_numbat_emitter.py:182` already asserts the
  constant. **~6 lines.** If the shape is a deliberate "pinned until an
  allowlist exists" placeholder mirroring `_source_type`, say so in a comment
  instead; today it reads as a bug that happens to be harmless.
- `shrink:` `.claude/skills/CyClaw-Sandbox/run_full_verification.py` and the
  `.codex/skills/Cyclaw-Sandbox/` copy: `MockResponse` (never instantiated),
  `MockGrokClient._verify_request_shape` and `MockClaudeClient._verify_request_shape`
  (never called; `last_headers` is only ever `None`, so both always return
  `False`), and the `last_headers` attribute they read. **~70 lines across both
  copies.** The `.codex` SKILL.md says not to blindly mirror, but this dead
  code is identical in both.
- `shrink:` `agentic/harness_optimizer/patching.py:61-79` `_release_artifact_lock`
  is byte-identical to `agentic/registry.py:228-246` `_release_registry_lock`,
  and `patching.py` already imports the other lock helpers from `registry`.
  Alias-import it; both names stay importable for
  `test_agentic_harness_optimizer.py:24` and `test_agentic_registry.py:30`.
  **~17 lines.** (2026-09-11 candidate 3, unchanged since.)
- `shrink:` `agentic/fsconnect/cli.py:189-218` `_run_write` re-implements
  `_run_writer` (`:240-262`); route write/append/mkdir/move through
  `_run_writer` lambdas the way `cmd_delete` already does. Same 0/2/3/4 exit
  codes. **~12 lines.**
- `shrink:` unused parameters (ruff ARG001): `label` on
  `guardrails/broker.py:144` `guarded_generate`. Two edits travel together:
  drop the parameter from the broker and drop the `label=label` keyword from
  the bridge's internal call at `utils/guardrail_bridge.py:105`; the bridge's
  own `_generate_guard(..., label=...)` signature stays, because `graph.py`
  passes `label` to it and guardrails ship enabled, so removing only one side
  raises `TypeError` on every guarded generation. Also `allow_demand` on
  `utils/win_schtasks.py:202` `_settings_xml` (the only caller at `:332` never
  passes it). **~4 lines.**
- `keep:` the unread `cfg` on `graph.py:365` `retrieve_node` and `graph.py:646`
  `user_gate_node` (ruff ARG001; bound by `partial` at `:1282`/`:1287`). Not a
  free cut: both nodes are called positionally with `cfg` by the two Sandbox
  verifiers (`.claude/skills/CyClaw-Sandbox/run_full_verification.py:709/730/738`,
  the `.codex` copy `:728/749/757`), `tests/ci_rag_smoke.py:343`,
  `tests/test_rerank.py` (four sites) and `tests/test_graph.py:1310`, so
  dropping the parameter is a 13-call-site signature change plus a core-file
  edit for two unread words. The ponytail call is to leave the signature alone.
- `shrink:` one-use private helpers where inlining is shorter:
  `utils/spend.py:174` `_tokens_for_provider`; `agentic/executor/apply.py:25`
  `_null_config_path` (`os.devnull` is already `nul` on Windows);
  `agentic/registry.py:124` `_reclaim_guard_path` and `:47` `_utcnow`;
  `utils/ratelimit.py:49` `_is_pg_dsn` (also redundant: `startswith("postgres")`
  covers `postgresql`, a redundancy repeated in both DB `connect()`s);
  `utils/sequence_detect.py:93` `_is_hook_denied`. **~25 lines.** Do not
  touch the sibling `utils/spend.py` `_append_line`, which
  `test_spend.py:472` monkeypatches by name.
- `shrink:` genuinely unreferenced one-liners: `opentweet/cli.py:61` `_ok`
  (`_err`/`_warn` beside it are used); `.claude/skills/dotenv-guard/envline.py:31`
  `SECRET_SUFFIXES` (no reader; `is_secret_name` calls `SECRET_POLICY`
  directly; keep the four comment lines above it, which document suffix
  semantics); `import json` at
  `.claude/skills/CyClaw-Sandbox/terminal_emulation.py:22`. **~4 lines.**
- `fix:` `utils/authn_cli.py:62` `_resolve_config_path` has drifted from the
  other five copies: it never calls `.resolve()`, so a relative
  `--config ../x.yaml` yields a different path string than `metrics.py:47`
  produces for the same input. Zero lines saved; one-line consistency fix.

### Tier 2 — worth doing, tests move with the code (about 185 source lines)

- `shrink:` `utils/authn_store.py:36-86` vs `utils/personality_db.py:62-111`
  `connect()`: the Postgres branch plus the SQLite owner-only 0600
  create/repair are ~40 identical lines. Extract one opener that takes an
  already-resolved DSN and a label; callers keep their differing DSN
  precedence (auth: config before env; personality: env before config) and
  the "DSN never in errors" contract. **~30-35 lines.** (2026-09-11 candidate
  1, deferred twice; `authn_store` already imports `_harden_pg_conninfo` from
  `personality_db`, so the seam exists.)
- `shrink:` `telegram/runner.py:182-208` vs `:308-333`: the inbound gate
  (enabled, `mode == chat`, allowlist with audit and raise, rate limiter) is
  identical modulo blank lines. Extract `_check_inbound_gate(cfg, chat_id,
  update_id)`. Security contract, but duplication here is drift risk, not
  defence in depth. **~20 lines.** Both paths need a test on the shared helper.
- `shrink:` `agentic/cli.py:157, 260, 614, 785`: the 13-line
  `fetch_*_context` try/except block appears four times and the 7-line
  injection refusal three times (`:278/:631/:799`). Extract
  `_fetch_context_bundle`; site `:157` passes `include_diff` and does not
  refuse, and the refusal verb differs ("plan"/"run"), so pass the verb in or
  keep the refusal inline. **~30 lines.**
- `shrink:` `telegram/cli.py` (six commands: `cmd_send`, `cmd_poll`,
  `cmd_poll_plist`, `cmd_health_plist`, `cmd_poll_task`, `cmd_health_task`) and
  `opentweet/cli.py` (two: `cmd_schedule_plist`, `cmd_schedule_task`): the
  load-config / `EXIT_ENV` / `_disabled_notice()` preamble. Extract
  `_load_enabled_cfg(args)`; the per-command mode and platform checks stay
  inline. **~24 lines.** Not part of the set: OpenTweet `cmd_post` refuses with
  `EXIT_ENV` when disabled (a different exit contract that must stay),
  `cmd_status` continues when disabled, and `cmd_test` has no such preamble.
- `shrink:` 30 identical 2-line print helpers (`_err` ×9, `_heading` ×8, `_ok`
  ×6, `_kv` ×4, `_warn` ×3) across the nine out-of-band CLIs and
  `retrieval/clear_cache.py`. A stdlib-only `utils/cli_out.py` saves **~80
  lines** but is low priority: `clear_cache`, `metrics` and `authn_cli` must
  keep the telemetry-kill-first import order (G1), and `opentweet`'s `_kv`
  redacts passwords, so it stays local.
- `shrink:` five `config.yaml` keys no code reads: `app.name` (`:5`),
  `app.env` (`:6`), `app.debug` (`:9`, its own comment says "Read by no code";
  already removed by open PR #1636, so skip it here),
  `models.embeddings.provider` (`:54`, the backend is hardcoded in
  `retrieval/embeddings.py:264-288`), and `policy.fallback.enabled` (`:228`,
  comment says "Read by no code"; I3 governs). PR #1636 removes `app.debug` and edits
  `tests/test_due_diligence_invariants.py:744`, which pins it as inert, and
  `policy.fallback.enabled` is set to no effect by `tests/conftest.py:189`.
  (`tests/judge_eval.py:401` is not evidence here: it disables
  `models.local_llm.fallback.enabled`, a live switch `llm/client.py` reads.)
  `config.yaml` is a shared file: trial-merge against open PRs first
  (`CLAUDE.md` §4).
- `docs:` three env vars read in code and documented nowhere: `CYCLAW_PYTHON`
  (`utils/launchd_plist.py:88`; the error at `:67` tells users to set it),
  `CYCLAW_LOCAL_LLM_API_KEY` (`llm/client.py:558`) and
  `CYCLAW_LOCAL_LLM_FALLBACK_API_KEY` (`llm/client.py:625`). Document in
  `macos/README.md` and the local-LLM section of `README.md`.

### Tier 3 — owner decision or retained on purpose

- `docs/memories/zOld/run_full_verification.py` (1,173 lines),
  `docs/memories/zOld/_test_terminal_consoles.py` (222) and
  `docs/CyClaw Audit Bundle Export Script.py` (356) are referenced by nothing.
  The zOld pair is covered by the "dated docs stay dated" archive policy
  (`fable-protocol/references/knowledge-base.md:225`); the export script is
  UNSURE and may be run by hand. **~1,750 lines**, outside the source tree.
- Production code only tests use: `guardrails/profiles.py` (240 lines;
  `profiles.yaml` and `guardrails/README.md` depend on it) and
  `guardrails/boundary.py` (138; its docstring states it has no caller and is
  kept), `memory/store.py` `get_fact`/`get_proposal` (planned public API per
  `docs/memory/IMPLEMENTATION_PLAN.md:576/583`), `AuthManager.count_enabled_admins`,
  `RateLimiter.tracked_ips`, `Scorecard.to_markdown`, `LoopResult.final_decision`.
  **~420 lines**; the guardrail scaffolds are an owner retention.
- Validated-only config keys: `policy.fallback.require_user_confirm` (boot
  rejects anything but `true`, a deliberate placeholder),
  `agentic.deepagent_github.allow_shell_execution` and `allow_github_writes`
  (`permissions.py:38/40` raise on `true`, fail-closed tripwires),
  `agentic.harness_optimizer.allow_local_model_judge` (bool-validated, never
  read; mark reserved or drop), `sync.include_soul` (deprecated no-op, warns
  at `sync/cli.py:131`; drop after the window).
- Config-path resolver (six copies, ~20-25 lines; 2026-09-11 candidate 2):
  keep. `test_metrics.py:434` and `test_indexer.py:223` monkeypatch each
  module's `_REPO_ROOT` and call `_resolve_config_path` by name, and
  `utils/sanitizer.py` deliberately avoids importing `utils/logger.py`. Only
  the drift fix above is recommended.
- Same-origin look-alikes that are different contracts, not duplication:
  `gate_auth.py:248/270` `CROSS_ORIGIN_BLOCKED` (route security),
  `graph.py:613/912` `assert_local_destination` (explicit per node, I3
  backstop), `llm/client.py:875/947` Grok/Claude client init,
  `utils/authn_manager.py` `login`/`change_password`, `utils/logger.py`
  `wait`/`drain` and the three writer threads (I4), `telegram/media.py:376/407`.
- Forwarders that are real seams: `agentic/fsconnect/client.py:52`
  `build_injection_patterns` (a def over the `guardrails.rails` function;
  `test_guardrails_shared_scanner.py:89` imports it from here, so a direct
  re-export with `__all__` is the most that should change),
  `gate.check_rate_limit` (tested by name), `utils/secret_policy.is_secret_name`,
  `llm.client.set_graph_deadline`, the netconnect/sqlconnect `run_op` modules.
- Dependencies: none to drop. `rank-bm25` (one import site) is the only
  plausibly stdlib-replaceable runtime dependency (~40 lines with
  `math`/`Counter`), and it should not be: `min_score` and the RRF tuning are
  calibrated to its `get_scores`. `nltk` has no stdlib stemmer and its pin is
  the CVE fix; `huggingface-hub` and `langchain-core` are transitive anyway;
  `websockets` is a documented import-time floor for `langgraph-sdk`.
- No empty abstractions: `HardSandbox` has three implementations,
  `HarnessRunner` and `ProposerClient` two each, `_GeneratingClient` covers
  three clients, `_PgVectorBase` two stores. There are no factory classes.
- Lint posture: the repo-wide walk CI runs, `ruff check --select
  F401,F811,F841,B007 .`, is clean under the project config, but that walk
  never visits `docs/memories/zOld/`; naming
  `docs/memories/zOld/run_full_verification.py` explicitly reports 7 hits
  (4 F401, 1 B007, 2 F841). That file is already a whole-file Tier 3
  candidate above, so the hits add no new symbol. The five F401 hits visible
  only with `--isolated` are in the vendored `agentic/vendor/unslop/`
  (excluded in `pyproject.toml`, upstream code left verbatim). The 18 unused `request: Request` handler arguments in
  `gate.py`/`gate_memory.py`/`gate_ops.py` are FastAPI DI shape and were scoped out.

Potential total: about 320 source lines in Tiers 1-2, zero dependencies
added or removed, plus about 1,750 lines of archived scripts under `docs/`
and about 420 lines of test-only production code that are the owner's call.

## 2026-09-11 candidates, re-checked

| Candidate | Status at `6519135` |
|---|---|
| Duplicate DB `connect()` in `authn_store` / `personality_db` | Still present, ~30-35 lines; `authn_store` now imports `_harden_pg_conninfo` from `personality_db` |
| Repeated config-path resolution | Grown from five to six copies (`utils/authn_cli.py:62` added, and drifted); keep, fix the drift |
| Artifact-lock release duplicating registry release | Still present, unchanged, ~17 lines; alias import |
| One-use `suppress_attr_error` in `sqlconnect/client.py` | Gone; replaced by `contextlib.suppress` (`:21`, `:559`) |
| Identical disabled-result branches in `memory/consolidation.py` | Gone; file deleted in #1595 |

## Invariants

No code changed in this audit, so every invariant is as it was at `6519135`.
For the candidates above: none touches a graph edge, router, entry point or
audit path (I1, I2, I4); no `graph.py` change is proposed at all, since the
unread `cfg` parameters are an explicit keep (13 positional callers). None touches the I3 gate (`policy.fallback.enabled` is read by
no code; the gate is `user_gate_router`). None touches soul writes (I5). None
adds an import across the core-six / out-of-band boundary (I6); the proposed
`utils/cli_out.py` would be imported only by out-of-band CLIs and
`clear_cache`, after the telemetry kill. The DB `connect()` extraction must
preserve the 0600 and DSN-redaction contracts named in
`docs/THREAT_MODEL.md`.

## Verification

Run directly in this session: the three `ast`/grep passes (stdlib `python3`,
no third-party imports); `ruff check --select F401,F811,F841,B007,ARG
--exclude .claude,tests,tools/lora_finetune/tests .` (ruff 0.16.8, the
`constraints.txt` pin), which reports 57 hits: 52 `ARG*` in non-test code
(23 ARG001, 17 ARG002, 10 ARG005, 2 ARG003, triaged above into 3 trims, 2
keeps, 18 FastAPI handler arguments, interface overrides and lambdas) plus
the 5 vendored F401. The same selection without the exclusions reports
1,026, almost all `ARG*` inside `tests/` (fixtures, mocks and callbacks take
unused arguments by design, and the `tests/*` per-file-ignores do not cover
ARG), which this audit did not triage; and hand re-verification of each
Tier 1 claim by reading the definition and grepping its name. After review, four rows were corrected
against the tree: the `graph.py` `cfg` parameters have 13 positional callers
(now a keep), the OpenTweet preamble set is two commands, not four,
`tests/judge_eval.py:401` sets a different key and was dropped as evidence,
and the lint-posture line now states the zOld walk exclusion. Not run: the test suite, `--cov`,
`ci_rag_smoke.py`, or any live server (nothing executable changed). The
Python 3.12 venv was still building for most of the session, so PyYAML was
unavailable and `config.yaml` keys were enumerated with an indentation
parser; every "never read" key was then confirmed by reading its would-be
consumer, not by the parser alone.

## Limits and rollback

Name-count dead-code detection misses dead symbols whose names are shared
with live ones. Duplicate detection used 8-line windows, so 4-7 line repeats
were found only where a reviewer noticed them. The 60 `PLR0913`
too-many-arguments hits were not triaged. Nothing to roll back: the audit
changes no tracked file other than adding this report.
