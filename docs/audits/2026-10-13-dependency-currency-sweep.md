# Dependency sync audit — 2026-10-13

**Scope:** `/verify-deps` against `origin/main` @ `6519135`, run from a Linux
cloud sandbox (Python 3.12 venv, pip only). Reports only; **no pin was
changed**. `dep-guard`'s Guardrails and CLAUDE.md §7 class a runtime bump as
ask-first, and the hashed `locks/` for macOS can only be regenerated on arm64
macOS (`scripts/refresh-runtime-lock.sh`), so a bump PR is an owner decision,
not a sweep output.

## Summary

```
Verify Deps: 47 packages checked | 25 behind latest | 2 packages with advisories on the pin (both already documented in SECURITY.md) | 0 install-surface failures
dep-guard:            PASS (D1-D11, 0 failures, 0 warnings)
requirements.txt drift: none (requirements.txt + requirements-test.txt <-> constraints.txt agree)
Env drift (E1-E7):    0 failure(s), 0 warning(s) - no E3 undeclared imports
Lock contract:        scripts/check_lock_contract.py passed
Lock <-> manifest:    all 25 lock files agree with constraints.txt on every shared pin (+cpu local tag ignored)
Install surfaces dry-run: local-dev=unverified* legacy-CI=unverified* Dockerfile=unverified* hashed-locks(runtime)=conditional** hashed-locks(test)=PASS wheel-build=PASS conda=not dry-run-verified compose=PASS (docker compose config --quiet)
Currency:             19 current | 17 runtime bump candidates (needs review) | 2 dev-tool bump candidates | 9 documented or compatibility-blocked exceptions
Verdict:              no fixes applied; findings for review below
```

\* `download.pytorch.org` is denied by this sandbox's egress proxy, so every
surface that must resolve `torch==2.13.0+cpu` from the CPU index fails with the
documented "unreachable CPU index" class (`ProxyError 403`, then pip's
`ResolutionImpossible: sentence-transformers depends on torch>=2.2 / constraint
torch==2.13.0+cpu`). Per `.claude/skills/verify-deps/SKILL.md` Step 4 that is
environment-local and recorded as **unverified**, not failed. The hashed test
lock (`--require-hashes`) and the hatchling wheel build resolved cleanly, and
the Dockerfile's `--require-hashes` path is the same runtime lock.

\*\* `locks/requirements-lock-linux.txt` deliberately omits `torch` (the torch
lock installs it first) while pinning `sentence-transformers`, which depends on
it. The dry-run here passed only because the sandbox venv already carried a
torch 2.13.0 build (a CUDA wheel, not the `+cpu` one), which pip accepted as
satisfying the dependency. That proves the lock's own hashes and pins resolve
against an installed torch; it does not prove the documented two-step install
from an empty venv, which needs the proxy-blocked CPU index. Recorded as
**conditional**, not PASS.

## Install surface dry-runs

| Surface | Command | Result |
|---|---|---|
| Local dev | `pip install --dry-run -e . -c constraints.txt --extra-index-url https://download.pytorch.org/whl/cpu` | unverified (CPU index denied by proxy) |
| Legacy / CI | `pip install --dry-run -r requirements.txt -r requirements-test.txt -c constraints.txt` | unverified (same cause: constraints pin `torch==2.13.0+cpu`) |
| Dockerfile step 1 | `pip install --dry-run torch==2.13.0+cpu --index-url https://download.pytorch.org/whl/cpu` | unverified (proxy) |
| Hashed Linux runtime lock | `pip install --dry-run --require-hashes -r locks/requirements-lock-linux.txt` | **conditional** — resolved only because torch 2.13.0 was already installed in the venv (see \*\* above); not a from-empty proof |
| Hashed Linux test lock | `pip install --dry-run --require-hashes -r locks/requirements-test-lock-linux.txt` | **PASS** |
| Hashed torch lock | `pip install --dry-run --require-hashes --no-deps -r locks/requirements-torch-lock-linux.txt --index-url …/whl/cpu` | unverified (proxy) |
| Wheel build | `pip wheel --no-deps -w <scratch> .` | **PASS** (hatchling `[tool.hatch.build]` packages resolve) |
| Compose render | `docker compose config --quiet` | **PASS** |
| Conda | `environment.yml` | not dry-run-verified (no conda in the sandbox); `dep-guard` D9 confirms its 24 cross-pinned packages agree with the pip manifests |

