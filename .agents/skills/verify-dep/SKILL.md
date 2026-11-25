---
name: verify-dep
description: "Verify a selected CyClaw install profile or supply-chain change. Use for hashed installs, Docker, Conda, native installers and releases."
---

# Verify an Install Profile

Run `$dep-guard` first. Use `setup-guide.md`, `locks/README.md` and the owning installer or active CI job.

| Profile | Acceptance source |
| --- | --- |
| Native/manual | Python 3.12, platform Torch lock followed by runtime lock with `--require-hashes`. macOS uses plain Torch and Linux/Windows use CPU wheels. |
| Tooling and optional extras | Dedicated test/CI locks or constrained `pyproject.toml` extras. Keep test tools outside base images. |
| Docker/Compose | Actual build configuration and isolated smoke. |
| Conda | Root `environment.yml` and its native workflow. |
| Native installer | `macos/`, `powershell/`, one-shot scripts and matching jobs. |

Use a disposable environment and the changed profile's documented install or supported dry-run. Preserve the operator's venv. Regenerate locks with the owning tooling and follow documented wheel acquisition order.

After installation run `python -m pip check`. For NeMo, `python -m guardrails.verify_install` needs a real engine and shipped allow/refuse behavior. Keep dry-run resolution, imports, service behavior and native keystore or confinement evidence distinct.

For pin changes verify primary release/advisory sources and relevant pip-audit, OSV, Trivy and optional-extra workflows. Preserve justified exceptions. Report profile, observed output, exit status and missing native/service lanes. Use `CLAUDE.md` section 5 for verification and the PR workflow for authorized publication.
