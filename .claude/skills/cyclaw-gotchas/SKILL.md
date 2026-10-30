---
name: cyclaw-gotchas
description: >-
  Session-tested sandbox traps for CyClaw (venv/install, pytest, gate.py,
  PR/review-bot flow) plus a driver that does the setup correctly. Load
  before installing deps, running tests, launching or probing gate.py, or
  driving a PR — or when something hangs, won't install, or prints no test
  summary. Every gotcha names the session, PR, or file that proved it.
---

# cyclaw-gotchas

Paths are relative to the repo root. The driver is
`.claude/skills/cyclaw-gotchas/driver.sh`; `SKILL.md` is its man page plus
the lessons the driver exists to encode. CLAUDE.md §4 is the canonical trap
list for the *codebase*; this file is the trap list for the *session*: the
sandbox, the process, the reviewers, and the runtime behaviours that look
like bugs but are not. Where the two overlap, CLAUDE.md wins; this file
links rather than restates.

## Prerequisites

Nothing to `apt-get`. The default cloud image (Ubuntu 24.04) already has
`/usr/bin/python3.12`, `ruff`, `uv`, `docker`, `curl`, and `git`. What it does
**not** have is any CyClaw dependency in any interpreter, and its egress proxy
denies two hosts CyClaw's install and index paths need:

| Host | Denied? | Consequence |
|---|---|---|
| `pypi.org`, `files.pythonhosted.org` | no | pip works |
| `download.pytorch.org` | **yes** (org policy, 403 on CONNECT) | `torch==2.13.0+cpu` is unresolvable |
| `huggingface.co` | **yes** | `all-MiniLM-L6-v2` cannot download, so the index cannot be built |
| `github.com` (git over the proxy) | no | fetch/push work |

Check the live picture before assuming: `bash .claude/skills/cyclaw-gotchas/driver.sh inventory`.

## Build (the venv)

```bash
bash .claude/skills/cyclaw-gotchas/driver.sh venv
```

What it does, and why each step is the way it is (all learned by failing first,
session 2026-09-06):

1. `python3.12 -m venv /root/.venv-cyclaw-312` -- outside the repo, so no
   `.gitignore` entry and no chance of `ruff`/pytest walking site-packages.
   Bare `python3` is never 3.12 on this image (3.11 on the 2026-09 images,
   3.13 on 2026-10-13's); do not `update-alternatives` it (the
   session-runtime hooks resolve through it).
2. Tries `torch==2.13.0+cpu` from the CPU index with one retry and a short
   timeout (`uv pip install` with `UV_HTTP_RETRIES=1 UV_HTTP_TIMEOUT=15` when
   `uv` is on PATH, as it is here; `pip --retries 1` otherwise). On this
   proxy that fails in seconds, not minutes.
3. Falls back to plain `torch==2.13.0` from PyPI **with** its dependency tree.
   `--no-deps` was tried and is a dead end: the Linux wheel dlopens
   `libcudart.so.13` at import and raises before anything else loads. The
   fallback costs ~2 GB and ~7 minutes; disk had 30 GB free.
4. Installs the hashed Linux locks `locks/requirements-lock-linux.txt` and
   `locks/requirements-test-lock-linux.txt` with `--no-deps --require-hashes`.
   No resolver runs and no constraints copy is built; both locks omit torch, so
   they go in after the torch step above. `--no-deps` is load-bearing on the
   uv path: a lock is a complete resolution, and without it uv's
   `--require-hashes` fails on the one package it would have to resolve
   itself (`must be pinned upfront with ==, but found: torch`, pulled in by
   sentence-transformers). pip accepts the installed torch, which is why CI
   and CLAUDE.md §8 need no `--no-deps` on the locks. This is unrelated to the
   torch `--no-deps` dead end in step 3.

Re-running is idempotent: it exits 0 immediately once
`import torch, chromadb, langgraph, pytest` succeeds.

## Run (agent path)

