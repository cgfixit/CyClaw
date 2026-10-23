---
name: verify-deps
description: Verify CyClaw's four install surfaces (pyproject+pip, requirements.txt+pip, Docker, environment.yml) agree with each other, upstream PyPI, and non-manifest pins (workflow tool/Python versions, undeclared imports, the Docker torch pin). Extends dep-guard's static checks with a real install dry-run and a PyPI currency + CVE sweep; reports only, never auto-bumps a pin. Use when asked to verify/audit dependencies, check drift after a merge, or before a dependency-heavy release. For pin-agreement alone (no network), use dep-guard instead.
---

# Verify Deps

**Persona:** You are a supply-chain reviewer for CyClaw answering a broader
question than `dep-guard`: not just *do the pins agree with each other*, but
*do the pins agree with each other **and** still reflect a defensible choice
against what's actually available upstream, across every real way someone
installs this project*. You report; you do not unilaterally bump a runtime
dependency.

**Why this skill exists, and how it differs from `dep-guard`:** `dep-guard`
is a fast, pure-stdlib, no-network static checker — it is the correct tool
for "did this PR break a pin invariant," and it should stay that way (no
network dependency in a merge gate). But it has two blind spots by design:
it reads `requirements*.txt` only for the NeMo contract (D11), never for pin
agreement, and it cannot tell you whether `numpy==1.26.4` is still a
reasonable choice today versus when it was pinned, because that requires a
live PyPI lookup. This skill closes both gaps.

It was built after two install-command-shaped bugs that no pin-agreement
check could see. In 2026-07 the "preferred" `uv pip install` recipe, executed
as the Dockerfile's primary path, had been failing silently and falling
through to its pip fallback on every build. On 2026-09-11 the rewritten uv
line failed again, this time on a `setuptools` pin: the PyTorch CPU index
mirrors `setuptools` at another version and uv's default `first-index`
strategy refuses to consult PyPI for a package an earlier index already
carried, so `2>/dev/null ||` sent every build down the pip branch while CI
stayed green. uv was removed from the Dockerfile (it now installs the hashed
`locks/`, pip only), and E5 fails any dependency-install `RUN` that redirects
stderr or branches on `||`. The lesson behind Step 4: the pins can agree
perfectly while the command that consumes them is broken.

---

## The install surfaces are not four copies of one list

This is the distinction most reviews get wrong, and getting it wrong produces
*false* drift findings — "package X is in `constraints.txt` but not
`requirements.txt`, that's drift" is usually the checker being wrong, not the
tree:

| Surface | What it installs | Extras? |
|---|---|---|
| Hashed locks: `pip install --require-hashes -r locks/requirements-{torch,,test}-lock-<os>.txt` (CLAUDE.md §8, `driver.sh venv`, the Dockerfile) | The documented install: the torch CPU wheel first (`--no-deps`, CPU index on Linux/Windows, plain torch on macOS), then the fully resolved runtime and test sets. Generated from the manifests below by `scripts/refresh-runtime-lock.sh` / `refresh-ci-locks.sh` on arm64 macOS; `scripts/check_lock_contract.py` refuses locks whose recorded inputs no longer match `constraints.txt`/`pyproject.toml` | **None** — a lock is one resolved set |
| `pip install -r requirements.txt -c constraints.txt` | Base runtime and NeMo, **torch deliberately absent** (its header says so; test tools live in `requirements-test.txt`). Declares itself a **legacy compatibility surface** kept in sync with `pyproject.toml`/`constraints.txt` for older CI/tools | **None.** Zero extras, by design |
| `pip install -e ".[<extra>]" -c constraints.txt` | The base dependencies in `pyproject.toml` `[project.dependencies]`, plus whichever extras are named | **Yes — the only surface that can install one** |
| `Dockerfile` (+ `docker-compose.yml`, `.dockerignore`, `.github/workflows/publish-ghcr.yml`) | `pip install --upgrade pip==<ci pin>`, then `--require-hashes` from `locks/requirements-torch-lock-linux.txt` and `locks/requirements-lock-linux.txt` — one path, no `||` branch, no stderr redirect, no `torch==` line of its own. Compose runs the image (loopback publish, runtime-state mounts), `.dockerignore` shapes the build context, `publish-ghcr.yml` ships the image compose pulls — E5/E6 pin the four files to each other | **None** — the hashed-lock surface, containerized |
| `conda env create -f environment.yml` | Base runtime + test/dev tools from conda-forge, plus a `pip:` tail for NeMo, Chroma/FastAPI/Starlette, and the remaining PyPI packages | **None** |

