# Metrics reader refactor — 2026-09-11

Base: `1ab36ad6b391f185f585668cd149a0942b5cf0eb`. One behavior-preserving cleanup on `codex/metrics-jsonl-reader`; PR base `main`, no merge predecessor.

## Ponytail audit and selection

Source-line estimates below are possible cuts, not a recommendation to apply every candidate. Only the metrics reduction was implemented and measured.

- `shrink:` Four JSONL parser loops in `metrics.py` become one streaming reader. **70 source lines removed**, no dependencies added; selected.
- `shrink:` Duplicate database connection lifecycle in `utils/authn_store.py` and `utils/personality_db.py`: approximately 35 lines. Deferred; distinct DSN precedence, environment isolation and warning contracts require separate storage verification.
- `shrink:` Repeated canonical config-path resolution across indexer, cache cleaner, sanitizer, metrics and logger: approximately 30 lines. Deferred; import coupling and per-module test roots complicate the cut. Lexical-only auth paths are excluded.
- `shrink:` Artifact-lock release duplicates registry release: approximately 21 lines in `agentic/harness_optimizer/patching.py`. Deferred as a separate concern; acquisition behavior differs.
- `shrink:` One-use `suppress_attr_error` class in `agentic/sqlconnect/client.py`: approximately 11 lines. Inline exception handling must preserve exact-type suppression; stdlib `suppress` has broader behavior.
- `shrink:` Identical disabled-result branches in `memory/consolidation.py`: approximately 4 lines. Deferred as low-value churn.

Dormant guardrail/Qwen scaffolds are explicitly retained by an owner decision. Similar-looking same-origin handlers have different response/security contracts. Neither warrants automatic deletion. Potential total: approximately 171 source lines and zero dependencies.

## Preserved contracts

`iter_events(audit_file=...)`, `iter_spend(spend_file=...)`, `compute_audit_integrity` and `summarize_audit` keep their interfaces and return shapes. The private reader streams JSON objects, optionally updating integrity counters during that same pass. Missing files yield zero records/counters. Blank lines do not count as corruption; malformed JSON and non-object JSON do. Raw-query and hash counters continue to test key presence. File-access and UTF-8 errors still propagate.

| Invariant | Before and after |
|---|---|
| I1 / I2 | Retrieval entry and graph routing unchanged |
| I3 | External-provider gates unchanged |
| I4 | Audit writers and convergence unchanged; only evidence readers consolidated |
| I5 | Soul write governance unchanged |
| I6 | No out-of-band imports added; telemetry kill remains before imports |

## Verification

Local verification uses an isolated Python 3.12 environment with the repository's macOS runtime/test pins. The initial sandbox-exec failure was the outer execution sandbox; the installer discovery failure was an inactive venv on PATH. Both disappeared when running native checks with the venv activated, without changing application code or tests.

- Clean baseline: 4,785 passed, 78 skipped. Focused metrics/caller tests: 70 before, 72 after.
- Differential check: 251 synthetic JSONL inputs across four public APIs; keyword compatibility and UTF-8 error propagation preserved. Independent review also checked iterator cancellation closes the file.
- Full post-change CI coverage command: 4,787 passed, 78 skipped; 89.12% total coverage (80% required), metrics 92%. The skip list records platform-only and optional-service gaps.
- Both Ruff sets, byte compilation, 46 invariant checks, doc-sync, dependency guards, 48 injection probes and strict telemetry guard pass. Config guard retains the documented hybrid-posture warning.
- Actionlint and offline Zizmor pass. Wheel builds; all seven entry points resolve, and packaged metrics bytes match source. `pip check` passes.
- Real ChromaDB/BM25/RRF smoke: 4/4 before and after. Native macOS API smoke passes against a disposable gateway on port 8797 and real Ollama.
- Computer Use opened Chrome, submitted a query to `qwen3.8:27b-mlx`, and expanded five local sources. The refactored runtime answered in 14.075 seconds. Browser injection rejection and authenticated Soul loading also passed on the baseline.
- Changed `/audit/summary` route: missing-key rejection, authenticated aggregation, two malformed synthetic records counted, blank lines ignored, no raw-query/hash-integrity violations. CLI metrics reports the same corruption count.

The runtime copy matches all 178 tracked Python files outside `tests/`, `docs/`, `.claude/`, and `.codex/`. Its only configuration overrides are a spare loopback port and disabled external providers; indexes, logs and state are disposable. Metrics SHA-256: `8447bdcaa333a8384c5e159b664a74c6da284baf60b0d6cbfded60f34b327941`.

## Limits and rollback

Mypy remains advisory: 31 existing file errors after the refactor, versus 33 before, including missing PyYAML stubs; the new reader has no reported error. Local execution is macOS, not native Windows/Linux, PostgreSQL integration, NeMo-engine acceptance or a Docker build. Hosted checks provide those separate CI results where configured. The all-in-one sandbox script was not rerun because it duplicates the suite and launches over the operator's Ollama port; its relevant runtime checks were exercised separately. No claim is made that every optional service was live-tested. Reverting this single PR restores the prior readers; no data migration is involved.

## Browser evidence

User-provided screenshot from baseline verification: a real local-model answer with five sources, followed by HTTP 400 `PROMPT_INJECTION_BLOCKED`. The separate post-refactor browser run is recorded above.

![Local RAG answer and rejected prompt injection](../screenshots/2026-09-11-local-rag-and-injection-verification.png)
