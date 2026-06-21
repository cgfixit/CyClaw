#!/usr/bin/env python3
"""CyClaw memory orchestrator — deterministic driver for the memory lifecycle.

This script owns the *mechanical* half of memory management: where files go,
when consolidation is due, how snapshots are deduplicated, and how Claude Code
hooks plug in. The *semantic* half (deciding what is worth remembering from a
conversation) is LLM work performed by the `memory-extraction` /
`memory-consolidation` skills — this driver computes paths and emits the
instructions that drive them.

Trigger matrix (see SKILL.md):
    manual /memory (in-session)      -> extract only
    manual /memory-orchestrator      -> consolidate + extract
    PreCompact  (context compress)   -> consolidate + extract  (hook)
    SessionEnd  (archive/delete)     -> consolidate (deterministic)  (hook)
    every 12h                        -> consolidate + extract  (timer-check)

All memory snapshots are written to docs/memories/<YYYY-MM-DD_HHMMSS>.md.

Subcommands:
    path                     Print the timestamped file path to write the next
                             memory snapshot to (ensures the dir exists). The
                             agent then Writes its extraction into that path.
    extract  [--content-file F]
                             Persist a memory snapshot. Content from F or stdin.
                             Updates the index and stamps last-extraction time.
    consolidate              Deterministically merge/dedupe docs/memories/*.md
                             snapshots into CONSOLIDATED.md; refresh INDEX.md;
                             stamp last-consolidation time. Prints a report.
    auto     [--content-file F]
                             consolidate THEN extract (lifecycle / timer path).
    timer-check              Exit 0 printing DUE / NOT DUE based on the 12h
                             consolidation interval.
    hook                     Read a Claude Code hook JSON event on stdin and
                             route it (PreCompact / SessionEnd). Emits
                             additionalContext where the platform supports it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
# Resolve the repo root from this file's location: .claude/skills/<name>/file
SKILL_DIR = Path(__file__).resolve().parent
REPO_ROOT = SKILL_DIR.parents[2]
MEM_DIR = REPO_ROOT / "docs" / "memories"
INDEX_FILE = MEM_DIR / "INDEX.md"
CONSOLIDATED_FILE = MEM_DIR / "CONSOLIDATED.md"
STATE_FILE = MEM_DIR / ".orchestrator-state.json"

CONSOLIDATION_INTERVAL_HOURS = 12

# Files the consolidator manages itself — never treated as raw snapshots.
RESERVED = {INDEX_FILE.name, CONSOLIDATED_FILE.name, "SESSION_NOTES.md"}


# ── State ────────────────────────────────────────────────────────────────────
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(**updates) -> None:
    MEM_DIR.mkdir(parents=True, exist_ok=True)
    state = _load_state()
    state.update(updates)
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")


def _stamp() -> str:
    return _now().strftime("%Y-%m-%d_%H%M%S")


def _timestamped_path() -> Path:
    return MEM_DIR / f"{_stamp()}.md"


# ── Snapshot discovery ───────────────────────────────────────────────────────
SNAPSHOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}\.md$")


def _snapshots() -> list[Path]:
    if not MEM_DIR.exists():
        return []
    return sorted(
        p for p in MEM_DIR.glob("*.md")
        if p.name not in RESERVED and SNAPSHOT_RE.match(p.name)
    )


# ── path ─────────────────────────────────────────────────────────────────────
def cmd_path(_args) -> int:
    MEM_DIR.mkdir(parents=True, exist_ok=True)
    print(_timestamped_path())
    return 0


# ── extract ──────────────────────────────────────────────────────────────────
def _read_content(args) -> str:
    if args.content_file:
        return Path(args.content_file).read_text()
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


def cmd_extract(args) -> int:
    MEM_DIR.mkdir(parents=True, exist_ok=True)
    content = _read_content(args).strip()
    target = _timestamped_path()

    if not content:
        # No content supplied: lay down a scaffold for the agent to fill in.
        content = (
            f"# Memory snapshot — {_stamp()}\n\n"
            "<!-- Filled by the memory-extraction skill. Sections below are "
            "the standard memory categories; delete any that are empty. -->\n\n"
            "## User preferences\n\n"
            "## Project patterns\n\n"
            "## Error corrections\n\n"
            "## Workflow notes\n"
        )
    elif not content.startswith("#"):
        content = f"# Memory snapshot — {_stamp()}\n\n{content}\n"

    target.write_text(content if content.endswith("\n") else content + "\n")
    _save_state(last_extraction=_now().isoformat())
    _refresh_index()
    print(f"[memory] extracted -> {target.relative_to(REPO_ROOT)}", file=sys.stderr)
    return 0


# ── consolidate ──────────────────────────────────────────────────────────────
def _split_sections(text: str) -> dict[str, list[str]]:
    """Group bullet/line content under their nearest '## ' heading."""
    sections: dict[str, list[str]] = {}
    current = "Uncategorized"
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections.setdefault(current, [])
        elif line.startswith("# "):
            continue  # snapshot title — skip
        elif line.strip():
            sections.setdefault(current, []).append(line.rstrip())
    return sections


def cmd_consolidate(_args) -> int:
    MEM_DIR.mkdir(parents=True, exist_ok=True)
    snaps = _snapshots()
    merged: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}

    for snap in snaps:
        for section, lines in _split_sections(snap.read_text()).items():
            bucket = merged.setdefault(section, [])
            seenset = seen.setdefault(section, set())
            for line in lines:
                key = re.sub(r"\s+", " ", line.strip().lower())
                if key and key not in seenset:
                    seenset.add(key)
                    bucket.append(line)

    total_lines = sum(len(v) for v in merged.values())
    out = [f"# Consolidated memory — {_stamp()}", ""]
    out.append(
        f"_Structural merge of {len(snaps)} snapshot(s); "
        f"{total_lines} unique line(s) across {len(merged)} section(s). "
        "Run the memory-consolidation skill for semantic merge._"
    )
    out.append("")
    for section in sorted(merged):
        if not merged[section]:
            continue
        out.append(f"## {section}")
        out.append("")
        out.extend(merged[section])
        out.append("")
    CONSOLIDATED_FILE.write_text("\n".join(out).rstrip() + "\n")
    _save_state(last_consolidation=_now().isoformat())
    _refresh_index()
    print(
        f"[memory] consolidated {len(snaps)} snapshot(s) -> "
        f"{CONSOLIDATED_FILE.relative_to(REPO_ROOT)} "
        f"({total_lines} unique lines, {len(merged)} sections)",
        file=sys.stderr,
    )
    return 0


# ── index ────────────────────────────────────────────────────────────────────
def _refresh_index() -> None:
    snaps = _snapshots()
    lines = ["# Memory index", ""]
    state = _load_state()
    lc = state.get("last_consolidation", "never")
    le = state.get("last_extraction", "never")
    lines += [
        f"- Last extraction: `{le}`",
        f"- Last consolidation: `{lc}`",
        f"- Snapshots: {len(snaps)}",
        "",
    ]
    if CONSOLIDATED_FILE.exists():
        lines.append(f"- Working set: [`{CONSOLIDATED_FILE.name}`]({CONSOLIDATED_FILE.name})")
        lines.append("")
    lines.append("## Snapshots (newest first)")
    lines.append("")
    for snap in reversed(snaps):
        lines.append(f"- [`{snap.name}`]({snap.name})")
    INDEX_FILE.write_text("\n".join(lines).rstrip() + "\n")


# ── auto (consolidate then extract) ──────────────────────────────────────────
def cmd_auto(args) -> int:
    rc = cmd_consolidate(args)
    if rc != 0:
        return rc
    return cmd_extract(args)


# ── timer-check ──────────────────────────────────────────────────────────────
def cmd_timer_check(_args) -> int:
    state = _load_state()
    last = state.get("last_consolidation")
    due = True
    if last:
        try:
            elapsed = _now() - datetime.fromisoformat(last)
            due = elapsed.total_seconds() >= CONSOLIDATION_INTERVAL_HOURS * 3600
        except ValueError:
            due = True
    if due:
        print(f"DUE (interval {CONSOLIDATION_INTERVAL_HOURS}h; last={last or 'never'})")
    else:
        print(f"NOT DUE (last={last})")
    return 0


# ── hook ─────────────────────────────────────────────────────────────────────
_EXTRACT_INSTRUCTION = (
    "Memory orchestrator: before this context is compacted, run the "
    "memory-extraction skill now. Get the target path from "
    "`python3 .claude/skills/memory-orchestrator/orchestrate.py path` and write "
    "the snapshot directly to it. A deterministic consolidation has already run. "
    "Keep it brief; capture durable user preferences, project patterns, error "
    "corrections, and workflow notes from the recent messages only."
)


def cmd_hook(_args) -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        event = {}
    name = event.get("hook_event_name", "")

    if name == "PreCompact":
        # Deterministic consolidation runs now; ask the agent to do the
        # semantic extraction before compaction proceeds.
        cmd_consolidate(_args)
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PreCompact",
                "additionalContext": _EXTRACT_INSTRUCTION,
            }
        }
        print(json.dumps(out))
        return 0

    if name == "SessionEnd":
        # No agent turn is possible as the session ends — run the deterministic
        # consolidation snapshot so on-disk memory is left tidy. Semantic
        # extraction of this conversation cannot be LLM-performed here.
        cmd_consolidate(_args)
        print("[memory] SessionEnd: deterministic consolidation complete.", file=sys.stderr)
        return 0

    # Unknown event — no-op, never block.
    return 0


# ── CLI ──────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CyClaw memory orchestrator")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("path", help="print next snapshot path")

    p_ex = sub.add_parser("extract", help="persist a memory snapshot")
    p_ex.add_argument("--content-file", help="read snapshot content from this file")

    sub.add_parser("consolidate", help="merge/dedupe snapshots")

    p_auto = sub.add_parser("auto", help="consolidate then extract")
    p_auto.add_argument("--content-file", help="read snapshot content from this file")

    sub.add_parser("timer-check", help="is consolidation due?")
    sub.add_parser("hook", help="route a Claude Code hook event from stdin")

    args = parser.parse_args(argv)
    return {
        "path": cmd_path,
        "extract": cmd_extract,
        "consolidate": cmd_consolidate,
        "auto": cmd_auto,
        "timer-check": cmd_timer_check,
        "hook": cmd_hook,
    }[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