Two consequences that drive every judgement in this skill:

**`constraints.txt` is not an install surface.** It is a version ceiling applied
*to* the other three. It legitimately pins packages that **no** surface installs
by default — every extras-only package (`psycopg`, `pgvector`) plus
pinned transitives. A package present in `constraints.txt`
and absent from `requirements.txt` is the **designed** state, not drift. The
drift-shaped question is the reverse: a package installed by a surface but
*unpinned* in `constraints.txt`.

**Conda installs Chroma, FastAPI, Starlette, and NeMo from PyPI.**
Their pins match the base metadata. The older conda-forge Chroma build forced
an incompatible FastAPI pin, so this trio now lives in the `pip:` subsection.
The exporter floor and Conda PyTorch/setuptools packaging limits remain
documented in `environment.yml`. Verify the installed environment with
`python -m pip check` and `python -m guardrails.verify_install` without adding
an extra. The smoke requires the real engine, shipped rules, exact allow/refuse
verdicts, with offline loader flags set. Docker also disables networking.
Fallback success is not NeMo verification.

---

## Run

### Step 1 — Static pin agreement (delegates to dep-guard)

```bash
python3 .claude/skills/dep-guard/check_deps.py
```

Run this first — it's the fast, authoritative check for pyproject.toml
`<->` constraints.txt `<->` environment.yml agreement (D1-D11) and the
load-bearing pin invariants (pydantic lock-step, numpy `<2`, torch `+cpu`,
uvicorn no-extras). Don't re-implement any of this; if it fails, fix that
first — the rest of this skill assumes clean pins to start from.

### Step 2 — requirements.txt cross-check + normalized pin table

```bash
python3 .claude/skills/verify-deps/extract_pins.py
```

Prints a `package × {pyproject.toml, constraints.txt, requirements.txt,
environment.yml}` table and flags any `requirements.txt` `<->`
`constraints.txt` disagreement — the one pair `dep-guard` never compares.
Add `--json` for a machine-readable version if you're about to hand the
package list to Step 3.

By default this is reporting-only (exit 0 on a parseable tree, 3 if
`pyproject.toml`/`constraints.txt` are missing) — a drift line is a finding
to act on. `--strict` turns a `requirements*.txt` ↔ `constraints.txt` drift
into exit 2; `verify.sh` relies on that.

### Step 3 — Environment drift *outside* the pin manifests

```bash
python3 .claude/skills/verify-deps/check_env_drift.py     # add --strict to fail on warnings
```

Steps 1 and 2 both stop at the manifest boundary — they compare pin files to
other pin files. But CyClaw declares load-bearing environment dependencies in
places no manifest checker reads, and nothing cross-checks those. Seven classes:

- **E1 — tool versions pinned inline in workflow YAML** (`flake8`, `wemake`,
  `actionlint-py`, `zizmor`, and `pip` at over a dozen sites; the checker
  prints the live set). None appears in any manifest. The failure this
  catches is not a wrong version — it is the *same* tool pinned at two
  different versions in two jobs, which makes one lane's result silently
  unreproducible against the other's.
- **E2 — the Python version**, declared independently in `pyproject.toml`
  (`requires-python`), `Dockerfile` (`FROM python:`), `environment.yml`
  (`python=`), and every workflow's `python-version:`. Four places, no
  cross-check. Compares the concrete minor versions for equality and checks
  them against `requires-python`'s floor (a range that everything satisfies is
  correct, not drift).
- **E3 — a third-party module imported by source but declared in no manifest.**
  The class `dep-guard` cannot see by construction: it reads manifests and never
  reads imports. Walks first-party source with `ast`, skipping virtualenvs
  structurally (by their own `pyvenv.cfg`, not by guessing the directory name)
  and skipping `tools/` (operator-optional offline kits; not a CyClaw runtime
  install surface — see `tools/lora_finetune/requirements.txt`).
- **E4 — the install-surface scope contract** from the table above: asserts
  `requirements.txt` carries no extras-only package.
