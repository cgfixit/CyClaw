---
name: dep-guard
description: "Run CyClaw offline static dependency-contract checks for manifest, lock, installer or dependency-CI changes. Use verify-dep for actual installation/profile acceptance; do not duplicate pin parsers."
---


# Check Dependency Contracts

Read the changed manifests, `setup-guide.md`, `locks/README.md` and relevant
workflows. Profiles deliberately differ: metadata/constraints, hashed runtime
and test locks, optional extras, Conda and platform-specific Torch.

Run from the root before and after changes:

```text
python .claude/skills/dep-guard/check_deps.py --strict
python .claude/skills/verify-deps/extract_pins.py --strict
python .claude/skills/verify-deps/check_env_drift.py --strict
```

Classify differences as base, optional, platform, transitive or documented
exception. Check locks and their regeneration procedure when inputs change;
do not hand-edit hashes or force profiles to identical text. NeMo belongs to
the base profile; plain macOS Torch and Linux/Windows `+cpu` are intentional.
Root `environment.yml` is the Conda profile; its workflow namesake is a no-op.

For changes to the guards themselves, run their maintained `verify.sh` mutation
self-tests and inspect CLI exit/output contracts. Report strict failures and
unavailable evidence; do not loosen pins/checks to get a green result.
This skill installs nothing. Use `$verify-dep` when install behavior is in scope.
