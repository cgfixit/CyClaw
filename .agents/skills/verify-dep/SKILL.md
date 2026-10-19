---
name: verify-dep
description: "Verify a selected CyClaw dependency/install profile and supply-chain change. Use for hashed installs, locks, Docker, Conda, platform installers or releases; dep-guard owns offline pin-contract checks."
---


# Verify an Install Profile

Run `$dep-guard` first. Read `setup-guide.md`, `locks/README.md`, the affected
installer and active CI job. Treat manifests as profile inputs, not identical
copies or a reason to add another dependency source of truth.

| Surface | Acceptance source |
| --- | --- |
| Native/manual runtime | Platform Torch lock, then platform runtime lock with `--require-hashes`; selected interpreter is Python 3.12 |
| Tests/tooling | Separate test or CI-purpose lock; do not add it to the base container |
| Editable/optional extras | `pyproject.toml` under the documented constraints/profile procedure |
| Lock updates | `locks/README.md`, maintained generation/check scripts and lock workflows |
| Docker/Compose | Actual Dockerfile/Compose and build workflow; a host pip install is not container proof |
| Conda | Root `environment.yml` and its native workflow |
| Native installers | `macos/`, `powershell/`, one-shot scripts and their platform jobs |

Validate only the changed profile in a disposable environment. Use its actual
documented install or supported dry-run; do not replace a hashed runtime install
with legacy unconstrained requirements or copy a dated Torch/pip pin. Dry-run
resolution is distinct from installed/imported/native acceptance. macOS uses
plain Torch; Linux/Windows use CPU wheels. Read current lock selection and CPU
wheel acquisition order before executing. Never delete the operator's venv.

After a real install, run `python -m pip check`. For NeMo install acceptance,
`python -m guardrails.verify_install` must exercise a real engine and shipped
allow/refuse behavior; deterministic fallback alone is insufficient.

For Docker/Compose changes, run available syntax/build checks and an isolated
smoke. For optional services or native keystore/confinement behavior, require
matching evidence. Do not manufacture platform parity from one host.

For pin changes review primary release/advisory sources and the existing
pip-audit/OSV/Trivy/optional-extra workflows. Preserve justified accepted-risk
scope; a new release is not an automatic bump instruction. Follow `CLAUDE.md`
section 5 for verification and the PR workflow for publication.
Report profile, command/exit/output, resolved versus installed state, exceptions,
advisories and unverified native/service lanes. Do not change defaults or policy
to satisfy old documentation.
