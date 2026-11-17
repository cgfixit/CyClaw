# Dependency sync audit — 2026-11-17

**Scope:** manifests, locks, install commands and the Docker surface on
`origin/main` @ `426d1cc` (after PR #1845), with no open pull requests. Run
from a Linux cloud sandbox with `/usr/bin/python3.12` (3.12.3), PyPI and
`download.pytorch.org` both reachable, `api.osv.dev` refused by the egress
proxy (HTTP 403), and the Docker CLI present without a daemon. Reports only;
**no pin was changed.** The hashed `locks/` regenerate only on the arm64 macOS
host (`scripts/refresh-runtime-lock.sh`, `scripts/refresh-ci-locks.sh`), and
`scripts/check_lock_contract.py` hashes the manifests into every lock's
recorded inputs, so any manifest edit here would turn the lock contract red
until the owner re-locks.

The previous sweep is
[2026-11-02](2026-11-02-dependency-currency-sweep.md). Since then the pins
moved in #1810 (OAuthLib 4.0.1, Python container base) and #1834
(`opentelemetry-api` 1.45.2 for CVE-2026-126360, with the Conda OpenTelemetry
set moved to the `pip:` tail).

## Summary

```
Verify Deps: 54 packages checked (45 constraints.txt pins + 3 environment.yml-only OTel pins + hatchling + pip + 4 other workflow tools) | 29 behind latest | 1 package with advisories on the pin (chromadb, all 4 accepted in SECURITY.md) | 0 new advisories since 2026-11-02
Lock-wide advisories: 143 locked Linux distributions (runtime + test + torch locks) queried per release; chromadb is the only hit
dep-guard:            PASS (D1-D11, 0 failures, 0 warnings)
requirements drift:   none (requirements.txt + requirements-test.txt <-> constraints.txt); --strict exit 0
Env drift (E1-E7):    0 failure(s), 0 warning(s), --strict exit 0; no E3 names reported (103 imported modules resolve)
verify-deps verify:   OK (24 checks, every mutation trips its rule)
otel-hardening:       check_otel.py --strict 0 failures, 0 warnings
Lock contract:        scripts/check_lock_contract.py passed
Lock <-> manifest:    all 20 lock files agree with constraints.txt on every shared pin (168 shared entries; +cpu local tag ignored)
Install surfaces:     locks (torch real install + runtime/test dry-run)=PASS editable=PASS legacy=PASS wheel-build=PASS compose-render=PASS conda=not dry-run-verified docker-build=not run (no daemon)
Verdict:              no pin changed; one time-boxed exception expires in 14 days; findings for review below
```

## Install surfaces (Step 4)

Each command ran in a **fresh** Python 3.12.3 venv with `pip==26.2.2` (the
CI/Dockerfile pin), so no pre-installed package could make a resolve pass
conditionally. The torch lock is a real install by design: the runtime lock
omits torch, and its `sentence-transformers` asks for `torch>=2.2`.

| # | Command (fresh venv) | Result | Evidence |
|---|---|---|---|
| 1a | `pip install --require-hashes --no-deps -r locks/requirements-torch-lock-linux.txt --index-url https://download.pytorch.org/whl/cpu` | PASS | rc 0; `pip show torch` reports `2.14.1+cpu` |
| 1b | `pip install --dry-run --require-hashes -r locks/requirements-lock-linux.txt` | PASS | rc 0 |
| 1c | `pip install --dry-run --require-hashes -r locks/requirements-test-lock-linux.txt` | PASS | rc 0 |
| 2 | `pip install --dry-run -e . -c constraints.txt --extra-index-url https://download.pytorch.org/whl/cpu` | PASS | rc 0 |
| 3 | `pip install --dry-run -r requirements.txt -r requirements-test.txt -c constraints.txt --extra-index-url https://download.pytorch.org/whl/cpu` | PASS | rc 0 |
| 4 | `pip wheel --no-deps -w <tmp> .` | PASS | builds `cyclaw-1.9.0-py3-none-any.whl` through hatchling |
| 5 | `docker compose config --quiet` | PASS | rc 0 with no daemon |

The dry-runs ran with `-q`, so this pass records exit codes rather than the
resolved package list; the 2026-11-02 sweep recorded the resolved versions for
the same commands, and no manifest has moved since except the two pins above.

## Advisories on pinned versions (PyPI `vulnerabilities`, per-release endpoint)

Every package was queried at `/pypi/<package>/<pinned-version>/json`, not the
project endpoint, whose `vulnerabilities` array describes only the latest
release. `api.osv.dev` was unreachable from this sandbox (proxy 403), so the
PyPI feed, which PyPI sources from OSV, is the only advisory source this pass.

This sweep also queried every pinned distribution in
`locks/requirements-lock-linux.txt`, `locks/requirements-test-lock-linux.txt`
and `locks/requirements-torch-lock-linux.txt` (143 in total, transitives
included), which earlier sweeps did not.

| Package | Pinned | Advisories reported | Status |
|---|---|---|---|
| `chromadb` | 1.5.9 | CVE-2026-45829 / PYSEC-2026-311 / GHSA-f4j7-r4q5-qw2c; CVE-2026-45830 / PYSEC-2026-3813 / GHSA-2wm9-hf6c-p5cr; CVE-2026-45831 / PYSEC-2026-3815 / GHSA-xph7-9rjv-w5fr; CVE-2026-45833 / PYSEC-2026-3814 / GHSA-36p7-vc44-83pf | All four accepted in `SECURITY.md` for the embedded `PersistentClient`-only posture, and suppressed consistently in `.osv-scanner.toml`, `.trivyignore.yaml`, `pip-audit.yml` and the `ci.yml` `allow-ghsas` list. 1.5.9 is still the latest release, and no advisory lists a `fixed_in`. Do not switch to the HTTP client or file a fix PR. |

No other pinned or locked distribution reports an advisory.
`opentelemetry-api` 1.45.2 (#1834) and `oauthlib` 4.0.1 (#1810) report none.

## Time-boxed exception due soon

`SECURITY.md`'s "Debian 12 container libraries" exception (issues #1629 /
#1757) **expires 2026-12-01**, 14 days after this sweep. It covers GnuTLS,
the krb5 libraries and `libtirpc3` in the `python:3.12-slim-bookworm` base,
last rechecked 2026-11-06 with no bookworm or trixie fix. It is outside this
skill's pin scope, but it is the only item in this report with a deadline: it
needs a recheck and either an extension with a reason or a base change before
that date.

## Currency table

Pinned column is `constraints.txt`, plus `hatchling` from `[build-system]`,
the three `environment.yml`-only OpenTelemetry pins, and the workflow-pinned
tools E1 inventories. Latest is PyPI `info.version` on 2026-11-17. **Newest
≥7d** is the newest non-yanked final release at least seven days old, the
cooldown the `.githooks` security gate states and Dependabot's
`cooldown: default-days: 7` applies. Conda-only names (`pytorch`,
`python-tzdata`) are omitted.

| Package | Pinned | Latest | Newest ≥7d | Class | Note |
|---|---|---|---|---|---|
| `actionlint-py` | 1.7.12.24 | 1.7.12.25 | 1.7.12.25 | bump candidate (workflow tool) | `ci.yml` workflow-lint job |
| `aiohttp` | 3.14.5 | 3.14.5 | — | current | |
| `bandit` | 1.9.4 | 1.9.4 | — | current | |
| `cel-python` | 0.5.0 | 0.5.0 | — | current | |
| `certifi` | 2026.10.19 | 2026.10.23 | 2026.10.23 | bump candidate (constraints-only transitive) | CA bundle refresh; unchanged since 2026-11-02 |
| `chromadb` | 1.5.9 | 1.5.9 | — | documented exception | see Advisories |
| `fastapi` | 0.143.3 | 0.163.1 | 0.162.2 | bump candidate (runtime, needs review) | 0.163.1 is 1 day old; 0.163.1 still needs only `starlette>=0.46.0`, `pydantic>=2.9.0`, `opentelemetry-api>=1.44.0` (all satisfied by current pins) |
| `fastembed` | 0.9.1 | 0.9.1 | — | current | |
| `flake8` | 7.3.0 | 7.5.0 | 7.5.0 | bump candidate (workflow tool) | advisory WPS lane in `lint.yml` |
| `google-re2` | 1.1.20251105 | 1.1.20251105 | — | current | |
| `hatchling` | 1.32.4 | 1.33.0 | 1.33.0 | bump candidate (build tool) | `[build-system].requires` only; not a lock input |
| `httpx` | 0.28.1 | 0.28.1 | — | current | |
| `huggingface-hub` | 1.32.0 | 2.4.0 | 2.4.0 | major, needs review | reachable only as a pair with `sentence-transformers` ≥6.2.0 (`huggingface-hub<3.0.0,>=1.3.0`); locked `transformers` 5.20.2 allows `<3.0,>=1.31.0` |
| `jmespath` | 1.1.0 | 1.1.0 | — | current | |
| `langchain-core` | 1.6.12 | 1.8.1 | 1.7.6 | bump candidate (runtime, needs review) | 1.8.1 is 1 day old; needs `langsmith>=0.14.9` (pinned 0.14.11 satisfies) |
| `langgraph` | 1.2.15 | 1.2.22 | 1.2.20 | bump candidate (runtime, needs review) | patch; needs `langchain-core>=1.4.7` |
| `langsmith` | 0.14.11 | 0.14.17 | 0.14.17 | bump candidate (constraints-only transitive) | moves with langchain-core |
| `lark` | 1.3.1 | 1.3.1 | — | current | |
| `mypy` | 2.4.0 | 2.4.1 | 2.4.1 | bump candidate (dev tool) | out of cooldown since the last sweep |
| `nemoguardrails` | 0.24.1 | 0.24.1 | — | current | |
| `nltk` | 3.10.4 | 3.10.4 | — | current | |
| `numpy` | 1.26.4 | 2.5.5 | 2.5.4 | documented exception | held `<2` (chromadb/onnxruntime; CLAUDE.md §4) |
| `oauthlib` | 4.0.1 | 4.0.1 | — | current | #1810 |
| `onnxruntime` | 1.31.0 | 1.32.0 | 1.31.1 | bump candidate (runtime, needs review) | 1.32.0 is 3 days old and needs `protobuf>=4.25.8` (locked 7.36.2 satisfies); telemetry-vendor pin in `check_otel.py` and literals in `otel-hardening/verify.sh` |
| `opentelemetry-api` | 1.45.2 | 1.45.2 | — | current | #1834 |
| `opentelemetry-exporter-otlp-proto-grpc` | 1.45.1 | 1.45.2 | 1.45.2 | bump candidate (lock transitive) | `environment.yml` pip tail; matches the hashed runtime lock on purpose (see its comment), so it moves only with a re-lock |
| `opentelemetry-sdk` | 1.45.2 | 1.45.2 | — | current | `environment.yml` pip tail |
| `opentelemetry-semantic-conventions` | 0.66b2 | 0.66b2 | — | current | `environment.yml` pip tail |
| `packaging` | 26.3 | 26.3 | — | current | |
| `pendulum` | 3.3.0 | 3.3.0 | — | current | |
| `pgvector` | 0.5.1 | 0.5.1 | — | current | |
| `pillow` | 13.0.0 | 13.0.0 | — | current | |
| `pip` | 26.2.2 | 26.3 | 26.3 | bump candidate (workflow/Dockerfile pin) | 16 workflow sites agree (E1); out of cooldown |
| `psycopg` / `psycopg-binary` | 3.3.6 | 3.3.9 | 3.3.8 | bump candidate (extras-only) | `postgres` extra; also `scripts/ci-lock-inputs/extra-postgres.txt` |
| `pydantic` | 2.13.5 | 2.14.3 | 2.14.3 | bump candidate (runtime, needs review) | lock-step: 2.14.3 hard-pins `pydantic-core==2.50.4`; `kubernetes` 37.0.2 requires `pydantic>=2.14.2`, so the current pin is what holds the lock on `kubernetes` 37.0.1 (`environment.yml` comment) |
| `pydantic-core` | 2.46.5 | 2.50.4 | 2.50.4 | bump candidate (runtime, needs review) | constraints-only; moves only with pydantic |
| `pydantic-settings` | 2.16.0 | 2.16.3 | 2.16.2 | bump candidate (constraints-only transitive) | chromadb transitive |
| `pygments` | 2.21.0 | 2.21.0 | — | current | |
| `pytest` | 9.1.1 | 9.2.0 | 9.2.0 | bump candidate (dev tool) | out of cooldown since the last sweep |
| `pytest-cov` | 7.1.0 | 7.1.0 | — | current | |
| `pyyaml` | 6.0.3 | 6.0.3 | — | current | |
| `rank-bm25` | 0.2.2 | 0.2.2 | — | current | |
| `ruff` | 0.17.1 | 0.17.5 | 0.17.4 | bump candidate (dev tool) | also the `lint.yml` pin and its `ruff==` comment; re-run ruff over the tree before pinning |
| `sentence-transformers` | 6.1.0 | 6.3.0 | 6.2.0 | bump candidate (runtime, needs review) | 6.2.0+ unlocks huggingface-hub 2.x; 6.3.0 needs `transformers<6.0.0,>=5.0.0` |
| `setuptools` | 84.1.0 | 84.2.1 | 84.2.1 | bump candidate (constraints-only floor) | floor for PYSEC-2026-3447; free patch if re-locking anyway |
| `sqlite-vec` | 0.1.9 | 0.1.9 | — | current | |
| `starlette` | 1.8.0 | 1.10.0 | 1.10.0 | bump candidate (runtime, needs review) | fastapi needs only `>=0.46.0` |
| `torch` | 2.14.1+cpu | 2.15.0 | 2.15.0 | bump candidate; documented exception | now 19 days old, out of cooldown. `2.15.0+cpu` cp312 wheels exist on the CPU index (manylinux x86_64/aarch64, win_amd64/arm64) and PyPI has `macosx_14_0_arm64`. A bump touches `requirements-torch.txt`, `environment.yml` (`pytorch=2.14.1=cpu*`), the hardcoded CI cache keys (dep-guard D8) and all three torch locks |
| `tzdata` | 2026.5 | 2026.6 | 2026.6 | bump candidate (test-only) | `test` extra + `requirements-test.txt` |
| `uvicorn` | 0.54.0 | 0.54.0 | — | current | |
| `websockets` | 15.0.1 | 17.4 | 17.4 | bump candidate (major, needs review) | a floor, not a ceiling (2026-11-02 sweep): nothing caps it |
| `wemake-python-styleguide` | 1.6.2 | 1.8.1 | 1.8.1 | bump candidate (workflow tool) | advisory WPS lane in `lint.yml` |
| `zizmor` | 1.28.0 | 1.32.0 | 1.32.0 | bump candidate (workflow tool) | blocking workflow-lint job in `ci.yml`; a newer zizmor can add audits, so run it over `.github/workflows/` before pinning |

## Changed since 2026-11-02

- **Out of cooldown:** `torch` 2.15.0, `pytest` 9.2.0, `mypy` 2.4.1 and
  `tzdata` 2026.6 were inside the seven-day window last sweep and are now
  ordinary candidates. `torch` keeps its documented `+cpu` handling.
- **New releases inside the cooldown:** `fastapi` 0.163.1, `langchain-core`
  1.8.1, `langgraph` 1.2.22, `onnxruntime` 1.32.0, `sentence-transformers`
  6.3.0, `ruff` 0.17.5, `psycopg` 3.3.9 and `pydantic-settings` 2.16.3 are
  under seven days old; the Newest ≥7d column gives the release to evaluate
  instead.
- **pydantic has a second reason to move.** Besides the existing lock-step
  candidate (2.14.3 with `pydantic-core` 2.50.4), `kubernetes` 37.0.2 (a
  chromadb transitive) now requires `pydantic>=2.14.2`. The 2.13.5 pin is
  what keeps the lock on `kubernetes` 37.0.1, as #1810's `environment.yml`
  comment records. The pair bump still moves dep-guard `_PYDANTIC_LOCKSTEP`,
  CLAUDE.md §4 and the stale `constraints.txt` comment in the same commit.
- **Workflow tools are now in the table.** E1 already checks that
  `actionlint-py`, `flake8`, `wemake-python-styleguide` and `zizmor` agree
  across workflows; this sweep adds their PyPI currency. All four are behind,
  none reports an advisory.
- **Unchanged:** the stale `constraints.txt` comment ("2.13.5 is the latest
  pydantic on PyPI", line 16) still rides the next re-lock, because editing
  it re-hashes `constraints.txt` and fails the lock contract.

## Small manifest comment drift (flagged, not fixed)

`environment.yml` line 53 says the PyPI `tzdata==2026.5` pin lives in
"requirements.txt / pyproject / constraints". The pin table shows it lives in
`requirements-test.txt` (and the `test` extra and `constraints.txt`), not
`requirements.txt`. The comment's real point, that conda-forge's
`python-tzdata=2026.2` is a different package from its `tzdata`, is correct.
`environment.yml` is not a lock input, so the fix needs no re-lock, but it is
left for the next manifest-touching change to keep this report docs-only.

## Bump candidates worth a decision

Every item except `hatchling` and the workflow tools needs the arm64 macOS
re-lock before it can merge. The files to edit for each package are the
non-empty columns of its `extract_pins.py` row, plus the extra inputs that
`verify-deps` SKILL.md Gotchas names. Ordered by how much review each needs,
smallest first:

1. **Free patches if re-locking anyway:** `certifi` 2026.10.23,
   `setuptools` 84.2.1, `pydantic-settings` 2.16.2,
   `opentelemetry-exporter-otlp-proto-grpc` 1.45.2.
2. **Dev and workflow tools (no runtime effect, can change lint results):**
   `pytest` 9.2.0, `mypy` 2.4.1, `ruff` 0.17.4, `tzdata` 2026.6, `pip` 26.3,
   `zizmor` 1.32.0, `actionlint-py` 1.7.12.25, `flake8` 7.5.0,
   `wemake-python-styleguide` 1.8.1, and `hatchling` 1.33.0 (build only, no
   lock input).
3. **Web stack (minor):** `fastapi` 0.143.3→0.162.2 and `starlette`
   1.8.0→1.10.0. Read the release notes for the request-body and
   `TestClient` paths `gate.py` relies on
   (`docs/analysis/TESTCLIENT_HTTPX_DEPRECATION.md`).
4. **pydantic pair:** 2.13.5→2.14.3 with `pydantic-core` 2.46.5→2.50.4 (see
   "Changed since"). `schemas/api.py` uses `strict=True`, so a minor can
   change coercion behavior.
5. **LangChain family and ONNX:** `langchain-core` 1.6.12→1.7.6,
   `langgraph` 1.2.15→1.2.20, `langsmith` 0.14.11→0.14.17 and `onnxruntime`
   1.31.0→1.31.1. All four are recorded in `check_otel.py`
   `LAST_VERIFIED_VENDOR_PINS` (and `onnxruntime` in three
   `otel-hardening/verify.sh` literals), so re-grep the installed sources
   for telemetry changes before updating them.
6. **torch:** 2.14.1→2.15.0 across all three torch locks and the four torch
   surfaces (`constraints.txt`, `pyproject.toml`, `requirements-torch.txt`,
   `environment.yml`) plus the D8 cache keys.
7. **Majors:** `sentence-transformers` 6.2.0 + `huggingface-hub` 2.x (the
   pair; read the hub 2.0 changelog against `retrieval/embeddings.py` and
   `retrieval/rerank.py` and the `HF_HUB_OFFLINE` latch in CLAUDE.md §4; both
   are also `LAST_VERIFIED_VENDOR_PINS` entries), and `websockets` 17.4.

Documented exceptions, unchanged: `numpy` <2 and `chromadb`.

## What this sweep did not do

- No `mamba env create --dry-run` (no conda in the sandbox): `environment.yml`
  is **not dry-run-verified this pass**; dep-guard D9 checked its 31
  cross-pinned packages agree with the pip manifests.
- No Docker image build (no daemon). The Dockerfile's install contract is
  E5's static check plus the lock commands above, which are the same commands
  the Dockerfile runs. The compose file was rendered with
  `docker compose config --quiet`, which needs no daemon.
- No direct OSV query (`api.osv.dev` refused by the sandbox proxy) and no CVE
  web search; advisories come only from PyPI's per-release feed.
- No `uv` run; `uv` is used only for lock generation on the macOS host.
- No pytest run and no CI leg; `--dry-run` validates resolution, not the
  build or link step (the wheel build above is the one real build).
