---
name: tests-refactor
description: Iterative test coverage and quality loop — adds tests under tests/ until coverage reaches 100%, diagnoses and fixes failing tests, and continues until all test results exceed 85% pass rate (targeting 100%). Use when asked to improve test coverage, fix failing tests, or get the test suite green.
disable-model-invocation: true
---

# Tests Refactor Loop

Bring the test suite to full health: add tests until coverage hits 100%, diagnose every failure, and apply fixes until all tests pass. The pass-rate target is 85% minimum; 100% is the goal. The CI gate is `fail_under = 80` in `pyproject.toml`; 100% is this loop's aspiration, not a number anything enforces.

This loop runs the full suite with coverage on every iteration. CLAUDE.md §5
reserves that run for CI and the owner, so this skill is user-invoked only: an
explicit `/tests-refactor` is the owner asking for it. Do not run the loop's
measurement command from any other skill or task.

---

## Setup

```bash
TRACKER="/tmp/refactor-$(basename "$PWD").md"    # /tmp/refactor-CyClaw.md here
[ -f "$TRACKER" ] || printf '# Tests Refactor — %s\nStarted: %s\nTarget: 100%% coverage, ≥85%% pass rate (goal 100%%)\n\n## Baseline\n\n## Progress\n' \
  "$(basename "$PWD")" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$TRACKER"
```

---

## Measurement Protocol

Run this exact command every iteration — do not vary flags between runs:

```bash
GROK_API_KEY=dummy pytest tests/ -o addopts="" --tb=short -q \
  --cov --cov-report=term-missing 2>&1 | tee /tmp/pytest-last-run.txt
echo "pytest exit=${PIPESTATUS[0]}"
```

`-o addopts=""` matters: `pyproject.toml` already sets `addopts = "-q
--tb=short"`, and a second `-q` makes `-qq`, at which level pytest drops the
final `N passed` line (cyclaw-gotchas). Bare `--cov` (no argument) picks up
`[tool.coverage.run] source=`/`omit=` from `pyproject.toml`, which is the
same source list CI measures through its explicit `--cov=<pkg>` flags (one per
entry; `tests/test_ci_coverage_flag_contract.py` keeps them in step). **Do not
create a `.coveragerc`** and do not use `--cov=.`: a blanket `--cov=.` would
include the `agentic/{fsconnect,netconnect}/*` paths that
`omit=` deliberately excludes, so the loop would chase a coverage % that
doesn't match the real gate.

### Extract key metrics after each run

```bash
# Pass rate (GNU grep -E has no \d; skipped tests count neither way)
read -r PASSED FAILED ERRORS < <(python3 - /tmp/pytest-last-run.txt <<'EOF'
import re, sys
tail = open(sys.argv[1]).read()[-2000:]
def n(k): m = re.search(rf"(\d+) {k}", tail); return int(m.group(1)) if m else 0
print(n("passed"), n("failed"), n("error"))
EOF
)
TOTAL=$((PASSED + FAILED + ERRORS))
PASS_RATE=$(python3 -c "print(f'{$PASSED*100/max($TOTAL,1):.1f}')")

# Coverage
COVERAGE=$(grep "^TOTAL" /tmp/pytest-last-run.txt | awk '{print $NF}')

echo "Pass rate: ${PASS_RATE}% (${PASSED}/${TOTAL}) | Coverage: ${COVERAGE}"
```

Record both metrics in the tracker under `### Step N — Measurement`.

---

## Decision Tree at Loop Start

Read the current metrics: pass rate below 85% → **Fix Loop** first; at or
above 85% with coverage short of 100% → **Coverage Loop**; coverage at 100%
with failures left → Fix Loop again; both at 100% → done.

---

## Fix Loop — bring pass rate to ≥ 85%

Repeat until pass rate ≥ 85%:

### 1. Triage failures

```bash
GROK_API_KEY=dummy pytest tests/ -o addopts="" --tb=long -q 2>&1 | grep -A 20 "FAILED\|ERROR"
```

Group failures by root cause — don't fix them one-by-one if they share a common cause:
- Import errors → missing dependency or broken module path
- Fixture errors → missing or misconfigured pytest fixtures
- AssertionError → logic bug in source or wrong test expectation
- Exception in setup/teardown → server state leak between tests

### 2. Identify root cause

For each failure group, read the traceback fully. Common patterns in this project:

