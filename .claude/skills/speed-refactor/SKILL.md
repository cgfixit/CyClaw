---
name: speed-refactor
description: Iterative speed optimization loop — continuously optimizes code for performance, measures every HTTP endpoint under repeatable test conditions after each change, and continues until every non-generation endpoint and module loads or runs in under 50 ms.
disable-model-invocation: true
---

# Speed Refactor Loop

Optimize the codebase for speed iteratively. After each significant change, measure the HTTP endpoints under identical, repeatable conditions. Continue until every non-generation endpoint and code module independently runs or loads in under 50 ms. The 50 ms gate covers the gate's own overhead; `POST /query` on a live Ollama path is bounded by the model (`local_llm.timeout_sec` 720, `max_tokens` 4096), so measure it only as far as the 503/`needs_confirm` path or with `mock_ollama.py`.

---

## Setup

```bash
PROJNAME=$(basename "$PWD")
TRACKER="/tmp/refactor-${PROJNAME}.md"
BASELINE_FILE="/tmp/speed-baseline-${PROJNAME}.json"
```

Initialize the tracker if it doesn't exist:

```bash
[ -f "$TRACKER" ] || cat > "$TRACKER" <<EOF
# Speed Refactor — $PROJNAME
Started: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
Target: every page and module < 50 ms

## Baseline
(run measurement before first change)

## Progress
EOF
```

---

## Measurement Protocol

All measurements must be taken under the same repeatable conditions every iteration. Do not compare across different machine states, load levels, or warmup counts.

### Server startup (cold)

```bash
# Kill any existing instance by pidfile, never `pkill -f` (it matches the
# invoking shell — cyclaw-gotchas), then start fresh and wait for /health.
D=.claude/skills/cyclaw-gotchas/driver.sh
bash $D stop 2>/dev/null
CYCLAW_API_KEY=smoke-test-key GROK_API_KEY=dummy bash $D serve
sleep 2   # fixed warm-up window — do not vary
```

By hand (no driver), the equivalent start is
`CYCLAW_API_KEY=smoke-test-key GROK_API_KEY=dummy python -m uvicorn gate:app --host 127.0.0.1 --port 8787 --no-proxy-headers &`
— keep `--no-proxy-headers`, which `gate._serve`, the Dockerfile and the
launchers all pass (`tests/test_gate.py` pins this recipe).

### Measure every endpoint

Run each endpoint 5 times and record the **median** (not mean — median is stable against outlier spikes):

```bash
measure() {
  local label="$1" method="$2" url="$3" data="$4"
  local t
  for i in 1 2 3 4 5; do
    if [ -n "$data" ]; then
      t=$(curl -s -o /dev/null -w "%{time_total}" -X "$method" "$url" \
          -H "Content-Type: application/json" -H "$AUTH" -d "$data")
    else
      t=$(curl -s -o /dev/null -w "%{time_total}" -H "$AUTH" "$url")
    fi
    echo "$t"
  done | sort -n | sed -n 3p | awk -v l="$label" '{ printf "%s median=%.0fms\n", l, $1*1000 }'
}

BASE="http://127.0.0.1:8787"
AUTH="Authorization: Bearer smoke-test-key"    # /soul is key-gated; harmless elsewhere
measure "GET /health"          GET  "$BASE/health"
measure "GET /index/status"    GET  "$BASE/index/status"
measure "GET /soul"            GET  "$BASE/soul"
measure "GET /static/terminal" GET  "$BASE/static/terminal.html"
measure "POST /query (vault)"  POST "$BASE/query" '{"query":"What is RRF?"}'
measure "POST /query (offline)" POST "$BASE/query" \
  '{"query":"What is CyClaw?","user_confirmed_online":false}'
```

Thirty requests fit under the 60/min per-IP rate limit; do not add runs
without spacing them. Teardown:

```bash
bash .claude/skills/cyclaw-gotchas/driver.sh stop
```

Record results in the tracker under `### Step N — Measurement`.

### Pass/fail gate

A step passes when **all** measured endpoints report median < 50 ms. If any endpoint is ≥ 50 ms, that endpoint is the target for the next optimization step.

---

## Loop Body

Repeat until all endpoints pass:

### 1. Identify the slowest path

From the latest measurement, pick the endpoint with the highest median. Profile it:

```bash
# Import-time cost (gate.py's __main__ starts the server, so profile the import,
# not the script)
GROK_API_KEY=dummy python3 -X importtime -c "import gate" 2>&1 | sort -t'|' -k2 -n | tail -25
# Per-request cost: drive the handler in-process under cProfile
GROK_API_KEY=dummy python3 -m cProfile -s cumulative -c \
  "from fastapi.testclient import TestClient; import gate; TestClient(gate.app).get('/health')" 2>&1 | head -40
```

Or add a quick timing probe inline:

```python
import time
t0 = time.perf_counter()
# ... suspect code ...
print(f"[TIMING] {time.perf_counter() - t0:.4f}s", flush=True)
```

Record the bottleneck and root cause in the tracker.

### 2. Plan one targeted change

Pick the single change with the highest expected speedup-to-risk ratio:

- **Cache** expensive repeated computations (ChromaDB client init, personality file read; BM25 scores are already `lru_cache`d in `retrieval/hybrid_search.py`)
- **Lazy-load** heavy imports that aren't needed on every request — but never move `gate.py`'s `_TELEMETRY_KILL` block or `apply_telemetry_kill()` below a heavy import (G1, `invariant-guard`)
- **Defer** work that doesn't need to happen in the hot path (log flushes; the audit write itself stays on the request path, I4)
- **Reduce I/O** — batch reads, avoid redundant disk hits per request
- **Tighten graph nodes** — short-circuit LangGraph nodes that re-derive already-known state

Do not change multiple things at once — it makes measurement ambiguous.

### 3. Execute

Make the targeted change. Keep the diff minimal and focused.

### 4. Measure

Re-run the full measurement protocol (all endpoints, 5 runs each, median). Compare against the previous step's numbers.

### 5. Smoke-test correctness

Speed wins are worthless if correctness breaks. Per CLAUDE.md §5, exercise the
changed path directly (`driver.sh probe`, or the endpoint you just measured
with its real response body checked), lint the touched files, and let CI run
the suite on the pushed draft. At most one targeted test file when nothing
else reaches the path:

```bash
ruff check --select E,F,I,B,C4,UP,S --ignore E501 <touched files>
GROK_API_KEY=dummy pytest tests/test_<module>.py -q --tb=short
```

`bash .claude/skills/CyClaw-Sandbox/smoke.sh` is a final, whole-loop pass
(it runs the full suite in its section F). If any check fails, **revert the
change** and pick a different approach.

If the change touched `gate.py`, `graph.py`, or `mcp_hybrid_server.py` (e.g.
caching, short-circuiting a LangGraph node, deferring an audit-log flush),
also run `python3 .claude/skills/invariant-guard/check_invariants.py` before
committing — a speed win that breaks I1 (RAG-first) or I4 (audit
convergence) is not a valid optimization.

### 6. Commit

Only commit if both the speed gate improved **and** smoke tests pass:

```bash
git add <files of this step>
git commit -m "[fix] - <what changed, measured improvement>"
```

Example: `[fix] - Cache the ChromaDB client at startup; /query median 210ms → 38ms`
(the tracked `commit-msg` hook refuses `perf:`-style subjects; `[rag]` fits
retrieval-path work).

### 7. Update tracker

```markdown
### Step N — Done
- Target: POST /query (was 210 ms median)
- Change: cached the ChromaDB PersistentClient instead of re-opening it per request
- Result: /query 38 ms, /health 4 ms, /soul 6 ms, /static 3 ms — ALL PASS ✓
- Verified: probe + tests/test_rag_integration.py; CI green
- Commit: abc1234
```

Loop back to **Identify the slowest path**.

---

## Stopping Criteria

Stop when the measurement run shows **every endpoint** at median < 50 ms for **two consecutive iterations** (confirms the result isn't a one-off).

Append a `## Final State` section to the tracker:

```markdown
## Final State
Completed: <timestamp>
All endpoints < 50 ms for 2 consecutive measurement runs.

| Endpoint              | Step 1 (ms) | Final (ms) |
|-----------------------|-------------|------------|
| GET /health           | 12          | 3          |
| GET /index/status     | 9           | 3          |
| GET /soul             | 45          | 7          |
| GET /static/terminal  | 8           | 2          |
| POST /query (vault)   | 340         | 41         |
| POST /query (offline) | 280         | 35         |
```

---

## Notes

- **Never vary warmup time** between runs — the 2 s sleep must be constant or measurements are incomparable.
- **Median over mean** — a single GC pause or cold-cache miss inflates mean; median is stable.
- **Revert if correctness breaks** — a 50 ms page that returns wrong data is worse than a 200 ms page that returns correct data.
- **Module-level load time counts** — if `import gate` takes 300 ms, that's a cold-start problem worth fixing even if per-request latency is fast.
- **`{projectname}`** in tracker/baseline paths is `basename $PWD`, e.g. `CyClaw` → `/tmp/refactor-CyClaw.md`.
- **Deferring audit-log flushes out of the hot path must not move them past `audit_logger`/`END`** in the graph — that breaks I4 (audit convergence). Check with `invariant-guard`, not just the probe.
- **Never "optimize" `retrieval/embeddings.py`'s `EMBED_DEVICE = "cpu"`** toward `mps`/GPU auto-detection; the pin is deliberate (PR #734, ranking regression on Apple Silicon).