```bash
D=.claude/skills/cyclaw-gotchas/driver.sh
bash $D serve      # gate.py in the background, pidfile in /tmp/cyclaw-gotchas, waits for /health (took 3-11 s here)
bash $D probe      # /health, POST /query, GET /soul without and with the API key
bash $D stop       # kills exactly the pid it started
```

What `probe` printed in this container, which is the **correct** no-Ollama,
no-index baseline:

```
{'status': 'degraded', 'index_ready': False, 'graph_ready': False, 'mode': 'hybrid'}
{"detail":{"error":"Index not built. Run: python -m retrieval.indexer","code":"INDEX_NOT_FOUND"}} [503]
401
200
```

`degraded` is normal without Ollama. `503 INDEX_NOT_FOUND` is normal here
and will stay that way: the index needs the embedding model, and the model
host is denied. `401` then `200` on `/soul` is the fail-closed key gate
working. Do not "fix" any of these.

`serve` reads `CYCLAW_API_KEY` (default `smoke-test-key`) and `GROK_API_KEY`
(default `dummy`, any non-empty value). Override on the command line for a
different key.

## Test

```bash
bash .claude/skills/cyclaw-gotchas/driver.sh test tests/test_sync_runner.py tests/test_telemetry_kill.py
bash .claude/skills/cyclaw-gotchas/driver.sh test                          # whole suite (5263 passed, 82 skipped, ~4m40s on 2026-09-06)
```

CLAUDE.md §5's verification policy (owner decision 2026-10-08) applies: run
the changed code, lint, let GitHub Actions run the suites, and reach for
`driver.sh test <one file>` only when nothing else exercises the path. The
no-argument whole-suite form is there for the owner, for CI parity checks
he asks for, and for `/tests-refactor`; it is not a routine step.

The suite is fully green in this sandbox even though the index cannot be
built, because `tests/conftest.py` mocks the embedding model. Only
`tests/ci_rag_smoke.py`, `.claude/skills/CyClaw-Sandbox/smoke.sh`, `/run`,
and `index-doctor` need the real model; they are unrunnable here and CI's
`ollama-mock-smoke` job is where they get exercised.

The driver clears `pyproject.toml`'s `addopts` before adding its own flags.
Reason: `addopts = "-q --tb=short"` plus a second `-q` on the command line is
`-qq`, and at that level pytest **drops the final "N passed" line**, so a
green run prints only dots. Three runs in one session went unread that way.
If you invoke pytest directly, either omit `-q` or pass `-o addopts=""`, and
read the exit code (`echo "pytest exit=${PIPESTATUS[0]}"` when piped).

## Checks

```bash
bash .claude/skills/cyclaw-gotchas/driver.sh checks
```

Runs the six stdlib guards (`invariant-guard`, `doc-sync`, `config-guard`,
`dep-guard`, `dotenv-guard`, verify-deps `check_env_drift.py --strict`) and prints one line
each. `config-guard` reports **0 warnings** on a clean tree since C9 was
flipped (commit 993f439) from "warn if hybrid+enabled" to "warn if the
committed config diverges from the documented shipped provider posture" —
the shipped posture is now hybrid with grok/claude enabled (CLAUDE.md's
2026-08-07 provider armament), so a clean tree reports C9 `ok`, not a
warning. A `1 warning` result today means the config no longer matches that
documented posture — treat it as drift to investigate, not the old baseline.

`python gate.py` by hand binds `127.0.0.1:8787` and blocks the shell (Ctrl-C
to stop); from an agent, use `serve`.

## Gotchas

Each entry: the trap, the evidence, the rule. Dated so a later session can
expire it.

### Sandbox and install

- **Nothing is preinstalled, in any interpreter.** On 2026-09-06 `import
  torch` failed for every Python on the image. Treat the venv step as
  mandatory every session (the cloud SessionStart hook starts it in the
  background); the container is rebuilt from a generic image, not from this
  repo.
