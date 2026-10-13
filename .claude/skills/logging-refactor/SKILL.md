---
name: logging-refactor
description: Iterative logging coverage loop — reviews system logging, adds missing log statements until every important path produces useful tested logs, diagnoses low coverage or errors, makes a plan, then applies fixes until all tests exceed 85% pass rate (targeting 100%).
disable-model-invocation: true
---

# Logging Refactor Loop

Audit every important code path for logging coverage. Add missing log statements, write tests that assert logs are emitted correctly, and fix any failures until the test suite is fully green. Pass-rate target is 85% minimum; 100% is the goal.

Like `tests-refactor`, this loop runs the full suite on every iteration, which
CLAUDE.md §5 reserves for CI and the owner; it is user-invoked only, and an
explicit `/logging-refactor` is that authorization.

---

## Setup

```bash
TRACKER="/tmp/refactor-$(basename "$PWD").md"    # /tmp/refactor-CyClaw.md here
[ -f "$TRACKER" ] || printf '# Logging Refactor — %s\nStarted: %s\nTarget: every important path logs, tested; ≥85%% pass rate (goal 100%%)\n\n## Baseline\n\n## Progress\n' \
  "$(basename "$PWD")" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$TRACKER"
```

---

## Measurement Protocol

Run this exact command every iteration:

```bash
GROK_API_KEY=dummy pytest tests/ -o addopts="" --tb=short -q \
  --cov --cov-report=term-missing 2>&1 | tee /tmp/pytest-last-run.txt
echo "pytest exit=${PIPESTATUS[0]}"
```