- **E5 — the Docker build's dependency-install contract**: asserts the
  Dockerfile installs from the hashed Linux locks with `--require-hashes` on a
  single pip path (no `||` fallback, no stderr redirect), never installs the
  test lock into the image, and that the torch the torch lock pins is the
  **same** release `constraints.txt` names — the Dockerfile's own history
  records the miss (constraints moved `2.12.1 -> 2.13.0`, the old fallback
  line did not, and it installed the old wheel then failed the constrained
  resolve). A "some `torch==` is present" check passed that tree.
- **E6 — the rest of the Docker surface**: `docker-compose.yml`,
  `.dockerignore`, and `.github/workflows/publish-ghcr.yml` must agree with
  the Dockerfile and each other. `.dockerignore` keeps the three COPYed
  manifests in the build context and keeps every runtime-state directory
  (`logs/`, `checkpoints/`, `index/`, `data/`, `.emb_cache/`) out of image
  layers; compose mounts each of those back in, publishes only on
  `127.0.0.1`, and agrees with `EXPOSE`/`CMD --port` on the container port;
  compose's default `CYCLAW_IMAGE_TAG` equals `pyproject.toml`'s `version`;
  `publish-ghcr.yml` builds `./Dockerfile` and pushes the `IMAGE_NAME` compose
  pulls. Each file is info-skipped when absent (the Docker surface may be the
  Dockerfile alone), never silently passed when present and incoherent.
- **E7 — a runtime pin no first-party module imports**: the reverse of E3,
  on E3's own import set so the two cannot disagree about scope. It **warns
  rather than fails**, because "not imported" is not "unused": a pin can be a
  transitive deliberately held on this surface (deleting it floats the real
  dependency), so every `_PINNED_NOT_IMPORTED` exemption names the package
  that pulls it (today only `websockets`, for `uvicorn[standard]`). `numpy`
  and `onnxruntime` are imported directly and carry no exemption.

Pure stdlib, no network, no install — same constraints as `dep-guard` and
`extract_pins.py`, so it runs in a fresh clone before pip does. Exits 0 with
warnings, 2 on a failure; `--strict` promotes warnings to a failure.

**A clean tree reports zero E3 warnings** (its first two findings,
`huggingface_hub` and `starlette`, were promoted to explicit pins on every
surface). Any new name this check reports requires investigation.

`pyodbc` (the old `mssql` extra) left every manifest with
`agentic/sqlconnect` in October 2026, so it no longer holds an
`_IMPORT_ALLOWLIST` entry (the allowlist is empty today). Keep the
allowlist an argued exception list — a new entry needs its reason written
next to it, or it becomes a silencer.

### Step 4 — Verify each install surface's primary command actually resolves

Static agreement doesn't prove the *command* works — the Dockerfile bug this
skill was born from had perfectly agreeing pins and a still-broken install
line. For each surface, dry-run the documented/executed primary command
against a real Python 3.12 venv:

Use the installer each surface actually names — `pip`, not `uv`. No
install surface runs `uv` (no workflow, no documented command, and since
2026-09-11 not the Dockerfile); `uv pip compile` is used only by the lock
*refresh* scripts. Dry-running `uv` here tests a command the repo does not
run, and (per the failure classes below) fails today for a reason that has
nothing to do with the manifests.

```bash
python3.12 -m venv /tmp/verify-deps-venv
source /tmp/verify-deps-venv/bin/activate
# 1. The documented install (CLAUDE.md §8), which is also the Dockerfile's
#    path: the hashed torch lock first, then the runtime and test locks.
pip install --dry-run --require-hashes --no-deps -r locks/requirements-torch-lock-linux.txt --index-url https://download.pytorch.org/whl/cpu
pip install --dry-run --require-hashes -r locks/requirements-lock-linux.txt
pip install --dry-run --require-hashes -r locks/requirements-test-lock-linux.txt
# 2. Editable install for console scripts — the --extra-index-url is required:
#    constraints.txt pins torch==...+cpu, which sentence-transformers pulls in,
#    and that wheel exists only on the CPU index. Omit it and you get a
#    ResolutionImpossible that is your invocation's fault, not the tree's.
pip install --dry-run -e . -c constraints.txt --extra-index-url https://download.pytorch.org/whl/cpu
# 3. The legacy requirements surface (torch absent there, so the constraint
#    still needs the CPU index):
pip install --dry-run -r requirements.txt -r requirements-test.txt -c constraints.txt --extra-index-url https://download.pytorch.org/whl/cpu
# 4. The packaging config itself — the one check a dry-run cannot make. This
#    really builds the wheel through hatchling, so a stale entry in
#    [tool.hatch.build] `packages`/`force-include` (a deleted module left
#    behind, say) fails here and nowhere else:
pip wheel --no-deps -w /tmp/verify-deps-wheel .
deactivate && rm -rf /tmp/verify-deps-venv /tmp/verify-deps-wheel
# 5. The compose half of the Docker surface renders (needs the docker CLI AND a
#    running daemon — the CLI alone is not enough; report "not verified" rather
#    than skipping silently when either is absent):
docker compose config --quiet
```

