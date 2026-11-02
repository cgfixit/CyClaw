# Dependency sync audit — 2026-11-02

**Scope:** manifests, locks, install commands and the Docker surface on
`origin/main` @ `84b7bf1` (after PR #1803), with the only open PR (#1805,
docs and compose comments) touching no manifest, lock or install command. Run
from a Linux cloud sandbox with `/usr/bin/python3.12` (3.12.3), PyPI and
`download.pytorch.org` both reachable, and the Docker CLI present without a
daemon. Reports only; **no pin was changed.** The hashed `locks/` regenerate
only on the arm64 macOS host (`scripts/refresh-runtime-lock.sh`,
`scripts/refresh-ci-locks.sh`), and `scripts/check_lock_contract.py` hashes
the manifests into every lock's recorded inputs, so any manifest edit here
would turn the lock contract red until the owner re-locks.

The previous sweep is
[2026-10-20](2026-10-20-dependency-currency-sweep.md). Since then the pins
moved in #1743/#1744 (relock), #1765 (Numbat hash-lock, torch conda floor)
and #1784 (pillow 13.0.0, fastembed 0.9.1).

## Summary

```
Verify Deps: 46 packages checked (44 manifest pins + hatchling + pip) | 22 behind latest | 1 package with advisories on the pin (chromadb, all 4 accepted in SECURITY.md) | 0 new advisories since 2026-10-20
dep-guard:            PASS (D1-D11, 0 failures, 0 warnings)
requirements drift:   none (requirements.txt + requirements-test.txt <-> constraints.txt)
Env drift (E1-E7):    0 failure(s), 0 warning(s) under --strict; no E3 names reported
verify-deps verify:   OK (all mutation self-tests trip their rule)
otel-hardening:       check_otel.py --strict 0 failures, 0 warnings (vendor pins unmoved)
Lock contract:        scripts/check_lock_contract.py passed
Lock <-> manifest:    all 20 lock files agree with constraints.txt on every shared pin (165 shared entries; +cpu local tag ignored)
Install surfaces:     locks (torch real install + runtime/test dry-run)=PASS editable=PASS legacy=PASS wheel-build=PASS compose-render=PASS conda=not dry-run-verified docker-build=not run (no daemon)
Verdict:              verify-deps SKILL.md Step 4 recipe fixed (2 defects); no pin changed; findings for review below
```

## Install surfaces (Step 4)

Each command ran in a **fresh** Python 3.12.3 venv with `pip==26.2.2` (the
CI/Dockerfile pin), so no pre-installed package could make a resolve pass
conditionally.

| # | Command (fresh venv) | Result | Evidence |
|---|---|---|---|
| 1a | `pip install --require-hashes --no-deps -r locks/requirements-torch-lock-linux.txt --index-url https://download.pytorch.org/whl/cpu` | PASS | installs `torch 2.14.1+cpu` (`pip show torch`) |
| 1b | `pip install --dry-run --require-hashes -r locks/requirements-lock-linux.txt` | PASS | rc 0; would install 135 packages; `torch>=2.2` reported "already satisfied" by the installed `2.14.1+cpu`, no other torch proposed |
| 1c | `pip install --dry-run --require-hashes -r locks/requirements-test-lock-linux.txt` | PASS | would install 9 packages (`pytest-9.1.1`, `pytest-cov-7.1.0`, `tzdata-2026.5`, ...) |
| 2 | `pip install --dry-run -e . -c constraints.txt --extra-index-url https://download.pytorch.org/whl/cpu` | PASS | resolves `torch-2.14.1+cpu`, `numpy-1.26.4`, `pydantic-2.13.5`/`pydantic_core-2.46.5`, `chromadb-1.5.9`, `nemoguardrails-0.24.1` |
| 3 | `pip install --dry-run -r requirements.txt -r requirements-test.txt -c constraints.txt --extra-index-url https://download.pytorch.org/whl/cpu` | PASS | same resolved versions as row 2 |
| 4 | `pip wheel --no-deps -w <tmp> .` | PASS | builds `cyclaw-1.9.0-py3-none-any.whl` through hatchling |
| 5 | `docker compose config --quiet` | PASS | exit 0 with no daemon (`docker info` fails); a copy with `image:` renamed `imagez:` exits 1 (`services.falco.imagez false schema`), so the render is a real schema check |

