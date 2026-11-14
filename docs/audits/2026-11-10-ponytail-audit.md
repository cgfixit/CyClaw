# Ponytail audit — 2026-11-10

Base: `b840d9e` (`origin/main`, 2026-11-10). Read-only audit; no code was changed.
"Ponytail" is the retired `/ponytail` lazy-senior-dev discipline
(`docs/audits/PONYTAIL_PLUGIN_6.29.md`). The plugin was removed in #1351, so
the `ponytail:ponytail-audit` skill no longer exists, and this run follows the
method `docs/audits/2026-10-31-ponytail-audit.md` recorded: YAGNI,
stdlib-first, minimal abstraction (abstract at four or more call sites), no
dead code, no speculative generality, correctness over cleverness. That audit
ran at `a27cff0`, and every one of its rows is re-checked at the end of this
report. There are 55 commits between the two bases. Most of them applied
2026-10-31 rows (#1796, #1798, #1799, #1803, `c2246d5`, `f1e2560`), so the tree
is leaner. Python changed by 1,927 insertions and 2,216 deletions.

## Method and scope

The same three static passes were run over the 170 tracked non-test Python
files (64,789 lines; `git ls-files '*.py'` minus `tests/`), with references
counted over all 929 tracked files:

1. **Dead code.** A stdlib `ast` name-count of every def, class, method and
   ALL_CAPS module constant, with references split into code, tests and docs.
   Then `vulture` 2.16 (through `uvx`; not a project dependency), run once
   with the tests as references and once without; the difference lists names
   that only tests reach.
2. **Abstraction.** Duplicate hashes over an 8-line sliding window (whitespace
   stripped, comments and blanks dropped) across every non-test file, plus a
   6-line pass over the core and shared modules (`gate*.py`, `graph.py`,
   `mcp_hybrid_server.py`, `utils/`, `retrieval/`, `llm/`, `memory/`,
   `schemas/`, `metrics.py`). A separate 8-line pass covered
   `tools/lora_finetune/`, comparing its dry-run script with its own tests.
3. **Speculative generality.** `config.yaml` leaf keys with no reader (a
   path-aware match: the key must appear near its parent section's name);
   `CYCLAW_*` names in code but not in any `*.md`, and the reverse; ruff
   `ARG,B006,B008` unused parameters; `ERA001` commented-out code; and runtime
   dependencies with two or fewer import sites.

Each candidate below was confirmed by reading its consumer. Where a row claims
a behavior, the code was run. Known blind spot, unchanged: a dead symbol whose
name collides with a live one is invisible to a name-count, so the dead-code
list is a floor.

## Ponytail audit and selection

Line counts estimate possible cuts; they are not a recommendation to apply
every candidate. Nothing was applied; selection is the owner's call. Tiers
follow `CLAUDE.md` §7: Tier 1 is Low (local, reversible), Tier 2 is Medium
(shared paths, tests move with the code), Tier 3 needs an owner decision.

The headline: the duplications that had cost correctness on 2026-10-31 are
fixed. That was the Codex smoke false green, the `api.port` bool drift, the
unpinned forwarding headers and the non-durable scheduler writers. No new
correctness defect turned up. What remains is the second-order cleanup those
fixes made possible: `utils/atomic_write.py` exists now but has only three of
its six natural callers. Two copies of things also remain, which is below the
four-site bar, but one of them is a test double that can drift from the script
it stands in for.

### Tier 1 — safe, local (about 11 source lines)

- `shrink:` (carried over from 2026-10-31 Tier 1, still open)
  `guardrails/boundary.py:31-43` `_FORBIDDEN_DECISION_KEYS` is still the same
  nine-key frozenset as `guardrails/metrics.py:42-54`
  `FORBIDDEN_METRIC_KEYS`. #1799 took the other rows in that tier and left
  this one. Import it, as long as `boundary.py` stays (it is an
  owner-retained scaffold, Tier 3). **~11 lines.**

Dead-code pass: nothing new in Tier 1. Every `vulture`/name-count hit outside
the retentions listed in Tier 3 is one of these:

- a decorator-registered route (`gate*.py` handlers);
- a framework override (`do_GET`, `log_message`, `redirect_request`,
  `setUpClass`);
- a Pydantic, TypedDict or dataclass field read through serialization
  (`schemas/api.py`, `graph.py` state keys, `memory/models.py`,
  `TrashEntry.deleted_at`);
- an API constant tests import on purpose: `sync/cli.py:55` `EXIT_SAFETY`
  ("exit codes are an API", `CLAUDE.md` §4), and
  `utils/external_pre_hook.py:60` `REASON_CODES`, which the numbat gate doc
  cites as the reason vocabulary.

`ruff --select F401,F811,F841,B007` and the `lint.yml` gate `--select F,B,S`
are both clean.

### Tier 2 — worth doing, tests move with the code (about 120 source lines)

- `shrink:` **finish the atomic-write consolidation.** #1803 (`84b7bf1`) added
  `utils/atomic_write.py` `write_atomic` (`mkstemp` in the target directory,
  chmod, fsync, `os.replace`, unlink on failure). It is called from
  `utils/launchd_plist.py:170`, `utils/win_schtasks.py:150`/`:268` and
  `sync/scheduler.py:187`/`:226`. Three plain write-content-to-path writers
  still hand-roll the same sequence:
  - `telegram/state.py:92-112` `_save_json`: the same `mkstemp`/fsync/replace/
    unlink, line for line. It becomes
    `write_atomic(path, (json.dumps(...) + "\n").encode(), mode=0o600)`;
    `mkstemp` already creates the file at 0o600, so the mode is unchanged.
  - `sync/filters.py:155-180` `write_filter_file`: a fixed
    `cyclaw_filters.txt.tmp` name rather than `mkstemp`. Its mode is currently
    whatever the umask gives (typically 0o644). Pass `mode=0o644` to keep that
    exactly, or 0o600 if the owner wants it tightened; rclone runs as the same
    user either way.
  - `macos/_enable_fsconnect_readlist.py:99-118`: `NamedTemporaryFile` plus a
    chmod that keeps the config file's original mode. It becomes
    `write_atomic(config_path, rendered.encode(), mode=original_mode)`.

  That makes six caller modules, which clears the four-site bar.
  **~40 lines.** Keep out of scope, for the reasons the 2026-10-31 audit
  gives:
  - `utils/personality.py` (I5's static check anchors on `os.replace(` in that
    file);
  - `agentic/fsconnect/pathsafe.py` (fd-relative replaces);
  - `utils/gen_cert.py` (paired rollback);
  - the numbat rollover;
  - the two index writers, `retrieval/indexer.py:376-389` and
    `agentic/fsconnect/indexer.py:228`. Both stream `json.dump` to disk, and
    `write_atomic` takes `bytes`, so routing them through it would build the
    whole BM25 payload in memory as a string first.
- `shrink:` `memory/store.py` runs
  `SELECT * FROM memory_proposals WHERE id = ?` at five sites: `:457`, `:473`
  (`get_proposal`), `:519`, `:623` and `:632`. The three write paths
  (`create_proposal`, `apply_proposal`, and `reject_proposal` twice) each
  need the row on the connection that holds their transaction, so they
  cannot call `get_proposal`, which opens a second one. Extract
  `_proposal_row(conn, proposal_id)`. Also in `reject_proposal`, the
  `row is None` check at `:636-637` follows an `UPDATE ... WHERE id=? AND
  status='pending'` that just hit exactly one row, inside the same
  `BEGIN IMMEDIATE` transaction on one SQLite connection. So it cannot fire,
  and the helper can drop it. **~12 lines.** `memory/` is a shared module
  (Medium); `tests/test_memory_store.py` and `tests/test_memory_routes.py`
  exercise the create, apply and reject paths.
- `shrink:` `tools/lora_finetune/dryrun_finetune.py:31-110` and
  `tools/lora_finetune/tests/test_finetune_integration.py:15-89` carry the
  same `_FakeTokenizer`, `_FakeModel`, `_FakeFastModel` and `_FakeSFTConfig`
  stand-ins for Unsloth/TRL. The 8-line pass finds three identical runs
  (`:36-45`, `:47-55`, `:98-110` against `:20-29`, `:30-38`, `:77-89`). Both
  exist to check that `finetune_qwen38.py` calls the real APIs with the
  right keywords. If the script gains a keyword, only one fake may learn it,
  and the other then passes or fails for the wrong reason. The test already
  puts the parent directory on `sys.path`, so it can import the fakes from
  `dryrun_finetune`. **~30 lines.** CI: `lora-finetune.yml` runs both
  (`dryrun_finetune.py` at `:84`, the tests outside `testpaths`).
- `shrink:` (carried over, smaller) `sync/scheduler.py:191-227`
  `_write_windows_launcher` is still a hand-written copy of
  `utils/win_schtasks.write_cmd_launcher` (`:113-151`):
  - the same scrub lines, the `%`-doubled `set` lines, the quoted argv and the
    CRLF join;
  - plus one `cd /d <root>` line;
  - minus the env-name and env-value validation.

  #1803 closed the atomicity gap, so what remains is pure duplication. An
  optional `cwd: Path | None` on `write_cmd_launcher` removes it.
  **~15 lines.** Tests move with it: `tests/test_sync_scheduler.py`'s
  launcher-content asserts and `tests/test_telemetry_env_delivery.py`.
- `shrink:` (carried over, still open) the load-config / `EXIT_ENV` /
  `_disabled_notice()` preamble. It appears in six `telegram/cli.py` commands
  (`:172`, `:231`, `:284`, `:353`, `:420`, `:484`; the 8-line pass still
  matches `:225-232` against `:278-421`) and in two `opentweet/cli.py`
  commands (`:213`, `:261`). Extract `_load_enabled_cfg(args)`, with the same
  exclusions as before. **~24 lines.**
- `shrink:` (carried over, low priority) 27 two-line print helpers (`_err`,
  `_heading`, `_ok`, `_kv`, `_warn`, ...) across seven CLIs, 26 last time.
  The caveats are unchanged: G1 import order for `clear_cache`, and
  OpenTweet's redacting `_kv` stays local. **~70 lines.**
- `shrink:` (carried over, optional) `opentweet/config.py:84`
  `_validate_loopback_url` and `:120` `_validate_https_base` still share a
  12-line prefix (`:89-100` against `:125-136`). Extract it only together
  with its tests. **~10 lines.**

### Tier 3 — owner decision or retained on purpose

- **Same-origin single source (carried over).** The forwarding-header tuple
  is now pinned equal by `tests/test_forwarding_headers_contract.py` (#1798),
  so the interim guard is in place. The same-origin predicate still exists
  twice (`gate.py:1653-1659` vs `gate_auth.py:306-312`, which the 6-line pass
  matches), and so does `_host_matches_allow_list` (`gate.py:1663`,
  `gate_auth.py:186`). Merging them touches `gate_auth.py`, which is
  protected and auth-tier, so it is the owner's call.
- `utils/numbat_emitter.py:1023` `emit_numbat_event` still repeats
  `build_event`'s (`:387`) keyword list (10 matching 8-line windows).
  `**fields: Unpack[_EventFields]` is unchanged as an option and remains a
  matter of taste.
- `metrics.py:361-363` and the `agentic_context_injection_finding`
  aggregation are still in place, with the same `GET /audit/summary` shape
  reason. The name-count now flags `INJECTION_FINDING_CODE` and
  `SCANNER_UNAVAILABLE_CODE`: nothing in production reads them, and only
  `tests/test_metrics_injection_findings.py` does. They exist only to name
  the codes the retired producer wrote. Ponytail's call stands: retire the
  block (~45 lines, plus those 187 test lines) once no retained `audit.jsonl`
  predates 2026-10-18. The audit log rotates on size (`logging.max_bytes`
  50 MiB), not age, so the owner has to check their own retained files.
  Code cannot date this.
- `utils/authn_manager.py` `validate_session` (`:729-748`) and the CSRF
  rotation path (`:766-774`) repeat the five-line session-expiry block (look
  up the row, refuse a revoked one, revoke an expired one, commit). That is
  two sites in security code, and the explanatory comment lives on the first.
  Keep it. Reported because the 8-line pass will keep finding it.
- `macos/generate_service_plist.py` vs `windows/generate_service_task.py`
  still share their argparse and `--confirm/--reason` refusal preamble
  (`:57-72`/`:26-38`, `:88-98`/`:54-64`, `:128-136`/`:102-110`). The
  duplicated part that mattered, the port read, moved into
  `utils/gateway_url.read_gate_port` in `c2246d5`. What is left is two
  platform-specific scripts with different risk text. Keep.
- Production code that only tests use: the same owner retentions as on
  2026-10-31, and none were added:
  - `guardrails/profiles.py`;
  - `guardrails/boundary.py` (plus `qwen_registry.provenance_ids_for_docs`);
  - `memory/store.py:297`/`:469` `get_fact`/`get_proposal`;
  - `AuthManager.count_enabled_admins` (`utils/authn_manager.py:431`);
  - `RateLimiter.tracked_ips` (now `utils/ratelimit.py:598`);
  - the test seams `reset_rails_singleton`, `reset_local_backend_cache`,
    `reset_embedding_cache`, `utils/logger.reset_config_cache`, and the
    `reset_*_for_tests` helpers in `telegram/` and `opentweet/`;
  - `utils/spend.py:515` `ticks_mismatch`.
- Validated-only config keys: unchanged. `policy.fallback.require_user_confirm`
  is a deliberate placeholder that must be `true`. `sync.include_soul` is a
  deprecated no-op (`config.yaml:626`). The key scan flagged only
  `evals.local_judge.enabled`/`.model`, and they do have a reader: the
  operator-run `tests/judge_eval.py` (`_local_judge_config`), outside the
  scanned set.
- `CYCLAW_*` names: code and docs agree. Every name the diff raised is one
  of these:
  - a Python constant: `CYCLAW_TAG` (`utils/numbat_emitter.py:66`),
    `_CYCLAW_VERSION` (`gate.py:55`) and the Sandbox runner's `CYCLAW_DIR`
    global;
  - a shell local in `macos/cyclaw-linux-key.sh` or the dotenv-guard harness;
  - a shell variable in a doc example (`setup-guide.md:494` `CYCLAW_KEY`,
    `.agents/skills/cyclaw-sandbox/SKILL.md:44` `CYCLAW_AUDIT_TEMP`);
  - the historical `CYCLAW_AGENTIC_WRITE_DISABLE`, which
    `docs/THREAT_MODEL.md:1004` names explicitly as removed.

  No environment variable is read without documentation.
- Unused parameters: ruff `ARG` without `tests/` reports 49 (down from 57).
  16 are FastAPI `request` arguments. The rest are mock or interface
  signatures, the two `graph.py` `cfg` keeps, `guarded_generate`'s `label`,
  the `on_timeout`/error-mapping lambdas in `llm/client.py`, and Unsloth-shaped fakes in
  `tools/lora_finetune/`. `ERA001` reports 8 hits, all prose that parses as
  code, so there is no commented-out code.
- Look-alikes, config-path resolvers, forwarders and one-use helpers: same
  verdicts as the 2026-10-31 and 2026-10-13 audits, not re-proposed. That
  covers:
  - `AuthManager.login`/`change_password` (a timing-equalized prefix);
  - the three bounded writer threads (`utils/logger.py:415`/`:562` `wait`/
    `drain`, and the numbat writer);
  - the Grok/Claude client init;
  - `graph.py`'s two `assert_local_destination` backstops;
  - the fsconnect/netconnect exception ladders;
  - the three `fsconnect_skipped_stat` sinks;
  - the stdlib checker scaffolding;
  - `check_otel.py` as an independent oracle;
  - the five private `_resolve_config_path` copies.
- Dependencies: none to drop. `oauthlib`, `langchain-core` and `websockets`
  (zero direct imports) are deliberate direct pins, with reasons in
  `pyproject.toml:18` and `:55-56`. `rank-bm25` (one import site) stays,
  because the RRF tuning is calibrated to its `get_scores`.
- Abstractions: still no empty ones or factory classes.

Potential total: about 11 source lines in Tier 1 and about 200 in Tier 2,
of which about 100 are new this run (atomic writers, memory row fetch, LoRA
fakes) and about 105 are carried over. Tier 3 adds about 45 exit-dated lines
plus the auth single-source decision. No dependency is added or removed, and
no correctness defect was found.

## 2026-10-31 candidates, re-checked

Status of every 2026-10-31 row at `b840d9e`:

| Candidate | Status at `b840d9e` |
|---|---|
| Codex Sandbox `smoke.sh` section F false green | Done (#1796); the copy is now a 7-line delegate |
| `launchd_plist.bootout` test-only helper | Done (#1798) |
| Telegram `retry_after` clamp twice | Done (#1799): `telegram/runner.py:511` `_retry_delay` |
| `_FORBIDDEN_DECISION_KEYS` = `FORBIDDEN_METRIC_KEYS` | **Still open** (Tier 1 above) |
| `_FORWARDING_HEADERS` equality test | Done (#1798): `tests/test_forwarding_headers_contract.py` |
| Three skill-script nits | Done (#1799) |
| `_read_gate_port` copies + `api.port` bool/out-of-range drift | Done (`c2246d5`): one `utils/gateway_url.resolve_port`, used by `gate._listen_port` and both generators. **Executed:** `True`, `False`, `99999`, `-1` and `'9000'` all raise `ValueError`; `9000` passes |
| Hand-rolled atomic writers | Partly done (#1803): `utils/atomic_write.py` serves launchd, schtasks and both scheduler launchers; three writers remain (Tier 2 above) |
| `_write_windows_launcher` re-implements `write_cmd_launcher` | Atomicity fixed (#1803); the duplication is still open (Tier 2 above) |
| fsconnect trash-schedule preflight twice | Done (#1799): `agentic/fsconnect/cli.py:304` `_trash_schedule_preflight` |
| Telegram/OpenTweet CLI preamble | Still open (Tier 2) |
| Print helpers | 27 (was 26); still open, low priority |
| OpenTweet URL-validator prefix | Still open, optional (Tier 2) |
| Codex Sandbox forks (~2,700 lines) | Done (`fe75407`, `f1e2560`): `.agents/skills/cyclaw-sandbox/` now holds 6-11 line delegates to the `.claude` implementations, plus its own `browser_render_check.py` and `test_verification_contract.py` |
| Same-origin / allow-list single source | Still open, owner decision (Tier 3) |
| `emit_numbat_event` keyword repeat | Unchanged, taste (Tier 3) |
| `agentic_context_injection_finding` aggregation | Unchanged; exit date still owner-checked (Tier 3) |
| Test-only production code, validated-only keys, look-alikes, resolvers, forwarders, one-use helpers, dependencies, abstractions | Unchanged verdicts |

## Invariants

No code changed in this audit, so every invariant is as it was at `b840d9e`;
`check_invariants.py` reports 46 passed, 0 failed. None of the candidates
above adds, removes or reroutes a graph edge, router, entry point or audit
path (I1, I2, I4), or touches the I3 gate. The `memory/store.py` row changes
only how a row is fetched inside the existing transactions; propose, apply
and reject keep their `reason` requirement and their status guards. No row
writes the soul: `utils/personality.py` stays outside the atomic-write row so
I5's static anchor survives. No row crosses the core-six / out-of-band
boundary (I6). `utils/atomic_write.py` is imported by `telegram/`, `sync/` and
`macos/`, never the reverse, and a `utils/` import from those out-of-band
packages is already the pattern there. The LoRA row stays inside
`tools/lora_finetune/`.

## Verification

Run directly in this session, all against `b840d9e`:

- The `ast` name-count, the 8-line duplicate window over all 170 non-test
  files, the 6-line window over the core and shared modules, and the 8-line
  LoRA pass (stdlib `python3.12`). Also `vulture` 2.16 through `uvx`, with
  and without the tests as references.
- `ruff check` at the `constraints.txt` pin (0.17.1, through `uvx`):
  - `--select F401,F811,F841,B007 .` is clean;
  - `--select F,B,S .` is clean;
  - `--select ARG,B006,B008 --exclude tests` reports 49 hits;
  - `--select ERA001 --exclude tests` reports 8 hits, all prose.
- The `config.yaml` key scan (PyYAML through `uvx`), the `CYCLAW_*` diff
  between code and `*.md` (NUL-separated, so doc filenames with spaces are
  counted), and the dependency import-site count from `pyproject.toml`.
- One behavior probe: `utils.gateway_url.resolve_port` run on `True`,
  `False`, `99999`, `-1`, `'9000'` and `9000`.
- `check_invariants.py` (46/0) and `doc_sync.py` (0 drift).

Not run: the test suite, `--cov`, `ci_rag_smoke.py`, or a live server;
nothing executable changed. Two claims are by reading only and were not
executed:
- the `reject_proposal` branch cannot fire;
- `sync/filters.py` currently gets its file mode from the umask.

## Limits and rollback

Name-count dead-code detection misses dead symbols whose names collide with
live ones. The 6-line pass covered only the core and shared modules, so 4-7
line repeats in channel and skill code appear only where the 8-line pass or a
reviewer caught them. Line counts are estimates from the ranges cited. Nothing
to roll back: the audit changes no tracked file other than adding this report.