Read the failure class if any command errors:
- `no version of torch==...+cpu` (or similar unresolvable pin) → the CPU
  wheel index isn't being reached; check for a missing `--extra-index-url`
  / `--index-url` (see Gotchas).
- `no version of setuptools==<pin> and torch==...+cpu depends on
  setuptools==<pin>` **from uv** → read past the first clause. This is NOT
  the torch case above, even though torch is what the message blames and
  `--extra-index-url` is present. uv's default `first-index` strategy found
  `setuptools` on the PyTorch index, refused to look at PyPI for the pinned
  version, and reported it as torch being unusable. pip resolves the same
  tree fine because it searches every index. `--index-strategy
  unsafe-best-match` "fixes" it by dropping the dependency-confusion guard
  `requirements.txt`'s own comment relies on — so the finding is "this
  surface should not be invoked through uv," not "bump a pin."
- `ResolutionImpossible: sentence-transformers X depends on torch>=... / the
  user requested (constraint) torch==...+cpu` **on `-e .`** → you omitted
  `--extra-index-url`. Not a finding; fix the invocation and re-run.
- `error: externally-managed-environment` (pip) or `no virtual environment
  found` (uv) → you are outside the venv the block above creates; not a real
  finding, fix the test invocation rather than reaching for `--system` or
  `--break-system-packages`.
- A network/proxy error reaching `download.pytorch.org` specifically →
  environment-local (sandboxes/CI runners sometimes restrict egress to
  approved hosts); note it as unverified rather than asserting pass or fail.
- Environment.yml (conda): there's no equivalent dry-run flag for `conda`/
  `mamba env create`; if you need to verify it, the honest option is a real
  `mamba env create -f environment.yml --dry-run` in an
  environment where conda is installed — otherwise report it as "not
  dry-run-verified this pass," don't assert it works from reading the file.

### Step 5 — PyPI currency sweep

For every package `extract_pins.py` reported (or a targeted subset if asked
about one), check the latest stable release and any published advisory
affecting versions at-or-above the current pin:

```
WebFetch https://pypi.org/pypi/<package>/json  →  read "info.version"
```

If `WebFetch` chokes on a large payload (`pydantic-core` and a few others
have big JSON bodies), fall back to `curl -s https://pypi.org/pypi/<package>/json | python3 -c "import json,sys; print(json.load(sys.stdin)['info']['version'])"`.
For CVE/advisory awareness, `WebSearch` for `"<package>" CVE <year>` and
sanity-check the affected-version range against the pin — a headline CVE
that was fixed in a version below your pin is not a finding.

This is naturally parallelizable — for a full sweep (~25+ packages),
batch 4-5 packages per subagent call rather than looking each one up
serially.

**Classify every gap, don't just list it:**