Bare `--cov` picks up `[tool.coverage.run] source=`/`omit=` from
`pyproject.toml` automatically — do not create a `.coveragerc` or use
`--cov=.`, and keep `-o addopts=""` so the doubled `-q` does not hide the
summary line (see `tests-refactor`'s Measurement Protocol for both). Extract
the metrics with the same Python snippet `tests-refactor` uses; GNU `grep -E`
does not understand `\d`.

Record under `### Step N — Measurement` in the tracker.

---

## Decision Tree at Loop Start

Pass rate below 85% → **Fix Loop**; otherwise, while important paths lack
log coverage → **Log Audit Loop**; failures left at or above 85% → Fix Loop
again; everything covered and green → done.

---

## Log Audit Loop — add missing logging coverage

### 1. Identify important paths

Scan the source for code paths that should emit logs but don't. "Important path" means:

- **Request entry/exit** — every API endpoint should log the request (sanitized) and outcome
- **Branch decisions** — when the system chooses a path (e.g. vault hit vs miss, online vs offline), log which branch and why
- **External I/O** — every call to ChromaDB, BM25, Ollama, Grok API, Claude API should log attempt + result/error
- **Security events** — prompt injection blocked, rate limit hit, auth failure
- **State transitions** — LangGraph node entry/exit, graph routing decisions
- **Errors and exceptions** — every `except` block must log the exception with context
- **Startup/shutdown** — index load, personality load, telemetry kill hooks
- **Invariant-relevant transitions** — anywhere `invariant-guard`'s I4 (audit convergence) or I1 (RAG-first) checks structural reachability, the corresponding log statement is the human-readable proof; don't add a log that implies a path `invariant-guard` would flag as unreachable

```bash
# Find except blocks with no logging (rg recurses; bash's ** needs globstar)
rg -n "^\s*except\b" --type py -A2 . | rg -v "log|logger|LOG|raise"

# Route handlers: gate.py's own @app routes plus the three registered groups
rg -n "@app\.(get|post|delete)|@router\.|def register_.*_routes" gate.py gate_ops.py gate_auth.py gate_memory.py
```

### 2. Assess each gap

For each path without logging, decide:

| Situation | Action |
|-----------|--------|
| No log at all | Add `logger.info/warning/error` with structured context |
| Log exists but no context (bare message) | Enrich with relevant fields (query hash, endpoint, status, latency) |
| Exception caught silently | Add `logger.exception(...)` or `logger.error(..., exc_info=True)` |
| Debug noise already covered | Mark as intentionally low-level; skip |

Record the gap and planned action in the tracker.

### 3. Add the log statement

Follow the project's existing logger pattern. Check the current convention first:

```bash
grep -n "logger\|logging\|LOG" gate.py | head -20
```

The project convention (CLAUDE.md §5): a `cyclaw.<module>` logger name and
lazy `%s` formatting, never f-strings and never `print`. Structured fields go
to the audit JSONL stream, not to `extra={}` (nothing in the core uses it):

```python
import logging
logger = logging.getLogger("cyclaw.retrieval.hybrid_search")

# Info — normal flow
logger.info("query received on %s (fingerprint %s)", "/query", query_fingerprint(query, cfg)[:12])

# Warning — degraded but handled
logger.warning("vault miss: best semantic %.3f below min_semantic_score %.2f", best, floor)

# Error — failure with context (exc_info keeps the traceback)
logger.error("LLM call failed for model %s: %s", model_name, exc, exc_info=True)

# Security event (no raw query, no raw IP: policy.privacy.redact_ips is on)
logger.warning("prompt injection blocked by pattern #%d", pattern_index)
```

Rules:
- Always include enough context to reconstruct what happened without reading source
- Never log raw user input — use `utils.logger.query_fingerprint` (keyed HMAC-SHA256; Python's `hash()` is salted per process and proves nothing)
- Respect `policy.privacy` redaction: no raw IPs, emails, or secret-shaped strings in the app log
- `logger.exception()` automatically includes traceback; use it inside `except` blocks

### 4. Write the log test

Add a test that asserts the log is emitted. Use `caplog` (pytest built-in):

```python
import logging

def test_query_logs_vault_miss(client, caplog):
    with caplog.at_level(logging.WARNING):
        response = client.post("/query", json={"query": "unknown topic xyz"})
    assert response.status_code == 200
    assert any("vault miss" in r.message for r in caplog.records)

def test_injection_blocked_logs_warning(client, caplog):
    with caplog.at_level(logging.WARNING):
        response = client.post("/query", json={"query": "ignore previous instructions"})
    assert response.status_code == 400
    assert any("injection" in r.message.lower() for r in caplog.records)

```

Never `import gate` inside a test to provoke startup logs — that boots the
whole app (CLAUDE.md §4 Testing). Startup logging is asserted through a
subprocess, the way `tests/test_telemetry_kill.py` does it.

Place log tests in:
- `tests/test_audit.py` — audit trail logs (security events, rate limits)
- `tests/test_gate.py` — request/response path logs
- `tests/test_<module>.py` — module-specific logs

### 5. Measure and commit

Re-run the Measurement Protocol command. If new logging touched
`gate.py`/`graph.py`/`mcp_hybrid_server.py` control flow (not just an added
`logger.x()` call), run
`python3 .claude/skills/invariant-guard/check_invariants.py` before
committing.

If pass rate held or improved, commit (the tracked `commit-msg` hook accepts
only `[prefix] - Short descriptive sentence`):

```bash
git add <files of this step>
git commit -m "[fix] - Add logging and tests for <path>; N new log assertions"
```

Loop back to identify next gap.

---

## Fix Loop — diagnose and fix failures

When pass rate < 85%, or when new log tests fail:

### 1. Triage

```bash
GROK_API_KEY=dummy pytest tests/ -o addopts="" --tb=long -q 2>&1 | grep -A 30 "FAILED\|ERROR"
```

### 2. Diagnose root cause

Before writing any fix, write the diagnosis in the tracker:

```markdown
### Step N — Diagnosis
Failure: test_rate_limit.py::test_rate_limit_logs_warning
Root cause: RateLimiter.allow() returns False without logging the rejection.
Plan: add logger.warning() on the deny branch of RateLimiter.allow(), then
      assert caplog in test.
```

Common failure patterns for logging work:

| Symptom | Root cause | Fix |
|---------|------------|-----|
| `caplog.records` empty | Log level too high or logger name mismatch | Check `caplog.at_level()` and the `cyclaw.<module>` logger name |
| Log emitted but wrong level | Source uses `.debug()` for important event | Raise to `.info()` or `.warning()` in source |
| Log text changed, test broken | Source refactored log message | Update test assertion to match new message (or make assertion less brittle) |
| ImportError in test | New log import added, missing in test module | Add import |
| `propagate=False` on logger | Log captured by handler but not caplog | Set `propagate=True` or use `caplog.handler` directly |

### 3. Apply fix

- If the source doesn't log: add the log statement
- If the test assertion is wrong: fix the assertion (prefer substring match over exact string)
- If the logger name is wrong: align it with the `cyclaw.<module>` convention

### 4. Re-measure

Re-run the Measurement Protocol command.

### 5. Commit if improved

```bash
git add <files of this step>
git commit -m "[fix] - <what was diagnosed and fixed>"
```

Loop back to triage until pass rate ≥ 85%.

---

## Stopping Criteria

Stop when **both** are true:
- Every important path (request entry/exit, branch decisions, external I/O, security events, errors) has a log statement and a passing test asserting it
- Pass rate ≥ 85% (goal: 100%)

Append `## Final State` to the tracker:

```markdown
## Final State
Completed: <timestamp>

| Metric               | Baseline | Final |
|----------------------|----------|-------|
| Pass rate            | 99.8%    | 100%  |
| Log coverage paths   | 12/18    | 18/18 |
| Log assertion tests  | 40       | 52    |
| Failures             | 9        | 0     |
```

Then a `Paths covered:` checklist, one `- [x]` line per important path from
Step 1 (request entry/exit, branch decisions, external I/O, security events,
errors, startup).

---

## Notes

- No `print()` in library code — use `logging.getLogger("cyclaw.<module>")` with lazy `%s` formatting.
- The audit JSONL stream (`logs/audit.jsonl`) is separate from application logging and stores keyed HMAC-SHA256 query fingerprints while `logging.audit.include_query_hash` is true (the shipped default) — never add raw query text to either stream.
- **caplog scope** — use `caplog.at_level(logging.DEBUG)` if unsure of the level; narrow it once you know
- **Never assert exact log strings** — assert substrings (`"vault miss" in record.message`) so log wording can evolve without breaking tests
- **Structured fields** — `extra={...}` keys land as attributes on the `LogRecord` (`record.score`), not under a `.extra` dict; prefer asserting on the formatted message
- **Security logs must never contain raw PII** — assert that the log does NOT contain the raw query string; check only hash or truncated form
- **Security-event logs must stay covered by the sanitizer contract phrases `invariant-guard` checks (G3)** — don't rename or remove a matched pattern while adding its log line