## Advisories on pinned versions (PyPI `vulnerabilities` field)

| Package | Pinned | Advisories reported | Status |
|---|---|---|---|
| `chromadb` | 1.5.9 | CVE-2026-45829, -45830, -45831, -45833 (GHSA-2wm9-hf6c-p5cr, -36p7-vc44-83pf, -f4j7-r4q5-qw2c, -xph7-9rjv-w5fr) | All four already listed and risk-accepted in `SECURITY.md` for the embedded `PersistentClient`-only posture; no newer release (1.5.9 is latest). Do not switch to the HTTP client or file a fix PR. |
| `nltk` | 3.10.3 | CVE-2026-81726 (GHSA-8mgp-746c-j5xp) | Already documented in `SECURITY.md`; 3.10.3 is the latest release, so no upstream fix exists yet. `retrieval/stemmer.py` caps tokens at 256 chars as defense in depth for the sibling CVE-2026-81722. |

No other pinned package reports an advisory. `api.osv.dev` is blocked by the
sandbox proxy, so this is the PyPI advisory feed only (it mirrors the PyPA
advisory database, including GHSA and PYSEC ids).

## Currency table

Pinned column is `constraints.txt` (falling back to `pyproject.toml`); latest
is PyPI `info.version` on 2026-10-13. Classes follow the `verify-deps` table.
Conda-only names (`pytorch`, `python-tzdata`) are omitted.

