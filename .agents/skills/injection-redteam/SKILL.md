---
name: injection-redteam
description: "Check CyClaw sanitizer regressions and false positives with synthetic local inputs. Use for sanitizer changes or defensive boundary reviews."
---

# Probe the Sanitizer

Read `utils/sanitizer.py`, effective config and the maintained corpus. Run `python .claude/skills/injection-redteam/redteam.py --json` and distinguish marked `open_finding` entries from regressions.

Check a relevant synthetic refusal and harmless near-miss at the changed HTTP, MCP or retrieval entry point. Inspect observable handling and audit behavior. Keep private inputs and external providers out of the probe.

For sanitizer edits, preserve the corpus and policy, rerun the probe and invariant guard, and follow `CLAUDE.md` section 5. For checker contract edits, use its `verify.sh`. Report baseline or newly observed failures and impact.
