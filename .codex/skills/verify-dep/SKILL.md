---
name: verify-dep
description: Verify CyClaw dependency profiles across pyproject, legacy requirements, constraints, Docker, Conda, platform installers, and existing supply-chain controls. Use before changing dependencies, install manifests, Docker/Compose/deploy files, dependency CI, or a release install path.
---

# Verify CyClaw Dependencies

Use the maintained `.claude/skills/dep-guard/` and
`.claude/skills/verify-deps/` checkers; do not copy their parsers into this
skill or add a second dependency source of truth.

## Install-surface contract

These are selected profiles, not three files that must contain identical text:

| Surface | Contract |
| --- | --- |
| `pyproject.toml` + `constraints.txt` | PEP 621 base dependencies and selected optional extras; constraints caps their versions. |
| `requirements.txt` + `constraints.txt` | Legacy and base container runtime: CPU Torch and core dependencies including load-bearing `websockets`; no test tools or opt-in extras. |
| `requirements-test.txt` + `constraints.txt` | Test tools installed alongside the runtime profile for CI/development; excluded from the base Docker image. |
| `Dockerfile` | Consumes the legacy constrained surface above; it is not an independent dependency manifest. |
| `environment.yml` | Conda base/test/dev profile with documented Conda-only FastAPI and Starlette exceptions. |
| Platform installers | Linux/Windows install `torch==...+cpu` from the PyTorch CPU index; macOS installs plain Torch then filters Linux-only Torch/index lines from copied manifests. |

The root `environment.yml` is the Conda profile. The same basename under
`.github/workflows/` is a workflow_dispatch no-op and is included in actionlint.
`constraints.txt` is a version ceiling, not an install list. Do not add a fake
`torch-cpu` extra or require all profiles to be byte-for-byte equal.

## Workflow

1. Read `AGENTS.md`, `.codex/Codex_instructions.md`, the target diff, and the
   relevant install/deploy workflows. Fetch `origin/main`, list open PRs, and
   map shared manifest, Docker, CI, and documentation files before editing.
   Consolidate related shared-file changes where practical; otherwise use the
   documented stacked-PR procedure.
2. Run the offline static gate before installing or updating anything:

   ```bash
   python .claude/skills/dep-guard/check_deps.py --strict
   python .claude/skills/verify-deps/extract_pins.py --strict
   python .claude/skills/verify-deps/check_env_drift.py --strict
   ```

   On POSIX hosts without `python`, replace it with `python3`. Treat any
   nonzero result as a dependency-contract failure, not a cue to add a random
   package or loosen a pin.
3. Inventory the selected profile from `pyproject.toml`: base dependencies,
   each optional-dependency group, direct source imports, and operator-supplied
   tools such as Ollama, GitHub CLI, rclone, Postgres, Docker, Falco, and
   AppArmor. Classify every difference as base, opt-in, platform-specific,
   transitive constraint, or documented exception.
4. Validate only the install surface being changed. When network/tooling is
   available, dry-run the installer actually used by that surface (`pip` in
   the maintained scripts and Dockerfile). For Linux/Windows:

   ```bash
   python -m pip install --dry-run --ignore-installed -e . -c constraints.txt --extra-index-url https://download.pytorch.org/whl/cpu
   python -m pip install --dry-run --ignore-installed -r requirements.txt -c constraints.txt
   ```

   For Docker or Compose changes, also run:

   ```bash
   python -m pytest tests/test_isolation_deploy.py tests/test_falco_detection.py -q -p no:cacheprovider
   docker compose config --quiet
   docker build -t cyclaw:verify-dep .
   ```

   Record a skipped Docker/Conda/platform build honestly if the host lacks that
   runtime. Do not substitute a host-pip success for a container build.
5. For macOS, validate the documented Apple-Silicon installer path separately.
   Plain macOS Torch is intentional; do not force the Linux/Windows `+cpu` pin
   into that filtered install. Remove Torch/index lines from a requirements
   copy, but retain the Torch constraint with only `+cpu` removed. Use that
   macOS constraints copy for editable/extras dry-runs too; the exact recipe
   lives in `setup-guide.md`. Report resolution separately from installation.
   `full` and `all` are aggregates, not synonyms for every extra: inspect their
   membership (currently `all` omits the standalone `mssql` extra).
6. For a pin or dependency change, use the existing `pip-audit`, OSV, Trivy,
   Dependabot, and optional-extras CI paths. Verify releases and advisories from
   authoritative sources, preserve accepted-risk documentation, and never
   auto-bump a package merely because a newer release exists.
7. Report the profile matrix, intentional exceptions, commands run, advisories
   reviewed, and any unverified platform. This skill changes no core request
   path and must preserve I1-I6, especially I6 optional-module isolation.

## PR completion gates

At the end of the implementation phase, immediately before push and draft PR,
fetch `origin/main` and rebase the feature branch onto it. Re-run the affected
checks after the rebase. After the draft PR's CI is green, fetch again: if
`main` moved, rebase onto its latest commit, re-run checks and CI, and only then
recommend merge. Force-with-lease requires explicit human approval.