**Recipe defect found and fixed in this PR.** `verify-deps` SKILL.md Step 4
ran row 1a as `--dry-run`. A dry-run installs nothing, and the runtime lock
omits torch by design, so in a fresh venv row 1b then failed:
`In --require-hashes mode, all requirements must have their versions pinned
with ==. These do not: torch>=2.2 from .../torch-2.15.0-cp312-cp312-manylinux_2_28_x86_64.whl
(from sentence-transformers==6.1.0 ...)`. pip had reached for PyPI's CUDA
torch, and hash mode refused it, which is the fail-closed behavior the lock
exists for. The tree was never broken; the recipe could not pass as written.
The skill's own Gotchas already warned that the runtime lock "resolved only
because a torch build was present". Step 4 now installs the torch lock for
real, matching the Dockerfile and CLAUDE.md §8. Step 4's note that
`docker compose config` "needs ... a running daemon" was also wrong (row 5)
and is corrected.

## Advisories on pinned versions (PyPI `vulnerabilities`, per-release endpoint)

Every package was queried at `/pypi/<package>/<pinned-version>/json`, not the
project endpoint, whose `vulnerabilities` array describes only the latest
release.

| Package | Pinned | Advisories reported | Status |
|---|---|---|---|
| `chromadb` | 1.5.9 | CVE-2026-45829 / PYSEC-2026-311 / GHSA-f4j7-r4q5-qw2c; CVE-2026-45830 / PYSEC-2026-3813 / GHSA-2wm9-hf6c-p5cr; CVE-2026-45831 / PYSEC-2026-3815 / GHSA-xph7-9rjv-w5fr; CVE-2026-45833 / PYSEC-2026-3814 / GHSA-36p7-vc44-83pf | All four accepted in `SECURITY.md` (last reviewed 2026-10-23) for the embedded `PersistentClient`-only posture; the `.osv-scanner.toml` suppressions run to 2027-02-01. 1.5.9 is still the latest release. Do not switch to the HTTP client or file a fix PR. |

`nltk` 3.10.4 now reports **no** advisory; the 2026-10-20 sweep's 2026-11-01
re-check date is moot because #1763 retired that acceptance. No other pinned
package reports an advisory.