| Package | Pinned | Latest | Class | Note |
|---|---|---|---|---|
| `bandit` | 1.9.4 | 1.9.4 | current |  |
| `cel-python` | 0.5.0 | 0.5.0 | current |  |
| `chromadb` | 1.5.9 | 1.5.9 | documented exception | risk-accepted CVE set (SECURITY.md); embedded PersistentClient only |
| `deepagents` | 0.6.12 | 0.7.24 | bump candidate (runtime, needs review) |  |
| `fastapi` | 0.141.1 | 0.143.0 | bump candidate (runtime, needs review) |  |
| `google-re2` | 1.1.20251105 | 1.1.20251105 | current |  |
| `httpx` | 0.28.1 | 0.28.1 | current |  |
| `huggingface-hub` | 1.32.0 | 2.2.0 | compatibility-blocked exception | `sentence-transformers==6.1.0` requires `huggingface-hub<2.0.0,>=1.3.0` (PyPI metadata); a standalone 2.x bump cannot resolve |
| `jmespath` | 1.1.0 | 1.1.0 | current |  |
| `langchain` | 1.4.2 | 1.4.5 | bump candidate (runtime, needs review) |  |
| `langchain-anthropic` | 1.7.2 | 1.7.6 | bump candidate (runtime, needs review) |  |
| `langchain-core` | 1.6.3 | 1.6.10 | bump candidate (runtime, needs review) |  |
| `langchain-google-genai` | 4.4.0 | 4.4.1 | bump candidate (runtime, needs review) |  |
| `langchain-openai` | 1.6.2 | 1.7.1 | bump candidate (runtime, needs review) |  |
| `langchain-xai` | 1.3.0 | 1.3.0 | current |  |
| `langgraph` | 1.2.11 | 1.2.15 | bump candidate (runtime, needs review) |  |
| `langsmith` | 0.13.0 | 0.14.8 | bump candidate (runtime, needs review) |  |
| `lark` | 1.3.1 | 1.3.1 | current |  |
| `mypy` | 2.3.0 | 2.4.0 | bump candidate (dev tool) |  |
| `nemoguardrails` | 0.24.0 | 0.24.1 | bump candidate (runtime, needs review) |  |
| `nltk` | 3.10.3 | 3.10.3 | documented exception | no newer release; CVE-2026-81726 documented in SECURITY.md |
| `numpy` | 1.26.4 | 2.5.4 | documented exception | held < 2 (chromadb/onnxruntime) |
| `onnxruntime` | 1.30.0 | 1.31.0 | bump candidate (runtime, needs review) |  |
| `packaging` | 26.3 | 26.3 | current |  |
| `pendulum` | 3.2.0 | 3.3.0 | bump candidate (runtime, needs review) |  |
| `pgvector` | 0.5.0 | 0.5.1 | bump candidate (runtime, needs review) |  |
| `psycopg` | 3.3.6 | 3.3.6 | current |  |
| `psycopg-binary` | 3.3.6 | 3.3.6 | current |  |
| `pydantic` | 2.13.5 | 2.14.1 | documented exception | lock-step with pydantic-core |
| `pydantic-core` | 2.46.5 | 2.50.1 | documented exception | lock-step with pydantic |
| `pydantic-settings` | 2.15.0 | 2.15.0 | current |  |
| `pygments` | 2.21.0 | 2.21.0 | current |  |
| `pyodbc` | 5.3.0 | 5.3.0 | current |  |
| `pytest` | 9.1.1 | 9.1.1 | current |  |
| `pytest-cov` | 7.1.0 | 7.1.0 | current |  |
| `pyyaml` | 6.0.3 | 6.0.3 | current |  |
| `rank-bm25` | 0.2.2 | 0.2.2 | current |  |
| `ruff` | 0.16.8 | 0.17.0 | bump candidate (dev tool) |  |
| `sentence-transformers` | 6.1.0 | 6.1.0 | current |  |
| `setuptools` | 84.0.0 | 84.0.0 | documented exception | pip-audit advisory floor |
| `sqlite-vec` | 0.1.9 | 0.1.9 | current |  |
| `starlette` | 1.6.0 | 1.7.0 | bump candidate (runtime, needs review) |  |
| `torch` | 2.13.0 | 2.14.1 | documented exception | CPU wheel pin; lock refresh on arm64 macOS |
| `tzdata` | 2026.2 | 2026.5 | bump candidate (runtime, needs review) |  |
| `uvicorn` | 0.53.0 | 0.54.0 | bump candidate (runtime, needs review) |  |
| `wcmatch` | 11.0 | 11.1 | bump candidate (runtime, needs review) |  |
| `websockets` | 15.0.1 | 17.2 | documented exception | pinned direct for langgraph-sdk import compatibility |

## Bump candidates worth a decision

Grouped by blast radius. A bump touches only the manifests and lock group that
**own** the package — the install surfaces are not four copies of one list
(`.claude/skills/verify-deps/SKILL.md`):

- Base runtime packages (`fastapi`, `starlette`, `uvicorn`, `langchain*`,
  `langgraph`, `pydantic` pair, `onnxruntime`, `nemoguardrails`, …):
  `pyproject.toml` + `constraints.txt` + `requirements.txt` +
  `environment.yml` in lock-step (`dep-guard` D6/D9).
- Extras-only packages (`deepagents`, `pgvector`, `langchain-openai`,
  `langchain-anthropic`, `pyodbc`, `psycopg*`):
  `pyproject.toml` optional-dependencies + `constraints.txt` only — never
  `requirements.txt` or `environment.yml` (`check_env_drift.py` E4 fails on
  that).
- Constraints-only transitives (`langsmith`, `langchain-google-genai`,
  `wcmatch`, `pendulum`, `pydantic-settings`, `lark`): `constraints.txt`
  alone.
- Test-only packages (`tzdata`): the `test` extra in `pyproject.toml` +
  `requirements-test.txt` + `constraints.txt` + the `python-tzdata` conda pin
  in `environment.yml` — never `requirements.txt` (no production module
  imports it; the wheel and Docker image stay without it).
- Dev tools (`ruff`, `mypy`): `pyproject.toml` dev extra + `constraints.txt`
  + `environment.yml` (they are not in `requirements-test.txt`); `ruff` is
  also pinned inline in `lint.yml` (E1 flags a split).

