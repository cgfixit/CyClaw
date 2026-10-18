# CyClaw Project Rules

Rules for Claude Code sessions that `CLAUDE.md` does not already state. `CLAUDE.md`
is authoritative for everything else (the six invariants §3, traps §4, conventions §5,
escalation tiers §7, git identity and branch namespaces §10) and is loaded in the same
session, so it is not restated here. The Hard Rules below are the one deliberate repeat.

---

## Python specifics

- `requires-python >=3.12,<3.13`: numpy 1.26.x has no cp313 wheels, so 3.13 stays out
  until that pin moves.
- Secrets are read directly via `os.environ`/`os.getenv`; `pydantic-settings` is only a
  chromadb transitive, not a CyClaw pattern.
- Data-modifying scripts default to a safe dry-run, with `--apply` to act (see
  `retrieval/clear_cache.py`). There is no `--dry-run` flag — safe is the default.
- Async: prefer `asyncio.TaskGroup` (3.11+) with `asyncio.gather` fallback.

## Dependency notes

- **PyYAML:** install with `pip install -r requirements.txt -c constraints.txt --ignore-installed PyYAML`.

## Facts CLAUDE.md does not state

- Retrieval always runs both legs (ChromaDB semantic + BM25 keyword) fused by RRF; never bypass either leg.
- The torch CPU-first install order also keeps the pin inside the CVE-2025-32434 patched range (fixed in 2.6.0).
- Soul DB: SQLite by default; Postgres via `CYCLAW_DB_URL` or `config.personality.database_url`.
- `telegram/` runs out-of-band via `python -m telegram.cli`; `sync/` performs the Dropbox corpus sync via `rclone`.
- Commit messages reference issue numbers when applicable.
- Blocker notes go in `docs/work/SESSION_NOTES.md`; `.claude/session-notes/` does not exist and must not be created.

## Documentation Standards

- **CLAUDE.md is authoritative** — update it when architecture, modules, or behavioral rules change.
- **.claude/ structure** — keep the documented commands/hooks/rules/skills tree in sync.
- **Owner PII stays out of committed files** — `.claude/skills/`, `.claude/rules/`, `CLAUDE.md`, and `docs/` are GitHub-public. The owner's *chosen* public attribution is fine and already in tracked docs: GitHub handle `cgfixit`, the byline name he signs guides with, and `cgfixit.com` links. Everything else is out: date of birth, email addresses, home location, phone, private accounts, or any personal detail beyond that byline, even in an agent-facing prompt file (learned 2026-09-02 on PR #1272, where the owner stripped a handle/email/location/sites block from `fable-5.1-cc`, since consolidated into `fable-protocol` §8 — see that file's §11). Personal identity belongs only in the user-level `~/.claude/skills/` copy.

---

## Hard Rules (No Exceptions)

- ✋ **Never expose credentials, tokens, or secret files.**
- ✋ **Never run destructive operations without explicit user confirmation.**
- ✋ **Never push to `main` via GitHub MCP when a feature branch and open PR exist** — creates add/add rebase conflicts.
- ✋ **Never confirm a force-push without the user's explicit sign-off.**
- ✋ **Never modify `data/personality/soul.md` without a `reason` string.**
- ✋ **Never import `agentic/`, `sync/`, or other out-of-band modules into the core six: `gate.py`, `gate_ops.py`, `gate_auth.py`, `gate_memory.py`, `graph.py`, `mcp_hybrid_server.py`.**

---
