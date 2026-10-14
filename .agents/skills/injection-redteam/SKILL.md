---
name: injection-redteam
description: "Probe CyClaw sanitizer regressions and false positives with synthetic local inputs. Use for injection-boundary review or pattern changes; preserve known findings and never ask an external model to judge private content."
---


# Probe the Sanitizer

Read `utils/sanitizer.py`, current config and the maintained probe corpus.
Run `python .claude/skills/injection-redteam/redteam.py --json`.
Distinguish known `open_finding` entries from new regressions.

Add a relevant negative probe outside the corpus for a read-only run: confusables,
case/whitespace splits, malformed/empty/long input or a harmless near-miss.
Exercise the actual changed HTTP/MCP/retrieval entry point; regex matching alone
does not prove the scanner is called there. Inspect rejection and audit behavior.

For an authorized sanitizer change preserve the corpus, rerun the probe and
invariant guard, and follow `CLAUDE.md` section 5 for verification. Run the
maintained `verify.sh` when changing its contract. Never remove probes, suppress
findings or alter policy to improve a score. Report bypasses and false positives
with a synthetic trigger and impact; keep private documents and providers out.