Whichever group owns the package, **both** refresh scripts run afterwards on
the arm64 macOS host: `scripts/check_lock_contract.py::contract` hashes
`constraints.txt` and `pyproject.toml`'s dependency tables into the runtime
*and* the CI lock inputs, so a change to either shared manifest invalidates
every group's recorded inputs even when only one group's resolved pins move,
and `check()` refuses with "regenerate the entire <group> set" until
`refresh-runtime-lock.sh` and `refresh-ci-locks.sh` have both been rerun.
Then CI's four test legs.

1. **LangChain stack (patch/minor, same majors):** `langchain` 1.4.2→1.4.5,
   `langchain-core` 1.6.3→1.6.10, `langgraph` 1.2.11→1.2.15,
   `langchain-anthropic` 1.7.2→1.7.6, `langchain-openai` 1.6.2→1.7.1,
   `langchain-google-genai` 4.4.0→4.4.1, `langsmith` 0.13.0→0.14.8,
   `deepagents` 0.6.12→0.7.24 (extras only). Move together; `graph.py` and
   the retired DeepAgents path are the consumers.
2. **Web stack (minor):** `fastapi` 0.141.1→0.143.0, `starlette` 1.6.0→1.7.0,
   `uvicorn` 0.53.0→0.54.0. `gate.py` imports `starlette` directly, so bump
   the three together and re-run `test_gate`/`test_terminal_contract` in CI.
3. **`huggingface-hub` 1.32.0→2.2.0 — blocked, not a candidate.**
   `sentence-transformers==6.1.0` declares `huggingface-hub<2.0.0,>=1.3.0`, so
   a standalone 2.x bump cannot resolve. It is pinned directly only because
   `retrieval/embeddings.py` imports it; revisit when `sentence-transformers`
   itself moves to a release that allows 2.x, and bump the two together.
4. **`pydantic` 2.13.5→2.14.1 with `pydantic-core` 2.46.5→2.50.1** — lock-step
   pair. Beyond the manifests, the pair is hard-coded as the repository's
   dependency contract in `.claude/skills/dep-guard/check_deps.py`
   (`_PYDANTIC_LOCKSTEP`) and in CLAUDE.md §4 "Dependencies"; D1 fails until
   both are updated in the same commit. `schemas/api.py` uses
   `strict=True`/`extra='forbid'`, so CI must run `test_schemas*` after.
5. **Small runtime:** `onnxruntime` 1.30.0→1.31.0 (telemetry suppression in
   `utils/onnx_telemetry.py` must be re-verified — `otel-hardening`),
   `nemoguardrails` 0.24.0→0.24.1 (re-run `guardrails.verify_install`),
   `pendulum` 3.2.0→3.3.0, `pgvector` 0.5.0→0.5.1, `wcmatch` 11.0→11.1.
6. **Test and dev tools (low blast radius, but re-run lint before merging):**
   `tzdata` 2026.2→2026.5 (test-only surface, see above), `ruff`
   0.16.8→0.17.0 (`lint.yml` also pins it inline — E1 will flag a split),
   `mypy` 2.3.0→2.4.0.

Deliberately not recommended: `torch` 2.13.0→2.14.1 (CPU wheel pin across
four surfaces and the Docker torch line; a release of its own), `numpy` <2,
`websockets` 15.0.1 (langgraph-sdk import compatibility), `setuptools` floor,
`chromadb`, `nltk`, and `huggingface-hub` 2.x (blocked by
`sentence-transformers`, item 3).

## What this sweep did not do

- No `mamba env create --dry-run` for `environment.yml` (no conda here).
- No run of the pytest suite or the four CI legs.
- No `uv` dry-run: no supported end-user or CI *installation* command uses
  `uv` (the Dockerfile, workflows, and documented installs are pip), and the
  skill records why (`first-index` strategy + the `setuptools` pin) a `uv`
  install result would mislead. `uv` is still required for lock
  *generation*: `scripts/refresh-runtime-lock.sh` and
  `scripts/refresh-ci-locks.sh` run `uv pip compile` (`UV_BIN`), so a
  maintainer regenerating locks does need it installed.