- `GROK_API_KEY` not set → ensure env var is set in test or conftest
- A test touching a real ChromaDB / BM25 index → it must not; `tests/conftest.py` mocks the embedder and the external services, and `tests/ci_rag_smoke.py` is the only real-index check (its own CI step)
- LangGraph node error → mock the LLM call (`MockLocalLLM`); don't require Ollama in tests
- Rate-limit state leaking between tests → the `client` fixture hands each test file its own loopback IP; a test that builds its own `RateLimiter` must `close()` it
- Personality file missing → `PersonalityManager._load_soul` self-heals; a test that asserts a crash here is wrong
- `import gate` at a test module's top level → full app init; use a subprocess or module-level patching (CLAUDE.md §4 Testing)

### 3. Fix

Apply the minimal fix:
- If it's a source bug: fix the source, not the test
- If it's a test bug (wrong expectation, brittle assertion): fix the test
- If it's a missing fixture: add to `tests/conftest.py`
- If it's a missing mock: add `unittest.mock.patch` for external I/O

### 4. Re-measure

Run the full measurement command. Record new pass rate and coverage.

### 5. Commit if improved

```bash
git add <files of this step>
git commit -m "[fix] - <root cause fixed; N tests now passing>"
```

The tracked `commit-msg` hook accepts only `[prefix] - Short descriptive
sentence` (CLAUDE.md §5); `test(fix):`-style subjects are refused.

Loop back to triage until pass rate ≥ 85%.

---

## Coverage Loop — bring coverage to 100%

Once pass rate ≥ 85%, shift to adding missing coverage:

### 1. Find uncovered lines

```bash
grep -E "^[a-z_/]+\.py +[0-9]+ +[0-9]+ +[0-9]+% +[0-9]" /tmp/pytest-last-run.txt \
  | sort -k4 -n | head -20     # lowest-covered modules first, from the last run
```

Pick the module with the lowest coverage percentage first.

### 2. Read the uncovered lines

For each uncovered block, identify **what scenario** would execute it:
- Error handling branch → write a test that injects the error condition
- Edge-case input → write a test with that input
- Conditional path → write a test that satisfies the condition
- Dead code → if genuinely unreachable, add `# pragma: no cover` with a comment explaining why

### 3. Write the test

Add tests to the appropriate file under `tests/`. Match existing naming conventions:

```
tests/test_gate.py          ← API endpoint tests
tests/test_sanitizer.py     ← input sanitization
tests/test_security.py      ← security/injection checks
tests/test_rate_limit.py    ← rate limiting logic
tests/test_audit.py         ← audit logging
tests/test_personality.py   ← soul/personality system
```

If no file fits, create `tests/test_<module_name>.py`. One behavior per test,
a one-sentence docstring, arrange/act/assert, and the shared `client` fixture
for anything that hits a route.

### 4. Re-measure

Run full measurement. Check both pass rate and coverage. If a new test reveals a source bug, fix it (don't skip the test). If the fix required changing source code (not just adding a test) and it touched `gate.py`/`graph.py`/`mcp_hybrid_server.py`/`utils/`, also run `invariant-guard` and `config-guard`.

### 5. Commit if coverage improved

```bash
git add tests/
git commit -m "[fix] - Add tests for <module>; coverage N% → M%"
```

Loop back to find next uncovered lines.

---

## Stopping Criteria

Stop when **both** are true:
- Pass rate ≥ 85% (goal: 100%)
- Coverage = 100%

If pass rate is exactly 85–99% and coverage is 100%, run one more Fix Loop pass — the remaining failures are known and worth fixing now.

Append `## Final State` to the tracker:

```markdown
## Final State
Completed: <timestamp>

| Metric      | Baseline | Final  |
|-------------|----------|--------|
| Pass rate   | 98.1%    | 100%   |
| Coverage    | 84%      | 91%    |
| Tests total | 5263     | 5310   |
| Failures    | 7        | 0      |
```

---

## conftest.py

Use the fixtures `tests/conftest.py` already provides rather than inventing
new session-scoped ones: `client` (a function-scoped `TestClient` over the
mocked gateway, one loopback IP per test file so rate-limit state cannot
leak), `test_config` (a deepcopy — `test_conftest_fixtures` guards that), and
the autouse mocks for the embedder, Ollama, Grok and Claude. Nothing builds a
real index and nothing starts a live service (CLAUDE.md §6 "Test").

---

## Notes

- **Fix source bugs, not tests** — if a test correctly describes expected behavior and the source is wrong, fix the source.
- **No `# pragma: no cover` without justification** — only mark code unreachable if you can prove it (e.g., defensive else on an exhaustive enum).
- **Don't mock what you can control** — mock external I/O (Ollama, Grok API, Claude API, disk), not internal logic.
- **Pass rate formula**: `passed / (passed + failed + error) * 100` — skipped tests do not count toward or against the rate.
- Coverage gate is 80% `fail_under` in `pyproject.toml` — do not lower it to make the loop exit early.
