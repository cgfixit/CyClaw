# Documentation sync and dependency verification — 2026-09-16

Source baseline: `origin/main` at
`7a977be80b5ce8296f225a4f6ccbf1b8cbfb8cf3`. The clean local main was
fast-forwarded before preparing `codex/docs-readme-sync`. A pre-publication
fetch confirmed that baseline remained current; open-PR reads returned an
empty list. This report records local verification before draft publication;
hosted CI results are available on the pull request. No runtime,
configuration, manifest, pin, workflow, or security exception changed.

## Documentation results

Reviewed all 41 tracked README guides, including lowercase names, hidden
agent directories, fixture/vendor READMEs, and the two suffix-named guides.
Updated 16 READMEs where source-backed drift was found, plus the setup guide,
agent guidance, and the two invoked Codex skills. Unchanged guides were kept
rather than receiving a date-only edit. This was a bounded code/documentation
reconciliation, not a fresh verification of every historical measurement,
third-party hardware recommendation, or external link.

| Correction | Current source |
|---|---|
| macOS vs Linux Torch commands; retain the plain macOS Torch constraint | `macos/install-cyclaw.sh`, `constraints.txt`, CI install steps |
| Normal launch through `python gate.py`; bind/TLS/port/proxy handling | `gate.main`, `gate._listen_port`, `gate._serve`, platform launchers |
| Windows dotenv Allow entries must all resolve to the current user SID | `powershell/Invoke-CyClaw.ps1::Test-CyclawDotenvOwnerOnly` |
| Retrieval-first does not guarantee claim grounding; MCP bypasses generation graph; cloud route bypasses the input rail | `graph.py`, `mcp_hybrid_server.py` |
| Raw audit queries are possible when hashing is disabled | `utils/logger.py::audit_log` |
| Memory isolation includes `gate_ops.py`; invalid regexes warn and skip | `tests/test_memory_isolation.py`, `memory/policy.py` |
| Builtin seccomp is already selected; AppArmor/Falco remain opt-in | `docker-compose.yml` |
| Real-repo commands remain CLI-only; plan output can write a file; removed console limits are stale | `agentic/cli.py`, `schemas/api.py` |
| Calibration and separate evaluation spend ledger | `tests/judge_calibrate.py`, `tests/judge_eval.py` |
| Runtime/test split; `[all]` omits `mssql`; Transformers is already a base transitive | manifests and successful pip resolution reports |

## Dependency profile matrix

| Surface | Classification and result |
|---|---|
| `pyproject.toml` base | 16 direct runtime requirements; static declarations/import checks PASS; macOS editable dry-run PASS |
| `requirements.txt` | Runtime plus explicit CPU Torch, no pytest or optional extras; pin agreement PASS; filtered macOS dry-run PASS |
| `requirements-test.txt` | Five test requirements; static pin agreement PASS; not installed by Docker |
| `constraints.txt` | 42 exact version constraints, including optional/transitive ceilings; static agreement PASS |
| Docker | Uses constrained legacy runtime and preinstalls matching CPU Torch; static E5/E6 PASS; no image build |
| Conda | Base/test/dev profile; static agreement PASS; no Conda solve (runtime absent) |
| macOS Apple Silicon | Requirements copy drops Torch/index lines; constraints copy retains `torch==2.13.0`; both dry-runs resolve plain Torch, no NVIDIA packages, no pytest |
| Linux/Windows | `torch==2.13.0+cpu` via the CPU index; static installer/CI agreement only, no native install |

All 11 optional groups were read from `pyproject.toml`:

| Group | Membership |
|---|---|
| `guardrails` | nemoguardrails |
| `postgres` | psycopg, psycopg-binary |
| `pgvector` | pgvector |
| `mssql` | pyodbc |
| `numbat-cel` | cel-python |
| `test` | pytest, pytest-asyncio, pytest-cov, pygments, tzdata |
| `dev` | ruff, mypy, bandit, pytest-cov |
| `agentic-deepagents` | deepagents, langchain, langchain-openai, langchain-anthropic |
| `agentic-deepagents-cloud` | langchain-xai |
| `full` | postgres, pgvector, dev, test, agentic-deepagents |
| `all` | full, guardrails, agentic-deepagents-cloud, numbat-cel; omits mssql |

Optional groups were statically inventoried, not freshly installed/resolved.
The Conda FastAPI pin and implicit Starlette pairing are deliberate packaging
exceptions; its OTel exporter floor, `pytorch=...=cpu*` naming, and
`python-tzdata` naming remain intact. Torch is an explicit legacy requirement
and a sentence-transformers transitive on the editable base path. Version
constraints do not themselves install packages.

Ollama (or configured local model server), Git/GitHub CLI, rclone, Postgres,
ODBC system drivers, Docker, Falco, and AppArmor are operator-supplied tools or
services. Python extras do not provision those services or enable their flags.

## Executed checks

Python: 3.12.13, macOS arm64. Resolver: pip 26.2.1 (host tooling, not a change
to the CI pip pin).

```bash
python3 .claude/skills/doc-sync/doc_sync.py
bash .claude/skills/doc-sync/verify.sh
python3 .claude/skills/invariant-guard/check_invariants.py
python3 .claude/skills/dep-guard/check_deps.py --strict
python3 .claude/skills/verify-deps/extract_pins.py --strict
python3 .claude/skills/verify-deps/check_env_drift.py --strict
GROK_API_KEY=dummy python3 -m pytest tests/test_readme_install_contract.py tests/test_macos_scripts.py tests/test_powershell_windows_parity.py tools/lora_finetune/tests/ -q --tb=short -p no:cacheprovider
git diff --check
```