| Gap | Action |
|---|---|
| Matches latest, or pin is the newest release on an intentionally-held line (e.g. numpy `1.26.x`) | Report "current," no action |
| Behind latest, **no CVE found**, dev-tool-only (`ruff`, `mypy`, `bandit`, `pytest*`) | Report as a bump *candidate* — low blast radius, but a `ruff`/`mypy` bump can silently change lint/type-check behavior mid-CI (`constraints.txt`'s own comment), so don't bump without re-running lint/tests |
| Behind latest, **no CVE found**, runtime dependency (`fastapi`, `uvicorn`, `langgraph`, ...) | Report as a bump candidate for explicit review — **do not bump without asking**. CLAUDE.md §7 puts a new runtime dependency in the High tier and a bump at Medium or above; `dep-guard`'s Guardrails say the same |
| Behind latest, **CVE found affecting the pin's version** | Escalate clearly — this is the one case worth flagging even without being asked, since it's a live security gap, not a staleness preference |
| Pin is a documented, deliberate exception (chromadb CVE-2026-45829 risk-accepted, numpy `<2`, pydantic/pydantic-core lock-step, `websockets` pinned direct for `langgraph-sdk` import-time compatibility) | Do not recommend bumping — report the gap for awareness only, cite the documented reason |

### Step 6 — Report

```
Verify Deps: <n> packages checked | <n> currency gaps | <n> flagged CVEs | <n> install-surface failures
dep-guard: <PASS/FAIL from Step 1>
requirements.txt drift: <none | list from Step 2>
Env drift (E1-E7): <n> failure(s), <n> warning(s) — <every E3 name reported, or "none">
Install surfaces dry-run: local-dev=<PASS/FAIL/unverified> legacy-CI=<...> Dockerfile=<...> wheel-build=<...> conda=<not dry-run-verified, unless actually tested>
Currency: <table or summary — current / bump-candidate / needs-review / CVE-flagged>
Verdict: <fixes applied (list) | findings for review (list) | none>
```

A clean tree reports zero E3 warnings, so every E3 name the run prints is a
new finding — list each one; never summarize them away as "known".

---

## Verify

```bash
bash .claude/skills/verify-deps/verify.sh
```

Pure stdlib, no install needed. It runs both scripts on the clean tree (exit
0, with `--strict` too; the E3 assertion is on the exit code, not a warning
count, so a future undeclared transitive surfaces as a warning to read) and
fails closed on missing pin files (exit 3), then a mutation per rule, each
asserting exit 2: a `requirements*.txt` pin drifting from `constraints.txt`
(and its `--strict` rejection), the same tool pinned at two versions in two
workflow files (E1 — the drift class nothing else in the repo can see), an
extras-only package leaking into `requirements.txt` (E4, preceded by a
negative test that the same name in a *comment* does not trip it), a
Dockerfile that loses the hashed-lock contract, grows a silent `||` fallback,
or whose torch lock lags `constraints.txt` (E5), the Docker surface losing a
COPYed manifest, the `index/` or `data/` exclusions, the loopback publish,
the `./index` mount, the `CMD --port`, the image-tag/version agreement or
the `IMAGE_NAME` compose pulls (E6, with the shipped files copied whole as
the negative control), and a dead or orphaned E7 exemption. The script
enumerates its checks as it runs (24 at last count).

Both scripts take `--repo-root`, which is what lets the mutations run against a
`mktemp -d` tree instead of the real repo. Does not re-test `dep-guard`'s own
mutations (`.claude/skills/dep-guard/verify.sh` already does, and this skill
delegates Step 1 to it rather than duplicating it).

---

## Guardrails

- **Never bump a runtime dependency's pin without explicit user approval.**
  CLAUDE.md §7 makes a new runtime dependency High tier (ask first) and a
  bump Medium or above. This skill's job is to make an *informed* bump
  decision possible, not to make the decision.
- **A bump touches at minimum two files** (`pyproject.toml` AND
  `constraints.txt`, per CLAUDE.md §6's code-change bar), usually three or
  four (`requirements.txt`, `environment.yml` if the package is conda-side
  too), **and then the hashed `locks/`** regenerated on arm64 macOS — never
  bump one pin file and leave the others stale; that's the exact class of bug
  this skill exists to catch.
- **The load-bearing exceptions `dep-guard` enforces** (pydantic pair, numpy
  `<2`, torch `+cpu`, the chromadb CVE pin) are inherited here, not
  re-decided; a real reason to revisit one goes through `dep-guard`'s
  constants and CLAUDE.md §4 in the same commit as the bump.
- **Currency findings do not need a fix to be a complete run.** "0 CVEs
  found, N packages a minor version behind, none recommended for
  unattended bump" is a valid, complete report — don't manufacture urgency
  to justify a change.

## Gotchas

- **uv is not an install surface here, and two uv traps are why.** `uv pip
  install` ignores `pyproject.toml`'s `[tool.uv.*]` tables (only `uv sync`/
  `uv lock` honor them; the repo has none anyway), so it needs
  `--extra-index-url https://download.pytorch.org/whl/cpu` to find
  `torch==...+cpu` at all; and under uv's default `first-index` strategy an
  exactly-pinned package the PyTorch index also mirrors (`setuptools`) makes
  uv stop rather than fall back to PyPI (reproduced 2026-09-11 on uv 0.7.22
  and 0.8.17). pip has neither rule. **Do not "fix" a uv resolution failure
  with `--index-strategy unsafe-best-match`** without owner sign-off: it is
  the dependency-confusion control, not a verbosity flag.
- **A build stage that copies only lock/manifest files before installing**
  (the Dockerfile's layer-caching pattern) cannot use `-e .` to install the
  local `cyclaw` package itself — hatchling has no `gate.py`/`graph.py`/etc.
  to build a wheel from yet at that point. That stage installs the hashed
  locks (a concrete external-package list, no local build needed).
- **`--dry-run` validates resolution, not the build/link step.** Don't
  over-claim "verified" from a dry-run alone; say what was actually checked.
- **PyPI's `Development Status` classifier is not a reliability signal**
  (`fastapi`, `pydantic-core` carry pre-1.0-era classifiers by habit). Judge
  by the version string and not-yanked status.
- **A CVE headline is not automatically a finding** — always check the
  affected-version range against the actual pin. Several 2026 CVE waves
  (LangChain/LangGraph in particular) fix in a version already below what
  CyClaw pins; reporting those as open findings would be noise.
- **E3's import→distribution mapping is PEP 503 normalization, not a lookup
  table** — `_DIST_ALIAS` in `check_env_drift.py` holds only the four names
  that differ by more than punctuation (`yaml`→`pyyaml`,
  `dateutil`→`python-dateutil`, `dotenv`→`python-dotenv`,
  `celpy`→`cel-python`). Every
  underscore/hyphen case (`langchain_xai`, `rank_bm25`, `huggingface_hub`, …)
  is handled by treating `_` and `-` as equivalent, per PEP 503. Adding those
  to the table instead would work today and silently rot on the next
  `langchain_*` import — resist it.
- **E3 skips virtualenvs structurally, by their own `pyvenv.cfg`** — not by
  name. The venv in this tree was `.venv312` when the check was written, so a
  hardcoded `.venv/` skip missed it entirely and the first run reported ~200
  site-packages modules as undeclared. Any name-based skip list has the same
  bug waiting in it.
- **E6 reads YAML with regexes on purpose.** `docker-compose.yml` and
  `publish-ghcr.yml` are scanned for the specific lines the contract names
  (`image:`, port publishes, `:/app/<dir>` mounts, `IMAGE_NAME:`, `file:`)
  rather than parsed, so the checker stays stdlib-only and pre-install like
  the rest of this skill. A restructured compose file that moves those lines
  into anchors/extension fields would need the regexes revisited — the
  failure mode is a false FAIL, never a silent pass.
- **`extract_pins.py` imports `dep-guard/check_deps.py` directly** (sibling
  skill, `sys.path` insert) rather than re-parsing pin files — if
  `dep-guard`'s parsing helpers change their names/signature, this script
  breaks with an `ImportError`, which is the intended failure mode (loud,
  not a silent drift between two parallel parsers).
- **The Step 6 bump recipe is a set of claims; derive each from a checker,
  not from memory of the install surfaces.** On PR #1640 (2026-10-13) every
  *measured* row of the sweep report survived review, while the "how to
  bump" prose took thirty-seven correct Codex findings across ten passes. Each one
  had a file that would have caught it first: a package's files-to-edit are
  exactly the non-empty columns of its `extract_pins.py` row (extras-only
  and constraints-only packages never enter `requirements.txt` or
  `environment.yml`; of the LangChain family only `langchain-core` and
  `langgraph` are base (`langsmith` is their constraints-only
  transitive); `pydantic-core` is constraints-only even though it moves in
  lock-step with base-runtime `pydantic`, and a lock-step pair whose new
  parent exists on PyPI is a candidate, not an exception; `tzdata` is the `test` extra + `requirements-test.txt` + the
  `python-tzdata` conda pin, not base runtime — and a reclassified package
  moves in the pin table *and* the summary totals, in the same edit), with
  two inputs the table does not show — `scripts/ci-lock-inputs/extra-postgres.txt`,
  the only extra lock input with exact pins (`psycopg`/`psycopg-binary`),
  which a psycopg bump edits or `refresh-ci-locks.sh` fails on the stale
  pin — and `requirements-torch.txt`, which
  `refresh-runtime-lock.sh` compiles the three torch locks from and the
  Dockerfile installs by lock (no versioned torch line of its own), so a
  torch bump edits it too — while `requirements.txt` stays torch-free on
  purpose. The inventory of
  hard-coded contracts that move with a pin is a **command**, never a list
  written from memory: `git grep -nF '<version>' -- ':!locks'` on the bare
  version string over tracked files (never a bare `grep -rn`, which walks
  ignored `logs/`, `data/`, and venvs and prints whatever line matched,
  so audit or query content could land in a transcript or report) — and
  that output is **discovery**, not the edit set: `0.24.0` also matches
  `trl<=0.24.0` in `tools/lora_finetune/requirements.txt` and every
  dated `docs/audits/` snapshot, so filter each hit by package context and
  never rewrite a historical audit; because the string appears in
  forms a `<package>==` grep misses — `torch-cpu-2.13.0-` cache keys in
  `ci.yml`/`pip-audit.yml`/`nemo-guardrails.yml` (the reason `dep-guard`
  D8 matches both forms), `nemoguardrails.__version__ == "0.24.0"` in
  `tests/nemo_runtime/`, `"0.24.0"` in `guardrails/verify_install.py` and
  `otel-hardening`'s `LAST_VERIFIED_VENDOR_PINS`, and `pendulum==3.3.0` /
  `pgvector==0.5.1`, the `langgraph-cli analytics` row's
  `langgraph==1.2.15 family`, and the core-libs row's `hatchling==1.32.4`
  in `check_otel.py`'s *prose* inventory, which `--strict` never reads —
  then `dep-guard` and
  `check_otel.py --strict` as the authoritative re-check, knowing the
  strict run covers only the pin dict. On 2026-10-13
  that grep surfaced, beyond the manifests: `dep-guard` `_PYDANTIC_LOCKSTEP`
  and D11 (plus its `verify.sh` fixture), `LAST_VERIFIED_VENDOR_PINS` for
  `nemoguardrails`, `onnxruntime`, `langchain`, `langchain-core`,
  `langgraph`, and `langsmith`, the NeMo exact-version checks in
  `guardrails/verify_install.py`, `ci.yml`'s wheel-metadata assert, and
  the `nemo_runtime` test, the three live `1.30.0` literals in
  `otel-hardening/verify.sh` (an exact assertion and two mutation targets
  that make that verifier fail after an `onnxruntime` bump until edited),
  the `ruff==0.17.1` *comment* in `lint.yml`
  (E1 compares workflow pins only with each other, so it never flags that
  comment against the manifests), and five
  docs that `doc_sync.py` does **not** check (it has no dependency-version
  rule), so they are fixed by hand and re-verified by the search. A new
  dependency edge is part of the same check, in two steps: read the bumped
  package's `requires_dist` on PyPI, then grep the runtime lock before
  calling anything "new" (`fastapi` 0.143.0 adds an unconditional
  `opentelemetry-api`, but `opentelemetry-api`/`-sdk`/the gRPC exporter were
  already in every runtime lock via `chromadb` and already under
  `OTEL_SDK_DISABLED`, so the review is of FastAPI's *use* of an installed,
  suppressed stack — not a new package, and not a new `constraints.txt`
  line); and `extract_pins.py` reads `[project]` tables only, so
  `[build-system].requires` (`hatchling`) is checked by hand, and its
  exercise is a full `python -m build` (wheel + sdist, as the release
  workflow runs it), not CI's `--wheel`. Advisories are queried at
  `/pypi/<package>/<pinned-version>/json`: the project endpoint's
  `vulnerabilities` array describes only the latest release, so for a pin
  behind latest it hides anything fixed since — and the report must say
  which endpoint it used (the 2026-10-13 sweep did query per-release but
  did not say so, which reads the same as not having done it); a
  major bump needs the dependents' `requires_dist` read on PyPI first
  (`sentence-transformers==6.1.0` pins `huggingface-hub<2.0.0`, so a 2.x
  "candidate" cannot resolve and is an exception); `check_lock_contract.py`
  hashes `constraints.txt` and `pyproject.toml`'s `[project]` dependency
  tables (not the raw file) into **every** group's inputs, so a bump that
  touches either runs both refresh scripts, a change confined to one group's
  own input file runs that group's script, and `[build-system]` or
  `environment.yml` edits run neither; name a test file only after `ls tests/<name>*`
  returns it (`test_schemas*` did not exist); and a `--dry-run` that
  resolves in a venv with packages already installed is **conditional**, not
  PASS — the runtime lock omits torch by design and resolved only because a
  torch build was present. Hold the recipe to the same standard as the pin
  table: every sentence traceable to a command.
