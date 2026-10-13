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
Currency:             19 current | 18 runtime bump candidates (needs review; the pydantic pair counts as two rows, one decision) | 1 test-only bump candidate | 2 dev-tool bump candidates | 7 documented or compatibility-blocked exceptions
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
| `pydantic` | 2.13.5 | 2.14.1 | bump candidate (runtime, needs review) | lock-step pair with `pydantic-core` 2.50.1 — item 4; never alone |
| `pydantic-core` | 2.46.5 | 2.50.1 | bump candidate (runtime, needs review) | constraints-only; moves only with `pydantic` 2.14.1, which hard-pins it — item 4 |
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
| `tzdata` | 2026.2 | 2026.5 | bump candidate (test-only, needs review) | `test` extra / `requirements-test.txt`; not installed by the wheel or Docker image |
| `uvicorn` | 0.53.0 | 0.54.0 | bump candidate (runtime, needs review) |  |
| `wcmatch` | 11.0 | 11.1 | bump candidate (runtime, needs review) |  |
| `websockets` | 15.0.1 | 17.2 | documented exception | pinned direct for langgraph-sdk import compatibility |

## Bump candidates worth a decision

Grouped by blast radius. A bump touches only the manifests and lock group that
**own** the package — the install surfaces are not four copies of one list
(`.claude/skills/verify-deps/SKILL.md`):

- Base runtime packages (`fastapi`, `starlette`, `uvicorn`, `langchain-core`,
  `langgraph`, `pydantic`, `onnxruntime`, `nemoguardrails`, …; of the
  LangChain family only those two are base — `pyproject.toml`
  `[project.dependencies]`; `pydantic-core` is **not** here — it lives in
  `constraints.txt` only, because `pydantic` hard-pins its exact version and
  `pyproject.toml` says so in a comment):
  `pyproject.toml` + `constraints.txt` + `requirements.txt` +
  `environment.yml` in lock-step (`dep-guard` D6/D9).
- Extras-only packages (`deepagents`, `langchain`, `langchain-openai`,
  `langchain-anthropic` — all four in the `agentic-deepagents` extra —
  `pgvector`, `pyodbc`, `psycopg*`):
  `pyproject.toml` optional-dependencies + `constraints.txt` only — never
  `requirements.txt` or `environment.yml` (`check_env_drift.py` E4 fails on
  that).
- Constraints-only transitives (`pydantic-core`, `langsmith`,
  `langchain-google-genai`, `wcmatch`, `pendulum`, `pydantic-settings`,
  `lark`): `constraints.txt` alone.
- Test-only packages (`tzdata`): the `test` extra in `pyproject.toml` +
  `requirements-test.txt` + `constraints.txt` + the `python-tzdata` conda pin
  in `environment.yml` — never `requirements.txt` (no production module
  imports it; the wheel and Docker image stay without it).
- Dev tools (`ruff`, `mypy`): `pyproject.toml` dev extra + `constraints.txt`
  + `environment.yml` (they are not in `requirements-test.txt`). `lint.yml`
  installs `ruff` from its hashed lock and names `ruff==0.16.8` only in a
  comment (`lint.yml:84`); E1 compares inline workflow pins with each other,
  not with the manifests, so that comment goes stale silently — update it
  by hand with the bump.

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
   `deepagents` 0.6.12→0.7.24. Move together, but by ownership: only
   `langchain-core` and `langgraph` are base runtime (`graph.py` is the
   consumer); `langchain`, `langchain-openai`, `langchain-anthropic`, and
   `deepagents` are the `agentic-deepagents` extra; `langchain-google-genai`
   and `langsmith` are constraints-only. Same telemetry contract as the NeMo
   and ONNX items below: `.claude/skills/otel-hardening/check_otel.py`
   `LAST_VERIFIED_VENDOR_PINS` records `langchain` 1.4.2, `langchain-core`
   1.6.3, `langgraph` 1.2.11, and `langsmith` 0.13.0, so T5 warns on each
   moved pin and `check_otel.py --strict` exits 2 until the installed
   sources are re-grepped for telemetry/analytics/usage-stat hooks (the
   `langsmith` tracing-precedence check in particular), the four pins are
   updated in the checker, and the strict run is green — before CI's legs.
   The strict run covers the pin dict only: the category-3 cloud-adapter
   `INVENTORY` row (`check_otel.py:410-413`) records `deepagents`,
   `langchain`, `langchain-openai`, `langchain-anthropic`,
   `langchain-google-genai`, `langsmith`, and `wcmatch` versions in prose
   that `--strict` never compares with the manifests, so that row is
   reviewed and rewritten in the same commit.
2. **Web stack (minor):** `fastapi` 0.141.1→0.143.0, `starlette` 1.6.0→1.7.0,
   `uvicorn` 0.53.0→0.54.0. `gate.py` imports `starlette` directly, so bump
   the three together. Not a test-only bump: `fastapi` 0.143.0's PyPI
   metadata adds `opentelemetry-api>=1.44.0` as an **unconditional**
   dependency (0.141.1 declares no OpenTelemetry package at all; the SDK and
   the OTLP HTTP exporter arrive behind its `opentelemetry`/`standard`/`all`
   extras, which CyClaw does not install). That puts a new
   telemetry-capable transitive on the base install path, so the bump needs
   the `otel-hardening` classification pass (`check_otel.py` already lists
   `opentelemetry-sdk` among its transitive vendors to report), an exact
   `opentelemetry-api` pin in `constraints.txt` on the same ground the file's
   header gives for the pydantic family and torch — it pins direct
   dependencies plus *selected critical* transitives and leaves complete
   transitive reproducibility to the hashed locks, so a telemetry-capable
   package newly on the base path qualifies as a selected constraint, while
   ordinary new transitives simply ride the regenerated locks (no checker
   decides this; it is a review judgement) — then the locks regenerated and
   `test_gate`/`test_terminal_contract` in CI.
