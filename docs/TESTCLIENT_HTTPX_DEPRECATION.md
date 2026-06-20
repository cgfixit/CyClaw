# Tech Note — `StarletteDeprecationWarning` in the test suite (httpx / TestClient)

**Status:** informational · no runtime impact · action required before a future Starlette major
**Filed:** 2026-06-19
**Applies to:** `starlette==1.3.1`, `httpx==0.28.1`, `fastapi==0.137.2` (current pins)

---

## Symptom

Every test run that constructs a `TestClient` emits this warning:

```
.../site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning:
  Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa
```

It is raised once per session (at import of `fastapi.testclient`, which re-exports
`starlette.testclient`). It does **not** fail any test — all 98 tests pass — but it is
noise on every `pytest` invocation, including CI.

### Where the TestClient is used

- `tests/test_gate.py:13` — `from fastapi.testclient import TestClient` (gateway integration tests)
- `tests/test_security.py:99,140` — `from fastapi.testclient import TestClient` (security/CORS tests)

These are the only consumers. The warning is purely a **test-time** concern — `httpx` is used
at runtime by `llm/client.py` for LM Studio / Grok calls, but that path does not touch
`starlette.testclient` and is unaffected.

---

## Why it happens

Starlette's `TestClient` is built on top of `httpx`. Starting in the Starlette 1.x line, the
project began migrating its test client onto the **`httpx2`** distribution (the `httpx` 2.x
rewrite, published separately on PyPI as the `httpx2` package). To steer users ahead of a hard
cutover, `starlette.testclient` now emits a `StarletteDeprecationWarning` whenever it detects the
classic `httpx` (1.x / 0.x line) installed instead of `httpx2`.

We currently pin:

```
httpx==0.28.1        # requirements.txt — classic httpx, 0.x line
starlette==1.3.1     # pulled transitively via fastapi==0.137.2
```

`httpx==0.28.1` is the classic line, so the warning fires. `httpx2` exists on PyPI
(`2.0.0b1 … 2.4.0` available at time of writing).

---

## Impact assessment

| Horizon | Effect |
|---|---|
| **Now** | None functional. Cosmetic warning on every test session. |
| **When Starlette removes the `httpx`-1.x shim** (a future major) | `TestClient` will fail to import / construct unless `httpx2` is present. CI test collection breaks. |

This is a "fix before the next Starlette major" item, not an emergency. It is tracked here so the
warning is not silently ignored until it becomes a hard break.

---

## Options (do **not** apply blindly — see recommendation)

1. **Do nothing yet (current state).** Acceptable while the shim exists. Risk: forgetting until a
   Starlette bump turns the warning into an `ImportError`.

2. **Silence the warning only.** Add a filter so CI logs stay clean without changing deps:

   ```ini
   # pytest.ini / pyproject.toml [tool.pytest.ini_options]
   filterwarnings =
       ignore:Using `httpx` with `starlette.testclient` is deprecated:DeprecationWarning
   ```

   Pros: zero dependency churn. Cons: hides the signal; the underlying break still lands later.

3. **Migrate the test client to `httpx2`.** Add `httpx2` to the test/dev requirements so
   `starlette.testclient` picks it up. This is the direction Starlette is steering toward.
   Caveats before doing this:
   - `httpx2` is a **major rewrite**; its request/response API differs from classic `httpx`.
     The two are **not** drop-in interchangeable.
   - Runtime code (`llm/client.py`) uses classic `httpx==0.28.1`. Installing both `httpx` and
     `httpx2` side by side is supported (different import names / distributions), but it should be
     verified that the resolver keeps runtime on classic `httpx` while the test client uses
     `httpx2`.
   - Any direct `httpx`-typed assertions in tests (status codes, JSON bodies) should be re-checked
     against the `httpx2` response surface.

4. **Drop `TestClient` entirely** in favour of an ASGI transport driven directly through `httpx`
   (`httpx.ASGITransport` + `httpx.AsyncClient`). Removes the Starlette-testclient dependency and
   the warning, at the cost of rewriting the two test files to async. Larger diff; only worth it if
   the suite is moving async anyway.

---

## Recommendation

Short term: **Option 2** (filter the warning) to keep CI logs clean and intentional, paired with a
tracking reference to this note so the deprecation is not lost.

Before the next Starlette **major** bump (watch dependabot PRs that move `starlette` past `1.x`):
**Option 3** — add `httpx2` for the test client and re-validate the two consuming test files. Treat
the Starlette major bump as the trigger; do not migrate speculatively, since `httpx2` is still on
beta/early releases and its API may shift.

Do **not** "fix" this by bumping the runtime `httpx==0.28.1` pin — that pin serves `llm/client.py`,
not the test client, and changing it has nothing to do with the warning.

---

## Reproduction

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install torch==2.4.1+cpu --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt pytest
GROK_API_KEY=dummy pytest tests/test_gate.py -q -W default 2>&1 | grep -i deprecat
# -> StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
```
