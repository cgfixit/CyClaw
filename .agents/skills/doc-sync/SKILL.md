---
name: doc-sync
description: "Reconcile CyClaw documentation after source, config, skill or workflow changes. Run the maintained checker and verify claims against their owners."
---

# Reconcile Documentation

Read the affected source, config, workflow and derived docs at the inspected SHA. Check commands, paths, install profiles and security claims manually. For README work include `docs/SYNC_README.md` and `docs/agentic/AGENTIC_README.md` beyond basename discovery.

From the root, run `python .claude/skills/doc-sync/doc_sync.py` with PyYAML and Git. The local wrapper forwards arguments and exit status. Its result covers mechanical drift. Use source and matching execution evidence for runtime or native claims.

Keep shared guidance in `AGENTS.md` and the Codex inventory in `.codex/README.md`. For skill edits, run `python scripts/check_codex_skills.py` and inspect callers for moved references.

Rerun doc-sync and `git diff --check`. For checker or wrapper changes run the maintained `verify.sh` and relevant `test_contracts.py` cases. POSIX fixtures need native path handling. Report any Windows Python/Git Bash limitation.
