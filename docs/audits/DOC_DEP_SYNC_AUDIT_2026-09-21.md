# Doc-Sync / Dep-Sync Audit — 2026-09-21

Scope: a fable-protocol-driven resync of `claude/fable-protocol-resync-rgi1c1`
against `origin/main`, followed by a thorough documentation-drift pass
(`doc-sync`) and a thorough dependency pass (`dep-guard` + `verify-deps`,
including a live PyPI currency and CVE sweep). No code behavior changed by
this audit; one stale line in a skill doc was corrected.

## 1. Branch resync

`git fetch origin main` at audit time resolved to `f4187882e268a8889e8b016db7b2b430efc9a39f`,
identical to the branch's own `HEAD`. The branch was already even with
`origin/main` (`ahead 0, behind 0`, confirmed by both the session's own
`sync-check` hook and a fresh fetch) — no merge or rebase was needed.

## 2. doc-sync

### Automated checker (`.claude/skills/doc-sync/doc_sync.py`)

All eleven structured checks (D1–D11 plus the M5-doctrine cross-check) passed
clean: **0 drift item(s) found**. Skills-on-disk vs. CLAUDE.md (22/22),
console entry points (7/7), config numbers, banned-pattern count, all 35
`gate.py` routes named in both CLAUDE.md and `setup-guide.md`, hook claims,
the 12-node graph count, and README path/link/module-ref integrity across all
39 READMEs.

### Manual pass (prose, not covered by the checker)

`doc_sync.py`'s own documented scope is structured facts only; skill-body
prose is manual-pass territory (per `cyclaw-gotchas` SKILL.md's own Gotchas
section). One stale operational claim was found and fixed:

- **`.claude/skills/cyclaw-gotchas/SKILL.md`** claimed `driver.sh checks`
  reports `1 warning` on a clean tree ("the known C9 hybrid-posture
  warning"). Verified against the actual checker (`check_config.py`) and its
  git history: commit `993f439` flipped C9's polarity from "warn if the
  shipped config is hybrid+enabled" to "warn if the committed config
  diverges from the *documented* shipped provider posture" — and that
  documented posture has been hybrid with `grok`/`claude` enabled since
  CLAUDE.md's 2026-08-07 provider armament. A clean tree today reports **0
  warnings** (C9 shows `ok`), not 1. Fixed the line to describe the current
  behavior and flag a `1 warning` result as drift-to-investigate going
  forward, not the baseline.

No other prose drift was found in the sampled skill/rule files touched by
this session's own reading (CLAUDE.md, PROJECT_RULES.md, `cyclaw-gotchas`,
`verify-deps`).

## 3. dep-sync

### Static pin agreement

- `dep-guard` (`.claude/skills/dep-guard/check_deps.py`): **0 failures, 0
  warnings** across D1–D10 (pydantic/pydantic-core lock-step, numpy `<2`,
  torch `+cpu`, uvicorn no-extras, exact pins, cross-file agreement,
  CI `--cov` coverage-source parity).
- `extract_pins.py` (requirements.txt ↔ constraints.txt cross-check, the pair
  `dep-guard` doesn't compare): **no drift**.
- `check_env_drift.py --strict` (E1–E7: workflow tool-version consistency,
  Python-version agreement across 4+ surfaces, undeclared/orphaned imports,
  install-surface scope, the Docker install contract, the rest of the Docker
  surface, and pin-reachability): **0 failures, 0 warnings**.

### Install-surface dry-runs (Step 4)

- `pip install --dry-run -e . -c constraints.txt --extra-index-url
  https://download.pytorch.org/whl/cpu`: **unverified in this sandbox** —
  the egress proxy denies `download.pytorch.org` outright (documented,
  per-organization policy; see `cyclaw-gotchas` SKILL.md), so this is a
  sandbox limitation, not a tree defect. The venv build for this session hit
  the same denial and fell back to plain PyPI `torch` per the documented
  recipe.
- `docker compose config --quiet`: **passes** (renders clean; no daemon
  required for this check).

### PyPI currency + CVE sweep (Step 5)

Swept all 39 pinned packages that resolve to a real PyPI project (torch and
the conda-only `pytorch`/`python-tzdata` entries excluded — no comparable
PyPI-JSON currency check applies) against `https://pypi.org/pypi/<pkg>[/<ver>]/json`,
reading each pinned version's own `vulnerabilities` array (OSV data PyPI
serves directly — no `pip-audit` install needed).

**CVE findings: zero new.** Two packages carry OSV advisories on their
currently pinned/shipped version, and both are pre-existing, dated,
risk-accepted entries already in `SECURITY.md` — re-confirmed, not
newly discovered:

| Package | Advisory | Status in `SECURITY.md` |
|---|---|---|
| `nltk==3.10.3` (matches PyPI latest) | PYSEC-2026-3740 / CVE-2026-81726 / GHSA-8mgp-746c-j5xp — unpatched (`fixed_in: []`), a `pathsec` sandbox-bypass in unused model-artifact APIs (`TransitionParser`, `AveragedPerceptron`, `PerceptronTagger`, `save_maxent_params`) | Accepted 2026-09-04, cited by its PYSEC id; CyClaw only ever calls `PorterStemmer.stem()` from this package, never the vulnerable APIs |
| `chromadb==1.5.9` (matches PyPI latest) | CVE-2026-45829/45830/45831/45833 — all unpatched, all scoped to the Chroma HTTP FastAPI server (`HttpClient`/`/api/v2`) | Accepted, dated 2026-08-25/26; CyClaw uses the embedded `PersistentClient` exclusively — the vulnerable server surface is never instantiated |

No action needed on either; both remain correctly risk-accepted under the
existing rationale. (First-pass parallel sub-agents queried the same OSV data
and initially reported these as "new" — cross-checked directly against
`SECURITY.md` before including anything here, since a stale CVE claim is
exactly the kind of confabulation-risk this audit exists to avoid. They were
not new.)

**Non-CVE currency gaps** (informational only — no bump applied; a version
bump is Medium–High risk per CLAUDE.md §7 / the `verify-deps`/`dep-guard`
guardrails and needs explicit user approval before it happens):

| Package | Pinned | Latest | Gap |
|---|---|---|---|
| `websockets` | 15.0.1 | 17.1 | 2 major versions |
| `pydantic-core` | 2.46.5 | 2.49.0 | locked in step with `pydantic` (already at its own latest, 2.13.5) — bumping one alone breaks the pair `dep-guard` enforces |
| `langsmith` | 0.13.0 | 0.14.0 | 1 minor |
| `deepagents` | 0.6.12 | 0.7.16 | 1 minor+patch (note: still imported by the retired-but-kept `deepagent_github/builder.py`, disarmed by default) |
| `tzdata` | 2026.2 | 2026.4 | 2 releases |
| `langchain-core` | 1.6.3 | 1.6.4 | 1 patch |
| `langchain-openai` | 1.6.2 | 1.6.3 | 1 patch |
| `langgraph` | 1.2.11 | 1.2.12 | 1 patch |
| `nemoguardrails` | 0.24.0 | 0.24.1 | 1 patch |
| `mypy` | 2.3.0 | 2.3.1 | 1 patch (dev-tool-only, low blast radius) |

Every other checked package (`bandit`, `cel-python`, `fastapi`, `httpx`,
`huggingface-hub`, `langchain`, `langchain-anthropic`,
`langchain-google-genai`, `langchain-xai`, `numpy` [intentionally held `<2`],
`onnxruntime`, `pgvector`, `psycopg`, `psycopg-binary`, `pydantic`,
`pydantic-settings`, `pygments`, `pyodbc`, `pytest`, `pytest-asyncio`,
`pytest-cov`, `pyyaml`, `rank-bm25`, `ruff`, `sentence-transformers`,
`setuptools`, `starlette`, `uvicorn`) matches its own latest PyPI release.

## 4. Verdict

- **invariant-guard:** 46 passed, 0 failed (all six invariants + supporting
  guards intact; unaffected by this audit's one docs-only edit).
- **doc-sync:** 0 automated drift; 1 manual-pass finding, fixed.
- **dep-guard / verify-deps static:** 0 failures, 0 warnings.
- **PyPI currency + CVE sweep:** 0 new CVEs; 10 non-urgent bump candidates
  identified and left untouched pending explicit approval.
- **Fix applied:** `.claude/skills/cyclaw-gotchas/SKILL.md` — corrected the
  stale "config-guard reports 1 warning on a clean tree" claim to match C9's
  current (post-#993f439) semantics.

## Risk to monitor

None of the identified bump candidates carry a CVE, so none are urgent. The
two furthest behind — `websockets` (2 majors) and `pydantic-core` (paired
with `pydantic`, which is already current) — are the ones worth a deliberate
look first if/when a dependency-bump pass is authorized; `websockets` in
particular is pinned direct in `pyproject.toml`/`constraints.txt` for
`langgraph-sdk` import-time compatibility per existing pin-notes, so a bump
there should re-verify that compatibility, not just re-run the test suite.