Results: zero documentation drift; doc-sync mutation self-test PASS (D1/D5,
D7 positive/negative, and 13/13 D9–D11 scenarios); 46 invariant checks PASS;
all three dependency gates PASS with zero failures/warnings. All 22 Codex
skills passed YAML frontmatter/UI metadata parsing and exact `$skill-name`
default-prompt checks; invocation policy was preserved.

Targeted pytest: **97 passed, 2 skipped**, 99 collected. Both skips require
native Windows PowerShell 5.1. One warning from the existing host Torch/NumPy
environment occurred in a fine-tune rendering test; this was not a pristine
installation test and does not establish native model compatibility.

The normal checker sees 39 READMEs because it filters basenames starting with
`readme`. An additional in-memory invocation reused its unchanged parser,
adding `docs/SYNC_README.md` and `docs/agentic/AGENTIC_README.md` to the corpus:
D9–D11 passed for all 41 guides. No second checker was added to the repository.

Two fresh-resolution dry-runs used temporary filtered copies prepared with
the same Torch transformation as the macOS installer:

```bash
python3 -m pip install --dry-run --ignore-installed --no-cache-dir --disable-pip-version-check --retries 0 --timeout 20 -r /tmp/cyclaw-doc-requirements-macos.txt -c /tmp/cyclaw-doc-constraints-macos.txt --report /tmp/cyclaw-doc-runtime-resolve.json
python3 -m pip install --dry-run --ignore-installed --no-cache-dir --disable-pip-version-check --retries 0 --timeout 20 -e . -c /tmp/cyclaw-doc-constraints-macos.txt --report /tmp/cyclaw-doc-editable-resolve.json
```

Both completed with `Would install`; the runtime profile resolved 117
packages, and the editable profile resolved the same 117 plus CyClaw.
JSON reports confirmed `torch==2.13.0`, no `nvidia-*`, and no pytest.
These are resolution results, not installations or runtime acceptance.

## Supply-chain and platform limits

Reviewed the repository's existing pip-audit base/optional-extra jobs, OSV
configuration, Trivy workflow, Dependabot configuration, and accepted-risk
register. Preserved the Chroma server-surface and NLTK unused-path exceptions,
and the separately documented CI pip advisory exception. No new advisory
sweep or upstream patch-status verification was performed; this report does
not assert that dependencies are vulnerability-free or latest.

`docker compose config --quiet` could not run: this host's Docker CLI has no
Compose plugin (`unknown flag: --quiet`, exit 125). Docker image build,
Conda solve, Linux/Windows installation, full application/coverage suite,
live model/paid judge runs, and native GUI/TLS acceptance were not run.
Hosted CI had not run at this local verification stage; consult the draft
PR for subsequent results.

## README review inventory

“Reviewed” means no change was warranted in the bounded reconciliation, not
that every historical or third-party assertion was independently remeasured.

| File | Outcome |
|---|---|
| `.claude/README.md` | Reviewed; unchanged |
| `.claude/skills/babysit-github-pr/README.md` | Reviewed; unchanged |
| `.claude/skills/cyclaw-privacy/README.md` | Reviewed; unchanged |
| `.codex/README.md` | Updated |
| `.githooks/README.md` | Reviewed; unchanged |
| `README.md` | Updated |
| `agentic/README.md` | Updated |
| `agentic/deepagent_github/README.md` | Reviewed; unchanged |
| `agentic/harness_optimizer/README.md` | Reviewed; unchanged |
| `agentic/harness_optimizer/mcp/README.md` | Reviewed; unchanged |
| `agentic/vendor/unslop/README.md` | Reviewed; unchanged |
| `data/README.md` | Updated |
| `deploy/README.md` | Updated |
| `deploy/apparmor/README.md` | Reviewed; unchanged |
| `deploy/falco/README.md` | Reviewed; unchanged |
| `deploy/seccomp/README.md` | Reviewed; unchanged |
| `docs/NeMo/README.md` | Updated |
| `docs/README.md` | Reviewed; unchanged |
| `docs/SYNC_README.md` | Updated |
| `docs/agentic/AGENTIC_README.md` | Updated |
| `docs/memory/README.md` | Updated |
| `docs/online-llm/readme.md` | Reviewed; unchanged |
| `docs/spend/README.md` | Updated |
| `guardrails/README.md` | Reviewed; unchanged |
| `llm/README.md` | Reviewed; unchanged |
| `macos/README.md` | Updated |
| `memory/README.md` | Updated |
| `opentweet/README.md` | Reviewed; unchanged |
| `powershell/README.md` | Updated |
| `retrieval/README.md` | Reviewed; unchanged |
| `schemas/README.md` | Reviewed; unchanged |
| `scripts/README.md` | Reviewed; unchanged |
| `static/README.md` | Reviewed; unchanged |
| `sync/README.md` | Reviewed; unchanged |
| `telegram/README.md` | Reviewed; unchanged |
| `tests/README.md` | Updated |
| `tests/fixtures/github_coding_repo/README.md` | Reviewed; unchanged |
| `tests/fixtures/groundedness/README.md` | Reviewed; unchanged |
| `tools/lora_finetune/README.md` | Updated |
| `utils/README.md` | Updated |
| `windows/README.md` | Reviewed; unchanged |
