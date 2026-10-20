# Dependency sync audit — 2026-10-20

**Scope:** manifests, locks and install docs on `origin/main` @ `cdcef76`
(after PR #1725), read with the two open PRs (#1726 Dependabot config,
#1727 installer-test timeout) treated as merged: neither touches a manifest,
a lock or an install command. Run from a Linux cloud sandbox with the system
Python 3.12 and PyPI reachable. Reports only; **no pin was changed.** The
hashed `locks/` regenerate only on the arm64 macOS host
(`scripts/refresh-runtime-lock.sh`, `scripts/refresh-ci-locks.sh`), and
`scripts/check_lock_contract.py` hashes `constraints.txt` and
`requirements*.txt` byte-for-byte, so any manifest edit here (a comment
included) would turn the lock contract red until the owner re-locks. A bump
is therefore an owner decision, exactly as the Dependabot header in
`.github/dependabot.yml` (#1726) now states.

The previous sweep is
[2026-10-13](2026-10-13-dependency-currency-sweep.md); this one records the
delta after the agentic removal (#1699), the orphaned-extras drop (#1700) and
the aiohttp floor (#1715).

## Summary

```
Verify Deps: 42 packages checked (40 constraints.txt pins + hatchling + pip) | 23 behind latest | 2 packages with advisories on the pin (both already accepted in SECURITY.md) | 0 new advisories since 2026-10-13
dep-guard:            PASS (D1-D11, 0 failures, 0 warnings)
Env drift (E1-E7):    0 failure(s), 0 warning(s); E3 all 103 imported modules declared
Lock contract:        scripts/check_lock_contract.py passed (19 locks, 2 input records)
Lock <-> manifest:    all 19 lock files agree with constraints.txt on every shared pin (148 shared entries checked; +cpu local tag ignored)
doc-sync:             0 drift items (D1-D13)
Install surfaces:     not dry-run here (download.pytorch.org is denied by the sandbox proxy, same as 2026-10-13); the hashed-lock contract and CI's four legs are the evidence on main
Verdict:              no fixes applied; findings for review below
```

## Delta since 2026-10-13

- **Pins gone (6 lock files, 10 packages):** `deepagents`, `langchain`,
  `langchain-openai`, `langchain-anthropic`, `langchain-xai`,
  `langchain-google-genai`, `wcmatch`, `pyodbc` left with the
  `agentic-deepagents`, `agentic-deepagents-cloud` and `mssql` extras
  (#1700). `locks/` went from 25 files to 19; `setup-guide.md` said 25 until
  this audit's doc pass.
- **Pin added:** `aiohttp==3.14.4` in `constraints.txt` (#1715, security
  floor for a nemoguardrails/chromadb transitive). 3.14.5 is out and carries
  no advisory; nothing to act on.
- **Moved upstream since then:** `fastapi` 0.143.0→0.153.0 latest,
  `starlette` 1.7.0→1.9.0, `langchain-core` 1.6.10→1.6.12, `langgraph`
  1.2.15→1.2.16, `langsmith` 0.14.8→0.14.11, `ruff` 0.17.0→0.17.1,
  `websockets` 17.2→17.3, `pydantic-settings` 2.15.0→2.16.1 (was current).
  The pinned versions did not move.
- **Stale manifest comment (not fixed here, on purpose):** `constraints.txt`
  still says "2.13.5 is the latest pydantic on PyPI" and that no pydantic
  release pairs with a newer pydantic-core. PyPI now has `pydantic==2.14.1`
  hard-pinning `pydantic-core==2.50.1`. Fixing the comment re-hashes
  `constraints.txt` and fails the lock contract, so it rides the next re-lock.

## Advisories on pinned versions (PyPI `vulnerabilities`, per-release endpoint)

| Package | Pinned | Advisories reported | Status |
|---|---|---|---|
| `chromadb` | 1.5.9 | CVE-2026-45829 / PYSEC-2026-311 / GHSA-f4j7-r4q5-qw2c; CVE-2026-45830 / PYSEC-2026-3813 / GHSA-2wm9-hf6c-p5cr; CVE-2026-45831 / PYSEC-2026-3815 / GHSA-xph7-9rjv-w5fr; CVE-2026-45833 / PYSEC-2026-3814 / GHSA-36p7-vc44-83pf | All four accepted in `SECURITY.md` for the embedded `PersistentClient`-only posture; `pip-audit.yml` ignores the four CVE ids. 1.5.9 is still the latest release. Do not switch to the HTTP client or file a fix PR. |
| `nltk` | 3.10.3 | PYSEC-2026-3740 / CVE-2026-81726 / GHSA-8mgp-746c-j5xp (model-artifact file-sandbox bypass) | Accepted in `SECURITY.md` (reviewed 2026-10-04): the affected APIs are not imported; `retrieval/stemmer.py` uses `PorterStemmer` only. No fixed version. The OSV-Scanner suppression expires 2026-11-01; re-check then. |

No other pinned package reports an advisory. Every package was queried at
`/pypi/<package>/<pinned-version>/json`.

## Currency table

Pinned column is `constraints.txt` (plus `hatchling` from `[build-system]`
and the `pip==26.2.1` CI pin); latest is PyPI `info.version` on 2026-10-20.
Conda-only names (`pytorch`, `python-tzdata`) are omitted.

| Package | Pinned | Latest | Class | Note |
|---|---|---|---|---|
| `aiohttp` | 3.14.4 | 3.14.5 | bump candidate (constraints-only transitive) | security floor pinned 2026-10-20 (#1715); 3.14.5 carries no new advisory, not required |
| `bandit` | 1.9.4 | 1.9.4 | current |  |
| `cel-python` | 0.5.0 | 0.5.0 | current |  |
| `chromadb` | 1.5.9 | 1.5.9 | documented exception | risk-accepted CVE set (SECURITY.md); embedded `PersistentClient` only; 1.5.9 is still the latest release; advisories on pin: GHSA-2wm9-hf6c-p5cr, GHSA-36p7-vc44-83pf, GHSA-f4j7-r4q5-qw2c, GHSA-xph7-9rjv-w5fr, PYSEC-2026-311, PYSEC-2026-3813, PYSEC-2026-3814, PYSEC-2026-3815 |
| `fastapi` | 0.141.1 | 0.153.0 | bump candidate (runtime, needs review) |  |
| `google-re2` | 1.1.20251105 | 1.1.20251105 | current |  |
| `hatchling` | 1.32.0 | 1.32.4 | bump candidate (build tool) | `[build-system].requires` only; not a lock input |
| `httpx` | 0.28.1 | 0.28.1 | current |  |
| `huggingface-hub` | 1.32.0 | 2.2.0 | compatibility-blocked exception | `sentence-transformers==6.1.0` requires `huggingface-hub<2.0.0,>=1.3.0` (PyPI metadata); a standalone 2.x bump cannot resolve |
| `jmespath` | 1.1.0 | 1.1.0 | current |  |
| `langchain-core` | 1.6.3 | 1.6.12 | bump candidate (runtime, needs review) |  |
| `langgraph` | 1.2.11 | 1.2.16 | bump candidate (runtime, needs review) |  |
| `langsmith` | 0.13.0 | 0.14.11 | bump candidate (constraints-only transitive) | runtime transitive of langchain-core |
| `lark` | 1.3.1 | 1.3.1 | current |  |
| `mypy` | 2.3.0 | 2.4.0 | bump candidate (dev tool) |  |
| `nemoguardrails` | 0.24.0 | 0.24.1 | bump candidate (runtime, needs review) |  |
| `nltk` | 3.10.3 | 3.10.3 | documented exception | no newer release; PYSEC-2026-3740 / CVE-2026-81726 accepted in SECURITY.md, review by 2026-11-01; advisories on pin: GHSA-8mgp-746c-j5xp |
| `numpy` | 1.26.4 | 2.5.4 | documented exception | held < 2 (chromadb/onnxruntime) |
| `onnxruntime` | 1.30.0 | 1.31.0 | bump candidate (runtime, needs review) |  |
| `packaging` | 26.3 | 26.3 | current |  |
| `pendulum` | 3.2.0 | 3.3.0 | bump candidate (constraints-only transitive) | cel-python requirement |
| `pgvector` | 0.5.0 | 0.5.1 | bump candidate (extra: pgvector) |  |
| `pip` | 26.2.1 | 26.2.1 | current |  |
| `psycopg` | 3.3.6 | 3.3.6 | current |  |
| `psycopg-binary` | 3.3.6 | 3.3.6 | current |  |
| `pydantic` | 2.13.5 | 2.14.1 | bump candidate (runtime, needs review) | lock-step pair: pydantic 2.14.1 hard-pins `pydantic-core==2.50.1`; move both plus dep-guard `_PYDANTIC_LOCKSTEP` |
| `pydantic-core` | 2.46.5 | 2.50.1 | bump candidate (runtime, needs review) | constraints-only; moves only with pydantic 2.14.1 |
| `pydantic-settings` | 2.15.0 | 2.16.1 | bump candidate (constraints-only transitive) | chromadb transitive; must stay compatible with the pydantic pair |
| `pygments` | 2.21.0 | 2.21.0 | current |  |
| `pytest` | 9.1.1 | 9.1.1 | current |  |
| `pytest-cov` | 7.1.0 | 7.1.0 | current |  |
| `pyyaml` | 6.0.3 | 6.0.3 | current |  |
| `rank-bm25` | 0.2.2 | 0.2.2 | current |  |
| `ruff` | 0.16.8 | 0.17.1 | bump candidate (dev tool) | also the `ruff==` comment in `lint.yml` |
| `sentence-transformers` | 6.1.0 | 6.1.0 | current |  |
| `setuptools` | 84.0.0 | 84.2.0 | documented exception | constraints-only floor for PYSEC-2026-3447 (83.0.0); 84.2.0 is a free patch bump if the lock is refreshed anyway |
| `sqlite-vec` | 0.1.9 | 0.1.9 | current |  |
| `starlette` | 1.6.0 | 1.9.0 | bump candidate (runtime, needs review) |  |
| `torch` | 2.13.0+cpu | 2.14.1 | documented exception | CPU wheel pin; lock refresh on arm64 macOS; `+cpu` tag on Linux/Windows only |
| `tzdata` | 2026.2 | 2026.5 | bump candidate (test-only, needs review) | `test` extra / `requirements-test.txt` / `python-tzdata` in environment.yml |
| `uvicorn` | 0.53.0 | 0.54.0 | bump candidate (runtime, needs review) |  |
| `websockets` | 15.0.1 | 17.3 | documented exception | pinned direct for langgraph-sdk import compatibility |

## Bump candidates worth a decision

Ownership rules (which manifests move with which package, and which refresh
script runs afterwards) are unchanged from the
[2026-10-13 report](2026-10-13-dependency-currency-sweep.md#bump-candidates-worth-a-decision)
and `locks/README.md`; they are not repeated here. Every item below needs the
arm64 macOS re-lock before it can merge.

1. **Web stack (minor):** `fastapi` 0.141.1→0.153.0, `starlette` 1.6.0→1.9.0,
   `uvicorn` 0.53.0→0.54.0. Twelve fastapi minors behind; read the fastapi
   and starlette release notes for the request-body and `TestClient` paths
   `gate.py` relies on (`docs/analysis/TESTCLIENT_HTTPX_DEPRECATION.md`).
2. **LangChain stack (patch):** `langchain-core` 1.6.3→1.6.12, `langgraph`
   1.2.11→1.2.16, `langsmith` 0.13.0→0.14.11 (constraints-only). Only these
   three remain after #1700. `check_otel.py` `LAST_VERIFIED_VENDOR_PINS`
   records the current three, so T5 warns until the installed sources are
   re-grepped and the pins updated there.
3. **pydantic pair:** 2.13.5→2.14.1 with `pydantic-core` 2.46.5→2.50.1 and
   `pydantic-settings` 2.15.0→2.16.1; move dep-guard's `_PYDANTIC_LOCKSTEP`
   and the `constraints.txt` comment in the same commit.
4. **Guardrail/ONNX:** `nemoguardrails` 0.24.0→0.24.1, `onnxruntime`
   1.30.0→1.31.0. Both are telemetry-vendor pins (`check_otel.py`); the
   ONNX floor stays 1.29.0. `docs/NeMo/README.md` and the Dockerfile's
   `verify_install` step are the regression checks.
5. **Small and isolated:** `pgvector` 0.5.1 (extra), `pendulum` 3.3.0
   (cel-python transitive), `tzdata` 2026.5 (test-only), `setuptools` 84.2.0,
   `aiohttp` 3.14.5, `hatchling` 1.32.4 (no lock input), `ruff` 0.17.1 and
   `mypy` 2.4.0 (dev; run ruff over the tree with the repo rule set before
   pinning, as the 2026-08-02 bump did).

Documented or blocked exceptions, unchanged: `torch` 2.13.0 (+cpu), `numpy`
<2, `websockets` 15.0.1, `huggingface-hub` 1.x (blocked by
`sentence-transformers`), `chromadb`, `nltk`.

## What this sweep did not do

- No install dry-run (the CPU torch index is denied by the sandbox proxy);
  no `mamba env create --dry-run`; no pytest run and no CI leg.
- No `uv` run; `uv` is needed only for lock generation on the macOS host.
- No `api.osv.dev` query (blocked); the PyPI advisory feed mirrors the PyPA
  database, GHSA and PYSEC ids included.
