---
name: doc-sync
description: "Reconcile CyClaw derived documentation with current source after code, config, command, skill or workflow changes. Use the maintained checker plus a manual claim/reference pass; never change behavior to match prose."
---


# Reconcile Documentation

1. Read the affected source/config/workflow and derived documentation. Record
   the inspected checkout; historical audits are evidence for their own SHA.
2. Run the maintained checker from the root:

   ```text
   python .claude/skills/doc-sync/doc_sync.py
   ```

   The local `doc_sync.py` wrapper forwards arguments and exit codes to that
   implementation. It requires PyYAML and Git. A clean result is mechanical
   evidence, not proof of all prose, runtime reachability or native keystores.
3. Manually verify changed commands, installer/lock profiles, security claims
   and source paths. For README work include `docs/SYNC_README.md` and
   `docs/agentic/AGENTIC_README.md`, which are outside basename README discovery.
4. Update derived guidance only. Use root `AGENTS.md` for shared instructions
   and `.codex/README.md` for the inventory; avoid duplicate architecture or
   version snapshots. Repository skills live in `.agents/skills/`.
5. Validate touched manifests and `agents/openai.yaml`: unique name matching
   folder, focused description, exact `$name` default prompt and intended
   `allow_implicit_invocation`. Check references/callers when moving resources.
6. Rerun doc-sync and `git diff --check`. If the checker/wrapper changes, use
   its maintained `verify.sh` and `test_contracts.py` to check rejected drift
   and argument/error forwarding. POSIX fixture self-tests need native path
   handling; Windows Python under Git Bash is a distinct limitation.

Keep factual changes separate from product changes. Do not interpret a checker
warning as permission to enable features, edit soul or weaken a control.