- ~~**`--ignore-installed PyYAML` reinstalls everything, not just PyYAML**~~
  — expired 2026-10-13: every documented install now uses the hashed
  `locks/` with `--require-hashes` (#1598), no install line carries
  `--ignore-installed`, and `tests/test_macos_scripts.py` asserts the old
  constraints rewrite is gone. Kept as a one-line tombstone because the
  lesson generalises: a bare pip flag followed by a package name is two
  arguments, and a resolver re-run can float torch to a CUDA build.
- **`pkill -f "python gate.py"` kills your own shell, and `pgrep -f gate.py`
  reports it as still running.** Both match the `bash -c` wrapper that is
  executing the command (exit 144 from `pkill`; a phantom "server still
  running" from `pgrep`, both observed 2026-09-06). The driver uses a pidfile
  for exactly this reason. To check liveness, hit the port:
  `curl -s --max-time 2 http://127.0.0.1:8787/health` (000 / connection
  refused means down). To kill without a pidfile, `fuser -k 8787/tcp`.
- **`uv pip install --dry-run --system` fails on this image** with the
  "externally managed" refusal before resolving anything. Not a finding about
  the Dockerfile; run the dry-run inside a venv or report it unverified.
- **The PyTorch and Hugging Face denials are per-organisation policy**, not a
  transient outage. `curl -sS "$HTTPS_PROXY/__agentproxy/status"` lists the
  denied hosts under `recentRelayFailures`. Report them as "unverified in this
  sandbox", never as a CyClaw defect.

### Runtime behaviour that looks like a bug

- **`/health` `degraded`, `TELEMETRY KILL` on stdout, `503 INDEX_NOT_FOUND`,
  `needs_confirm: true` on `/query`** are all normal states, not errors
  (CLAUDE.md §4 "Environment & install" and `.claude/commands/run.md`).

### Tests and checks

- **A green run can print no summary** (see Test above). Read the exit code.
- **`workflow-lint` can go red with no workflow change, and offline zizmor will
  not reproduce it.** On 2026-10-30 `ci.yml` run 41128159124 (main, #1789)
  failed the zizmor step with exit 14: the online `known-vulnerable-actions`
  audit (CI passes `--gh-token`) flagged `pypa/gh-action-pypi-publish` for
  GHSA-5xjx-3w67-w9x9, an advisory published after the previous green run. The
  fix is a pin bump, not a code change. In this sandbox `zizmor --offline`
  reports nothing before or after, and the online mode panics (proxy denies the
  advisory API), so read the failing job's log for the advisory id and let CI
  confirm. Do not add a `zizmor: ignore` for a high finding without the
  owner's say-so.
- **A lone `subprocess.TimeoutExpired` on the Windows leg is a runner stall
  until proven otherwise.** On 2026-10-30, `ci.yml` run 41065100100 on main
  (#1787, an installer/docs change) failed one test,
  `test_read_mode_is_the_default[plain]`, because `node -e` for a
  millisecond-long script did not return in 30s; coverage was 90.23% and the
  same code had passed on its PR branch (run 40999080828). Read the log's
  `FAILURES` block before blaming the merge, and compare against the PR-branch
  run. The three node-spawning workflow-contract tests now allow 120s. Do not
  "fix" it by skipping the test on Windows.
- **Scope any local test run to the one file that covers the change** and
  let CI run the suite (CLAUDE.md §5). When the owner does ask for the whole
  suite, `-x` on the first pass finds the first failure without waiting
  ~4m40s for all of it.
- **Ruff, invariant-guard, and the doc-sync checker are cheap; run them
  before every push.** `ruff check --select E,F,I,B,C4,UP,S <touched files>`
  is seconds; the F/B/S subset is what blocks merge (`lint.yml`).
- **A new skill directory with a `verify.sh` must be classified in
  `ci.yml`'s `discover-skills` step** (`heavy|yaml|stdlib` arm), or that job
  fails closed for the whole workflow. Same commit as the skill.
- **A new skill must also appear in CLAUDE.md §9** or doc-sync D1 flags it,
  and gets a thin `.claude/commands/<name>.md` wrapper (`.claude/README.md`).

### Git, PRs, and the review bots

- **A merged PR's branch is finished.** If the session's designated branch
  already merged, restart it from `origin/main` with
  `git checkout -B <branch> origin/main`; never stack new commits on merged
  history (this session, after #1317 merged).
- **The stop hook nags on every unpushed commit and dirty tree.** Commit per
  concern and push before ending a turn; do not accumulate.
- **After a squash-merge GitHub deletes the head branch, and the stale
  tracking ref makes the stop hook report phantom "N unpushed commits".**
  Once the designated branch is reset onto `origin/main`, `git push` is not
  a fast-forward against the old remote branch and `--force-with-lease`
  answers `rejected (stale info)` because the remote ref no longer exists
  (2026-09-06, after #1319). Fix: `git fetch --prune origin`, then a plain
  `git push -u origin <branch>` recreates it. No force push needed.
- **`mergeable_state: "unstable"` means checks pending or failing, not a
  conflict.** `"dirty"` is the conflict state. Read the check runs before
  acting on "unstable".
- **`list_triggers` is the record of check-ins; memory is not.** On
  2026-09-06 the session armed a one-shot timer for #1318 at 00:31, lost
  track of it, told the owner at 01:07 that none existed, armed a second
  overlapping one, and was then woken by the first at 01:32. Before
  asserting or denying that a check-in exists, run `list_triggers`
  (`include_completed` shows fired one-shots as `run_once_fired`). Keep
  **one** live timer that names every open PR and re-scope it with
  `update_trigger` as PRs merge; `update_trigger` on a deleted id returns
  not-found, so re-scope rather than delete-and-recreate.
- **Trim `list_pull_requests` with `fields`** (`number,title,head`); the full
  payload is large and mostly body text.
- **Codex P2s are bug reports; verify against the code, then fix.** On #1318
  (in the since-removed agentic `repo_workspace`) the bot was right that the caller (`repo_workspace._clone`) does not retry,
  so "skip the timeout retry for `repo_clone`" had silently discarded the
  operator's `gh_retries`. The fix was to make the retry able to succeed
  (clear the partial `dest` first), not to remove it. General rule: before
  disabling a retry, read what the caller does on failure; a fail-fast that
  deletes a configured budget is a regression.
- **A PR body claim the bot can check will be checked.** "The caller retries
  at a higher level" was false and was caught. Only write verifiable claims.
- **Reply on the thread, then resolve it, on PRs you opened.** The reply needs
  the Claude Code attribution footer. Leave a thread open only while a
  question to the reviewer is pending. Check merged PRs for threads left open.
- **Bot review triggers:** the owner comments `@codex review` to start a
  Codex pass; `@codex apply fixes` hands the fix to Codex; `@copilot resolve
  the merge conflicts ...` with explicit write permission is how conflicts on
  a branch this sandbox cannot force-push get resolved (#1194 history).
- **Two branches editing `ci.yml`, `config.yaml`, `CLAUDE.md`, or the pin
  manifests must be trial-merged before opening the second PR** (CLAUDE.md
  §4 Git & PR). `git checkout -B _trial origin/main && git merge --no-ff
  <a> && git merge --no-ff <b>` and grep for `<<<<<<<`.

### Docs and doc-sync

- **An owner's recent edit is intent, not drift.** The root README said
  "multi-operator" while the threat model said "single-operator". `git log
  -L<line>,<line>:README.md` showed the owner wrote it two days after the
  threat model's stance was last touched. The right move was to ask, then
  amend the threat model (fifteenth amendment), not to revert the README.
  Always check authorship and date before "fixing" a scope or policy claim.
- **Fan out README audits to read-only subagents, one file group each,
  "report only confirmed drift with file:line and the minimal fix", then
  re-verify every finding yourself before editing.** Four groups over 38
  READMEs returned 11 findings; all 11 held up on re-read, and the re-read
  cost seconds each.
- **Docstrings are docs.** When a README derives from a package docstring,
  fix both in the same commit or the drift regrows (seen on the since-removed
  `agentic/harness_optimizer`).
- **`doc_sync.py` covers structured facts only** (D1–D13: skills list, entry
  points, config numbers, routes, node count, hook claims, the M5 doctrine
  citations, and README path/link/`python -m`/record-table references).
  README prose, the threat model stance, and skill bodies are manual-pass
  territory.

### verify-deps in this sandbox

- **Steps 1-3 (dep-guard, `extract_pins.py`, `check_env_drift.py --strict`)
  and the currency sweep run fine**; the PyPI JSON API is reachable and its
  per-version `vulnerabilities` array carries OSV advisories, so no
  `pip-audit` install is needed.
- **The install dry-runs cannot pass here** (PyTorch index denied); report
  them "unverified in this sandbox" and say why. `docker compose config
  --quiet` does work without a daemon.
- **Every advisory hit on the current pins (4 chromadb, 1 nltk on
  2026-10-13) is a dated acceptance in `SECURITY.md`** with no upstream fix
  version. Re-reporting them is noise; a *new* id is the signal.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `No matching distribution found for torch==2.13.0+cpu` after five proxy retries | CPU index denied by the egress proxy | `driver.sh venv` falls back to PyPI torch automatically |
| `OSError: libcudart.so.13: cannot open shared object file` on `import torch` | plain torch installed with `--no-deps` | reinstall without `--no-deps`; the CUDA libs are required at import on Linux |
| pytest prints dots and `[100%]` but no `N passed` line | `-q` doubled with `addopts` → `-qq` | use `driver.sh test` or `-o addopts=""`; read the exit code |
| `ModuleNotFoundError: pytest` / `torch` under `python3` | the system `python3` (not 3.12) has nothing installed | use `/root/.venv-cyclaw-312/bin/python -m pytest` |
| shell exits 144 after `pkill -f "python gate.py"`, or `pgrep -f gate.py` says a stopped server is running | both patterns match the invoking `bash -c` shell | `driver.sh stop` (pidfile); check liveness with `curl` on the port |
| `POST /query` → `503 INDEX_NOT_FOUND` after a successful serve | no index; model host denied | expected here; test retrieval via the unit suite, not the live route |
| `uv pip install --dry-run --system ...` → "externally managed" | system interpreter refuses | run inside a venv, or report unverified |
| `discover-skills` job: `unclassified skill '<name>'` | new `verify.sh` without a profile arm in `ci.yml` | add the skill to the `stdlib` (or `yaml`/`heavy`) case |
| `update_trigger` → "requested resource was not found" | the timer was deleted earlier | `send_later` a new one; do not assume one exists |
| stop hook: "N unpushed commits" on a branch you just reset to `origin/main`; `push --force-with-lease` → `rejected (stale info)` | GitHub deleted the merged head branch; local tracking ref is stale | `git fetch --prune origin` then plain `git push -u origin <branch>` |

## Guardrails

- `driver.sh` writes only under `/tmp/cyclaw-gotchas` and
  `/root/.venv-cyclaw-312` (override with `CYCLAW_SCRATCH` / `CYCLAW_VENV`);
  `serve` creates `logs/` in the repo exactly as `gate.py` would. A gotcha
  here is never a licence to skip a guard (CLAUDE.md §3, §7).

## Maintaining this file

Add a gotcha only with evidence: the session date, the PR number, or the
file:line that proved it. Expire one the same way (strike it with the date
and what changed). Keep CLAUDE.md §4 as the codebase trap list and link to it;
keep this as the session trap list. `bash .claude/skills/cyclaw-gotchas/verify.sh`
checks the driver parses, the frontmatter name matches the directory, every
repo path cited here still exists, the wrapper and CLAUDE.md row are present,
and `driver.sh inventory` runs with nothing installed.
