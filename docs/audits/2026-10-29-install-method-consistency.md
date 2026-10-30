# Install-method dependency consistency review

Reviewed against `origin/main` at `c005d7961f6b41796488b8824027a08d506af67d`.
This records manifest/recipe evidence separately from native installation proof.

## Profiles and intended differences

| Method | Dependency source and contract |
| --- | --- |
| Manual Windows/Linux | Python 3.12; platform Torch hash lock first with `--no-deps` and CPU index, then runtime hash lock; test lock is separate |
| Manual Apple Silicon | Python 3.12; plain Torch from macOS hash lock, then macOS runtime lock; no `+cpu` constraint |
| Native installers and macOS onboarding | Same platform Torch/runtime hash locks; onboarding delegates to the native installer; no test tools required |
| Editable source | `pyproject.toml`; apply documented platform prerequisites/constraints. macOS self-install uses `--no-deps` only after locks supply the complete environment |
| Wheel | Built `Requires-Dist` matches all base manifest dependencies, including markers and extras; platform Torch selection remains in the install recipe |
| Docker/Compose/GHCR | Linux runtime/Torch hash locks; runtime state excluded from build and mounted separately; loopback port 8787 |
| Conda | Root `environment.yml`: Python 3.12, CPU PyTorch, pip dependencies; deliberately includes development/test tools |
| Optional extras | `guardrails` is an empty compatibility alias because NeMo is base-required. `full` adds postgres/pgvector/dev/test; `all` adds numbat-cel. CI tool locks remain purpose-specific |
| CUDA LoRA toolkit | Separate, currently blocked by Unsloth constraints conflicting with patched Transformers/TRL/Datasets pins. Mocked preparation CI is not CUDA acceptance; no security floors were lowered |

Version agreement does not mean every profile has an identical package set.
Constraints bound resolution but do not install packages. Native application
installers should not gain test/dev tools merely to match Conda or CI.

## Correction

Both native installers previously reported dependencies installed immediately
after pip installation. Existing environments can retain conflicting packages.
They now run `pip check` before success/shim creation; Bash propagates failure
through `set -e`, and PowerShell explicitly checks `$LASTEXITCODE` and throws.
Skip-dependency modes preserve their existing bypass semantics.

## Executed local checks

- `check_deps.py --strict`: D1-D11, no failures/warnings; 44 exact constraints
  and 28 Conda cross-pins agree.
- `extract_pins.py --strict`: runtime/test requirements agree with constraints.
- `check_env_drift.py --strict`: E1-E7, no failures/warnings; Python, imports,
  workflow tools, Docker install/build/port/state contracts agree.
- `scripts/check_lock_contract.py`: all recorded inputs/outputs and hashes pass.
- Isolated `python -m build --wheel`, then `check_lock_contract.py --wheel`:
  built wheel base dependency metadata matches `pyproject.toml`.
- `tests/test_installer_python_contract.py`: 12 passed on Windows, including
  successful and failed final checks. POSIX executes the actual installer with
  fake Python/pip; PowerShell executes the actual dependency block with fake pip.
  The new POSIX cases failed before the fix because no `pip check` ran.
- Ruff F/B/S, Bash syntax, and invariant guard (46 checks) pass.

The first sandbox test invocation hit PowerShell language-mode restrictions in
four pre-existing tests; the host rerun passed all 12. No real provider keys,
operator venv, credential store, corpus, or index were used by these probes.

## Acceptance limits

These checks establish contracts, wheel metadata, and installer control flow,
not fresh installation on every OS. This Windows host has no Docker/Conda or
native macOS/Linux runtime. The PR's hosted matrix supplies separate installed
runtime, wheel, Conda, and NeMo evidence where its workflows run. Native desktop
and credential-store acceptance remains in the manual native E2E workflow.
No dependency versions or generated locks changed. Existing accepted dependency
risks remain governed by `SECURITY.md`; this is not a new vulnerability scan.