**Outside this skill's scope, but due soon:** `SECURITY.md`'s Debian 12
container-library exception (issues #1629 / #1757) expires **2026-12-01**.

## Currency table

Pinned column is `constraints.txt` (plus `hatchling` from `[build-system]`
and the `pip==26.2.2` CI pin); latest is PyPI `info.version` on 2026-11-02.
**Newest ≥7d** is the newest non-yanked final release at least seven days
old, the "prefer releases older than a week" rule the `.githooks` security
gate states and Dependabot's `cooldown: default-days: 7` (#1790) applies.
Conda-only names (`pytorch`, `python-tzdata`) are omitted.

| Package | Pinned | Latest | Newest ≥7d | Class | Note |
|---|---|---|---|---|---|
| `aiohttp` | 3.14.5 | 3.14.5 | — | current | |
| `bandit` | 1.9.4 | 1.9.4 | — | current | |
| `cel-python` | 0.5.0 | 0.5.0 | — | current | |
| `certifi` | 2026.10.19 | 2026.10.23 | 2026.10.23 | bump candidate (constraints-only transitive) | CA bundle refresh |
| `chromadb` | 1.5.9 | 1.5.9 | — | documented exception | see Advisories |
| `fastapi` | 0.143.3 | 0.162.0 | 0.162.0 | bump candidate (runtime, needs review) | 19 minors behind; 0.162.0 still needs only `starlette>=0.46.0`, `pydantic>=2.9.0`, `opentelemetry-api>=1.44.0` (all satisfied by current pins) |
| `fastembed` | 0.9.1 | 0.9.1 | — | current | |
| `google-re2` | 1.1.20251105 | 1.1.20251105 | — | current | |
| `hatchling` | 1.32.4 | 1.33.0 | — | bump candidate (build tool) | `[build-system].requires` only; not a lock input |
| `httpx` | 0.28.1 | 0.28.1 | — | current | |
| `huggingface-hub` | 1.32.0 | 2.4.0 | 2.3.0 | **no longer blocked**; major, needs review | see "Changed since 2026-10-20" |
| `jmespath` | 1.1.0 | 1.1.0 | — | current | |
| `langchain-core` | 1.6.12 | 1.7.3 | 1.7.0 | bump candidate (runtime, needs review) | minor; 1.7.x needs `langsmith>=0.14.9` (pinned 0.14.11 satisfies) |
| `langgraph` | 1.2.15 | 1.2.19 | 1.2.17 | bump candidate (runtime, needs review) | patch; needs `langchain-core>=1.4.7` |
| `langsmith` | 0.14.11 | 0.14.17 | 0.14.12 | bump candidate (constraints-only transitive) | moves with langchain-core |
| `lark` | 1.3.1 | 1.3.1 | — | current | |
| `mypy` | 2.4.0 | 2.4.1 | 2.4.0 | current under cooldown | 2.4.1 is 4 days old |
| `nemoguardrails` | 0.24.1 | 0.24.1 | — | current | |
| `nltk` | 3.10.4 | 3.10.4 | — | current | no advisory on the pin |
| `numpy` | 1.26.4 | 2.5.4 | 2.5.4 | documented exception | held `<2` (chromadb/onnxruntime; CLAUDE.md §4) |
| `onnxruntime` | 1.31.0 | 1.31.1 | 1.31.0 | current under cooldown | 1.31.1 is 6 days old; telemetry-vendor pin in `check_otel.py` |
| `opentelemetry-api` | 1.45.1 | 1.45.2 | 1.45.1 | current under cooldown | |
| `packaging` | 26.3 | 26.3 | — | current | |
| `pendulum` | 3.3.0 | 3.3.0 | — | current | |
| `pgvector` | 0.5.1 | 0.5.1 | — | current | |
| `pillow` | 13.0.0 | 13.0.0 | — | current | |
| `pip` | 26.2.2 | 26.2.2 | — | current | 17 workflow/Dockerfile sites agree (E1) |
| `psycopg` / `psycopg-binary` | 3.3.6 | 3.3.6 | — | current | |
| `pydantic` | 2.13.5 | 2.14.2 | 2.14.1 | bump candidate (runtime, needs review) | lock-step: 2.14.1 hard-pins `pydantic-core==2.50.1`; move both plus dep-guard `_PYDANTIC_LOCKSTEP` and CLAUDE.md §4 |
| `pydantic-core` | 2.46.5 | 2.50.2 | 2.50.1 | bump candidate (runtime, needs review) | constraints-only; moves only with pydantic |
| `pydantic-settings` | 2.16.0 | 2.16.2 | 2.16.1 | bump candidate (constraints-only transitive) | chromadb transitive |
| `pygments` | 2.21.0 | 2.21.0 | — | current | |
| `pytest` | 9.1.1 | 9.2.0 | 9.1.1 | current under cooldown | 9.2.0 is 5 days old |
| `pytest-cov` | 7.1.0 | 7.1.0 | — | current | |
| `pyyaml` | 6.0.3 | 6.0.3 | — | current | |
| `rank-bm25` | 0.2.2 | 0.2.2 | — | current | |
| `ruff` | 0.17.1 | 0.17.3 | 0.17.2 | bump candidate (dev tool) | also the `ruff==` comment in `lint.yml`; re-run ruff over the tree before pinning |
| `sentence-transformers` | 6.1.0 | 6.2.0 | 6.2.0 | bump candidate (runtime, needs review) | unlocks huggingface-hub 2.x |
| `setuptools` | 84.1.0 | 84.2.1 | 84.2.1 | bump candidate (constraints-only floor) | floor for PYSEC-2026-3447; free patch if re-locking anyway |
| `sqlite-vec` | 0.1.9 | 0.1.9 | — | current | |
| `starlette` | 1.8.0 | 1.10.0 | 1.10.0 | bump candidate (runtime, needs review) | fastapi needs only `>=0.46.0` |
| `torch` | 2.14.1+cpu | 2.15.0 | 2.14.1 | current under cooldown; documented exception | 2.15.0 is 4 days old (`2.15.0+cpu` cp312 manylinux wheel is on the CPU index); a bump touches `requirements-torch.txt`, `environment.yml` and the hardcoded CI cache keys (dep-guard D8) |
| `tzdata` | 2026.5 | 2026.6 | 2026.5 | current under cooldown | test-only |
| `uvicorn` | 0.54.0 | 0.54.0 | — | current | |
| `websockets` | 15.0.1 | 17.4 | 17.3 | bump candidate (major, needs review) | see "Changed since 2026-10-20" |

## Changed since 2026-10-20

- **`huggingface-hub` 2.x is no longer compatibility-blocked.** The 10-20
  sweep, and `verify-deps` SKILL.md's Gotchas, record that
  `sentence-transformers==6.1.0` requires `huggingface-hub<2.0.0`. That is
  still true of 6.1.0, but `sentence-transformers` 6.2.0 (11 days old)
  requires `huggingface-hub<3.0.0,>=1.3.0`, and the locked
  `transformers==5.20.2` already allows `huggingface-hub<3.0,>=1.31.0`. A
  2.x hub is therefore reachable as a **pair** bump (`sentence-transformers`
  6.2.0 + `huggingface-hub` 2.3.0), not standalone. Major version: read the
  hub 2.0 changelog against `retrieval/embeddings.py` and
  `retrieval/rerank.py` model fetch/offline paths, and the
  `HF_HUB_OFFLINE` latch CLAUDE.md §4 describes, before taking it.
- **`websockets` is a floor, not a ceiling.** The 10-20 sweep filed
  `websockets` 15.0.1 as a documented exception. The documented reason
  (`constraints.txt`/`pyproject.toml`: "langgraph-sdk imports
  websockets.asyncio at graph import time; keep this direct so legacy/no-deps
  paths cannot strand the app on websockets 12.x") is a lower bound.
  `langgraph-sdk` 0.4.11 needs `websockets>=14`, `langsmith` 0.14.17
  `>=15.0`, `uvicorn` 0.54.0 `[standard]` `>=13.0`. Nothing caps it, so 17.3
  is an ordinary major-version candidate.
- **Stale manifest comment, still not fixed (on purpose):**
  `constraints.txt` lines 16-18 still say "2.13.5 is the latest pydantic on
  PyPI" and that no pydantic pairs with a newer pydantic-core. PyPI has had
  `pydantic` 2.14.1 (→ `pydantic-core==2.50.1`) for 21 days. Editing the
  comment re-hashes `constraints.txt` and fails the lock contract, so it rides
  the next re-lock, as the 10-20 sweep also said.
- Lock count is 20 (was 19); #1765 added the Numbat hash lock.

## Bump candidates worth a decision

Every item needs the arm64 macOS re-lock before it can merge; the
files-to-edit for each package are the non-empty columns of its
`extract_pins.py` row, plus the extra inputs `verify-deps` SKILL.md Gotchas
names. Ordered by how much review each needs, smallest first:

1. **Free patches if re-locking anyway:** `certifi` 2026.10.23,
   `setuptools` 84.2.1, `pydantic-settings` 2.16.1, `langgraph` 1.2.17 with
   `langsmith` 0.14.12, `ruff` 0.17.2 (dev), `hatchling` 1.33.0 (build only,
   no lock input).
2. **Web stack (minor):** `fastapi` 0.143.3→0.162.0 and `starlette`
   1.8.0→1.10.0. Read the release notes for the request-body and
   `TestClient` paths `gate.py` relies on
   (`docs/analysis/TESTCLIENT_HTTPX_DEPRECATION.md`).
3. **pydantic pair:** 2.13.5→2.14.1 with `pydantic-core` 2.46.5→2.50.1;
   move dep-guard `_PYDANTIC_LOCKSTEP`, CLAUDE.md §4 and the stale
   `constraints.txt` comment in the same commit. `schemas/api.py` uses
   `strict=True`, so a minor can change coercion behavior.
4. **LangChain minor:** `langchain-core` 1.6.12→1.7.0; `check_otel.py`
   `LAST_VERIFIED_VENDOR_PINS` records the current value, so re-grep the
   installed sources before updating it.
5. **Majors:** `sentence-transformers` 6.2.0 + `huggingface-hub` 2.3.0 (the
   pair above) and `websockets` 17.3.

Documented exceptions, unchanged: `numpy` <2, `chromadb`, `torch` (+cpu, and
2.15.0 is inside the cooldown).

## What this sweep did not do

- No `mamba env create --dry-run` (no conda in the sandbox): `environment.yml`
  is **not dry-run-verified this pass**; dep-guard D9 checked its 28
  cross-pinned packages agree with the pip manifests.
- No Docker image build (no daemon). The Dockerfile's install contract is
  E5's static check plus the lock dry-run above, which is the same command
  the Dockerfile runs. The compose file was rendered with
  `docker compose config --quiet`, which needs no daemon.
- No `uv` run; `uv` is used only for lock generation on the macOS host.
- No pytest run and no CI leg; `--dry-run` validates resolution, not the
  build or link step (the wheel build above is the one real build).
