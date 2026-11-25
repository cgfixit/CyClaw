---
name: dep-guard
description: "Check CyClaw dependency contracts offline after manifest, lock, installer or dependency-CI changes. Use verify-dep for install acceptance."
---

# Check Dependency Contracts

Review the changed inputs and owning workflows against `setup-guide.md` and `locks/README.md`. Run before and after from the root:

```text
python .claude/skills/dep-guard/check_deps.py --strict
python .claude/skills/verify-deps/extract_pins.py --strict
python .claude/skills/verify-deps/check_env_drift.py --strict
```

Classify differences by profile, platform, transitive dependency or documented exception. NeMo is base. macOS uses plain Torch and Linux/Windows use CPU wheels. Regenerate hashes with the owning tool. The root `environment.yml` is the Conda profile.

For guard edits, run the maintained `verify.sh` mutation checks and inspect failure output and exit status. Report strict failures without weakening the contract.