3. **`huggingface-hub` 1.32.0→2.2.0 — blocked, not a candidate.**
   `sentence-transformers==6.1.0` declares `huggingface-hub<2.0.0,>=1.3.0`, so
   a standalone 2.x bump cannot resolve. It is pinned directly only because
   `retrieval/embeddings.py` imports it; revisit when `sentence-transformers`
   itself moves to a release that allows 2.x, and bump the two together.
4. **`pydantic` 2.13.5→2.14.1 with `pydantic-core` 2.46.5→2.50.1** — lock-step
   pair, one decision: PyPI metadata for `pydantic` 2.14.1 requires exactly
   `pydantic-core==2.50.1`, so the pair is a candidate, not an exception,
   and `pydantic-core` is never bumped alone. Ownership differs within the
   pair: `pydantic` is base runtime (all four manifests), `pydantic-core` is
   constraints-only. `constraints.txt`'s header comment ("2.13.5 is the
   latest pydantic", "no pydantic release pairs with" the newer core) is
   stale as of 2026-10-13 and moves with the pin. Beyond the manifests, the pair is hard-coded as the repository's
   dependency contract in `.claude/skills/dep-guard/check_deps.py`
   (`_PYDANTIC_LOCKSTEP`) and in CLAUDE.md §4 "Dependencies"; D1 fails until
   both are updated in the same commit. `schemas/api.py` uses
   `strict=True`/`extra='forbid'`; there is no `test_schemas*` file, so the
   focused re-check is the files that import those models —
   `tests/test_gate.py` (request/response strictness), `tests/test_ops_runner.py`,
   `tests/test_memory_routes.py`, and `tests/test_telegram_runner.py` — before
   CI's full legs.
5. **Small runtime:** `onnxruntime` 1.30.0→1.31.0 (telemetry suppression in
   `utils/onnx_telemetry.py` must be re-verified — `otel-hardening`),
   `nemoguardrails` 0.24.0→0.24.1 (same telemetry contract as the ONNX bump:
   `.claude/skills/otel-hardening/check_otel.py` pins the last-verified
   vendor version in `LAST_VERIFIED_VENDOR_PINS`, so the bump needs a
   source-level re-check of NeMo's usage-stat opt-outs and telemetry sink,
   the pin updated in the checker, `check_otel.py --strict` green — plus
   every other site that hard-codes `0.24.0`. That inventory is the output
   of `git grep -nF '0.24.0' -- ':!locks'` (tracked files only — a bare
   `grep -rn` also walks ignored `logs/`, `data/`, and venvs and would print
   whatever line matched), not a list to copy; on
   2026-10-13 it returned, besides the five manifests, these fail-closed
   sites: `guardrails/verify_install.py` (raises unless exactly 0.24.0),
   `dep-guard` D11 and its `verify.sh` fixture (`nemoguardrails==0.24.0`
   once per install surface), `ci.yml`'s wheel-packaging metadata assert,
   and `tests/nemo_runtime/test_nemo_runtime.py`'s
   `test_installed_version_is_0240`, which `nemo-guardrails.yml` runs
   against the real install; plus one message string in
   `guardrails/integration.py` and five docs (`README.md`,
   `guardrails/README.md`, `docs/NeMo/README.md`, `docs/DOCKER.md`,
   `setup-guide.md`) that `doc_sync.py` would flag. All move in the same
   commit as the pin; then `guardrails.verify_install`),
   `pendulum` 3.2.0→3.3.0, `pgvector` 0.5.0→0.5.1, `wcmatch` 11.0→11.1.
   Those three are **not** in `LAST_VERIFIED_VENDOR_PINS`, so
   `check_otel.py --strict` stays green after the pins move — but its
   egress inventory names `pendulum==3.2.0`, `pgvector==0.5.0`, and
   `wcmatch==11.0` in prose, and the pendulum no-egress conclusion was
   drawn from source at that version. Each bump re-checks the source and
   updates its inventory row in the same commit; the bare-version grep in
   the skill gotcha finds these rows, the strict run does not.
6. **Test and dev tools (low blast radius, but re-run lint before merging):**
   `tzdata` 2026.2→2026.5 (test-only surface, see above), `ruff`
   0.16.8→0.17.0 (`lint.yml:84` names the version in a comment E1 does not
   check against the manifests — update it by hand),
   `mypy` 2.3.0→2.4.0.

Deliberately not recommended: `torch` 2.13.0→2.14.1 (CPU wheel pin across
`pyproject.toml`, `constraints.txt`, and `environment.yml` — **never**
`requirements.txt`, which excludes torch on purpose so the CPU index stays
out of the ordinary resolve — plus `requirements-torch.txt`, the input
`refresh-runtime-lock.sh` compiles the three `requirements-torch-lock-*.txt`
from, which `extract_pins.py` has no column for; the Dockerfile installs the
Linux torch lock and carries no versioned torch line of its own; and the
`torch-cpu-2.13.0-` cache keys in `ci.yml`, `pip-audit.yml`, and
`nemo-guardrails.yml`, which no `torch==` grep finds and `dep-guard` D8
exists to catch; a release of its own), `numpy` <2,
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
