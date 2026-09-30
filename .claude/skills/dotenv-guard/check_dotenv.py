#!/usr/bin/env python3
"""check_dotenv.py – keep secrets out of dotenv files, gitignored or not.

Usage:
    python3 .claude/skills/dotenv-guard/check_dotenv.py [--repo-root PATH]
                                                        [--baseline PATH]

`.gitignore` keeps a dotenv file off GitHub. It does not keep the plaintext
copy on disk from being sourced into every new shell, read by any process
running as the user, swept into a backup, or pulled into an AI coding agent's
context from the workspace. CyClaw's gateway reads secrets from the
environment and loads no dotenv file itself. This checker guards the paths
that put secrets INTO dotenv files, and the shell hook that spreads them.

It is deliberately NOT a duplicate of its neighbours:
  * invariant-guard checks the six invariants and the G1-G5 structure guards.
    Secrets at rest are neither.
  * gitleaks scans committed secret VALUES. A gitignored ~/.CyClaw/.env never
    reaches git, so gitleaks cannot see it. This checker looks at the scripts
    and docs that create such files, by variable NAME.
  * ruff S105/S106 flag hardcoded passwords in Python source only.
  * tests/test_setup_cyclaw_keys.py pins what setup-cyclaw-keys.sh does today.
    This checker states the policy that behavior is measured against.

A name is secret-classified when it matches
^[A-Z][A-Z0-9_]*_(API_KEY|TOKEN|SECRET|PASSWORD)$ (case-sensitive; the same
suffix set proposed in open draft PR #1507).

Checks:
  K1  Python outside tests/ loads no dotenv file: no `dotenv` import, no
      load_dotenv/dotenv_values/find_dotenv call, no pydantic-settings
      `env_file`.
  K2  Tracked dotenv-shaped files (.env, *.env, .env.*) assign no secret name.
  K3  .gitignore still ignores dotenv files at any depth.
  K4  macos/setup-cyclaw-keys.sh, run in a throwaway HOME with a fake
      `security` and a fake checkout, writes no secret assignment into any
      dotenv file. POSIX only.
  K5  The shell rc file that same run writes neither assigns a secret nor
      `.`/`source`s a dotenv file directly. POSIX only.
  K6  No tracked shell, PowerShell, or cmd line writes a literal secret
      assignment to a dotenv path (redirect, tee, heredoc body,
      Add-Content/Set-Content/Out-File, [IO.File]::Write*/Append*).
  K7  No tracked Markdown line pairs a secret assignment with a dotenv file,
      and no ```dotenv / ```env block assigns a secret.

K6 and K7 are line heuristics. They see literal names only: a name that
reaches a writer through a variable is invisible to them, which is why K4
runs the macOS keys script instead of reading it. Windows has no such probe;
its installers are covered by K6 alone.

Baseline (ratchet): baseline.txt, next to this script, lists findings that
exist on main by design, one per line as RULE<TAB>KEY<TAB>REASON.
    KNOWN  a baselined finding. Reported, does not fail.
    FAIL   a finding not in the baseline; a baseline entry that no longer
           matches anything (delete it, so the fixed violation cannot come
           back silently); or a probe that could not run.
Keys carry no line numbers, so unrelated edits do not churn the baseline.

Exit codes (repo convention):
    0  no new finding and no stale baseline entry
    2  a FAIL tripped
    3  env error (git missing, not a work tree, baseline malformed)
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SECRET_NAME = re.compile(r"^[A-Z][A-Z0-9_]*_(?:API_KEY|TOKEN|SECRET|PASSWORD)$")

# `NAME=` anywhere in a line (script string, doc prose). The lookbehind keeps
# `$NAME = x` comparisons and longer identifiers out.
_ASSIGN_ANYWHERE = re.compile(
    r"(?<![A-Za-z0-9_$])([A-Z][A-Z0-9_]*_(?:API_KEY|TOKEN|SECRET|PASSWORD))\s*="
)
# A dotenv assignment line: `NAME=...` or `export NAME=...`.
_ASSIGN_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
# `.env`, `x.env`, `.env.local`, `$HOME/.CyClaw/.env`; not `.environ`.
_DOTENV_TOKEN = re.compile(r"\.env(?![A-Za-z0-9_])")
# A variable that plainly names a dotenv file: $ENV_FILE, ${env_file}, $envFile.
_DOTENV_VAR = re.compile(r"\$\{?[A-Za-z_]*(?:ENV_?FILE|DOTENV)[A-Za-z0-9_]*\}?", re.IGNORECASE)
# Write contexts. `2>` / `>&2` are stream plumbing, not file writes.
_SHELL_WRITE = re.compile(r"(?<![0-9&])>>?(?!&)|\btee\b")
_PS_WRITE = re.compile(
    r"\b(?:Add-Content|Set-Content|Out-File)\b|\[(?:System\.)?IO\.File\]::(?:Write|Append)All(?:Text|Lines)",
    re.IGNORECASE,
)
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
# `. "$HOME/.CyClaw/.env"` / `source ~/.env` on a line of its own.
_RAW_SOURCE = re.compile(r"""^\s*(?:\.|source)\s+(["']?)([^"'\s;&|]+)\1\s*(?:[;&|#].*)?$""")
_FENCE = re.compile(r"^\s*(```+|~~~+)\s*([A-Za-z0-9_+-]*)")

_SCRIPT_SUFFIXES = {".sh", ".bash", ".zsh", ".ps1", ".psm1", ".cmd", ".bat"}
# Fixtures, history, and this skill's own planted examples.
_SKIP_PREFIXES = ("tests/", "docs/audits/", "docs/memories/", ".claude/skills/dotenv-guard/")
_DOTENV_CALLS = {"load_dotenv", "dotenv_values", "find_dotenv"}
_RC_FILES = (".zshrc", ".zprofile", ".zshenv", ".zlogin", ".bashrc", ".bash_profile", ".bash_login", ".profile")
_GITIGNORE_PROBES = (".env", "a/.env", "a/b/.env", "app.env", ".env.local", ".env.production")

# The probe is the documented non-interactive install: generate the API key,
# store GROK_API_KEY=dummy, point the checkout .env at a fake checkout so the
# real one is never written.
_PROBE_ARGS = ("--skip-prompts", "--no-print-key", "--no-copy-key", "--grok-dummy")
_FAKE_SECURITY = """#!/usr/bin/env bash
# dotenv-guard probe stub. No real Keychain: every lookup reports "not found"
# (exit 44); every store succeeds, logs only its service name, and discards
# the secret it is handed.
case "${1:-}" in
  find-generic-password) exit 44 ;;
  add-generic-password)
    while [ "$#" -gt 0 ]; do
      if [ "$1" = "-s" ] && [ "$#" -gt 1 ]; then printf '%s\\n' "$2" >> "$DOTENV_GUARD_STORE_LOG"; fi
      shift
    done
    cat >/dev/null 2>&1 || true
    exit 0 ;;
  *) echo "dotenv-guard fake security: unsupported command ${1:-}" >&2; exit 1 ;;
esac
"""

RULES = ("K1", "K2", "K3", "K4", "K5", "K6", "K7")
TITLES = {
    "K1": "Python loads no dotenv file",
    "K2": "tracked dotenv files assign no secret",
    "K3": ".gitignore ignores dotenv files",
    "K4": "keys script writes no secret into a dotenv file",
    "K5": "keys script rc block neither assigns a secret nor sources a dotenv",
    "K6": "scripts write no literal secret to a dotenv path",
    "K7": "docs pair no secret assignment with a dotenv file",
}


class EnvError(Exception):
    """Exit 3: the checker cannot inspect this tree."""


class ProbeError(Exception):
    """A check could not run. Fails closed (exit 2)."""


Finding = tuple[str, str]  # (stable key, human detail)


def is_dotenv_name(name: str) -> bool:
    return name == ".env" or name.endswith(".env") or name.startswith(".env.")


def secret_assignments(text: str) -> list[str]:
    """Secret names assigned by dotenv-style lines, in first-seen order."""
    names: list[str] = []
    for line in text.splitlines():
        m = _ASSIGN_LINE.match(line)
        if m and SECRET_NAME.match(m.group(1)) and m.group(1) not in names:
            names.append(m.group(1))
    return names


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    git = shutil.which("git")
    if not git:
        raise EnvError("git not found on PATH")
    return subprocess.run(  # noqa: S603 -- resolved git binary, argv list, no shell
        [git, "-C", str(root), *args], capture_output=True, text=True, check=False
    )


def tracked_files(root: Path) -> list[str]:
    proc = _git(root, "ls-files", "-z")
    if proc.returncode != 0:
        raise EnvError(f"{root} is not a git work tree: {proc.stderr.strip()}")
    return sorted(p for p in proc.stdout.split("\0") if p)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""  # tracked but absent from the work tree (e.g. a sparse checkout)


def _skipped(rel: str) -> bool:
    return rel.startswith(_SKIP_PREFIXES)


# ── K1 ──────────────────────────────────────────────────────────────────────
def check_k1(root: Path, files: list[str]) -> list[Finding]:
    found: dict[str, str] = {}
    for rel in files:
        if not rel.endswith(".py") or rel.startswith("tests/"):
            continue
        try:
            tree = ast.parse(_read(root / rel), filename=rel)
        except (SyntaxError, ValueError):
            continue  # not ours to parse; ruff reports syntax errors
        for node in ast.walk(tree):
            what = None
            if isinstance(node, ast.Import):
                if any(a.name == "dotenv" or a.name.startswith("dotenv.") for a in node.names):
                    what = "import dotenv"
            elif isinstance(node, ast.ImportFrom):
                if node.module and (node.module == "dotenv" or node.module.startswith("dotenv.")):
                    what = "from dotenv import"
            elif isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
                if name in _DOTENV_CALLS:
                    what = f"{name}()"
                elif any(kw.arg == "env_file" for kw in node.keywords):
                    what = "env_file= (pydantic-settings)"
            elif isinstance(node, ast.ClassDef):
                for stmt in node.body:
                    targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target] if isinstance(stmt, ast.AnnAssign) else []
                    if any(isinstance(t, ast.Name) and t.id == "env_file" for t in targets):
                        what = "env_file class attribute (pydantic-settings)"
            if what:
                key = f"{rel}:{what}"
                found.setdefault(key, f"{rel}:{getattr(node, 'lineno', '?')} {what}")
    return sorted(found.items())


# ── K2 ──────────────────────────────────────────────────────────────────────
def check_k2(root: Path, files: list[str]) -> list[Finding]:
    out: list[Finding] = []
    for rel in files:
        if not is_dotenv_name(Path(rel).name):
            continue
        for name in secret_assignments(_read(root / rel)):
            out.append((f"{rel}:{name}", f"tracked {rel} assigns {name}"))
    return out


# ── K3 ──────────────────────────────────────────────────────────────────────
def check_k3(root: Path) -> list[Finding]:
    out: list[Finding] = []
    for probe in _GITIGNORE_PROBES:
        proc = _git(root, "check-ignore", "--no-index", "-q", "--", probe)
        if proc.returncode == 1:
            out.append((probe, f"{probe} is not ignored by .gitignore"))
        elif proc.returncode != 0:
            raise ProbeError(f"git check-ignore {probe} failed: {proc.stderr.strip()}")
    return out


# ── K4 / K5 ─────────────────────────────────────────────────────────────────
def _redact(text: str) -> str:
    text = re.sub(r"[0-9A-Fa-f]{32,}", "<redacted>", text)
    return re.sub(r"([A-Z][A-Z0-9_]*_(?:API_KEY|TOKEN|SECRET|PASSWORD)\s*=\s*)\S+", r"\1<redacted>", text)


def probe_keys_script(root: Path) -> tuple[list[Finding], list[Finding], list[str]]:
    script = root / "macos" / "setup-cyclaw-keys.sh"
    if not script.is_file():
        raise ProbeError("macos/setup-cyclaw-keys.sh not found")
    bash = shutil.which("bash")
    if not bash:
        raise ProbeError("bash not found on PATH")
    with tempfile.TemporaryDirectory(prefix="dotenv-guard-") as tmp_name:
        tmp = Path(tmp_name)
        home, checkout, fakebin = tmp / "home", tmp / "checkout", tmp / "bin"
        for d in (home, checkout, fakebin):
            d.mkdir()
        (checkout / "gate.py").write_text("# dotenv-guard probe: fake checkout marker\n", encoding="utf-8")
        stub = fakebin / "security"
        stub.write_text(_FAKE_SECURITY, encoding="utf-8")
        stub.chmod(0o755)

        env = {k: v for k, v in os.environ.items() if not SECRET_NAME.match(k)}
        for k in ("CYCLAW_HOME", "CYCLAW_REPO", "CYCLAW_GATE_PORT", "ZDOTDIR", "BASH_ENV", "ENV"):
            env.pop(k, None)
        env.update({
            "HOME": str(home),
            "SHELL": "/bin/zsh",
            "PATH": f"{fakebin}{os.pathsep}{os.environ.get('PATH', '')}",
            "CYCLAW_SETUP_KEYS_SKIP_PLATFORM": "1",
            "CYCLAW_SETUP_KEYS_STDIN_STORE": "1",
            "DOTENV_GUARD_STORE_LOG": str(tmp / "stores.log"),
        })
        argv = [bash, str(script), *_PROBE_ARGS, "--repo-path", str(checkout)]
        try:
            proc = subprocess.run(  # noqa: S603 -- resolved bash + the repo's own script, argv list, no shell
                argv, cwd=tmp, env=env, capture_output=True, text=True,
                timeout=120, stdin=subprocess.DEVNULL, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProbeError("keys-script probe timed out after 120s") from exc
        if proc.returncode != 0:
            tail = " | ".join(_redact(proc.stderr).strip().splitlines()[-5:])
            raise ProbeError(f"keys-script probe exited {proc.returncode}: {tail}")
        store_log = tmp / "stores.log"
        stores = store_log.read_text(encoding="utf-8").split() if store_log.is_file() else []
        if not stores:
            # Positive control: a run that stores nothing proves nothing about
            # where secrets go, so it must not pass K4/K5 by default.
            raise ProbeError("keys-script probe stored no Keychain item; it no longer exercises the install path")

        def label(path: Path) -> str:
            for base, name in ((home, "~"), (checkout, "<checkout>")):
                if path.is_relative_to(base):
                    return f"{name}/{path.relative_to(base).as_posix()}"
            return path.relative_to(tmp).as_posix()

        k4: list[Finding] = []
        for path in sorted(p for p in tmp.rglob("*") if p.is_file() and is_dotenv_name(p.name)):
            if path.is_relative_to(fakebin):
                continue
            for name in secret_assignments(_read(path)):
                k4.append((f"{label(path)}:{name}", f"probe wrote {name} into {label(path)}"))

        k5: list[Finding] = []
        for rc_name in _RC_FILES:
            rc = home / rc_name
            if not rc.is_file():
                continue
            text = _read(rc)
            for name in secret_assignments(text):
                k5.append((f"~/{rc_name}:{name}", f"probe wrote {name} into ~/{rc_name}"))
            for line in text.splitlines():
                m = _RAW_SOURCE.match(line)
                if m and is_dotenv_name(Path(m.group(2)).name):
                    k5.append((f"~/{rc_name}:{m.group(2)}", f"~/{rc_name} sources {m.group(2)} into every shell"))
        return k4, k5, stores


# ── K6 ──────────────────────────────────────────────────────────────────────
def _is_script(root: Path, rel: str) -> bool:
    if Path(rel).suffix.lower() in _SCRIPT_SUFFIXES:
        return True
    if Path(rel).suffix:
        return False
    try:
        with (root / rel).open("rb") as fh:
            first = fh.readline(200)
    except OSError:
        return False
    return first.startswith(b"#!") and b"sh" in first


def _names_dotenv_target(line: str) -> bool:
    return bool(_DOTENV_TOKEN.search(line) or _DOTENV_VAR.search(line))


def check_k6(root: Path, files: list[str]) -> list[Finding]:
    found: dict[str, str] = {}

    def hit(rel: str, lineno: int, name: str, how: str) -> None:
        found.setdefault(f"{rel}:{name}", f"{rel}:{lineno} writes {name} to a dotenv path ({how})")

    for rel in files:
        if _skipped(rel) or not _is_script(root, rel):
            continue
        lines = _read(root / rel).splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            writes = _SHELL_WRITE.search(line) or _PS_WRITE.search(line)
            if writes and _names_dotenv_target(line):
                for name in _ASSIGN_ANYWHERE.findall(line):
                    hit(rel, i + 1, name, "same line")
                doc = _HEREDOC.search(line)
                if doc:
                    term, strip_tabs = doc.group(2), "<<-" in line
                    j = i + 1
                    while j < len(lines):
                        body = lines[j].lstrip("\t") if strip_tabs else lines[j]
                        if body == term:
                            break
                        for name in _ASSIGN_ANYWHERE.findall(lines[j]):
                            hit(rel, j + 1, name, "heredoc")
                        j += 1
                    i = j
            i += 1
    return sorted(found.items())


# ── K7 ──────────────────────────────────────────────────────────────────────
def check_k7(root: Path, files: list[str]) -> list[Finding]:
    found: dict[str, str] = {}
    for rel in files:
        if not rel.endswith(".md") or _skipped(rel):
            continue
        fence: str | None = None
        dotenv_block = False
        first_in_block = False
        for lineno, line in enumerate(_read(root / rel).splitlines(), 1):
            m = _FENCE.match(line)
            if m and (fence is None or m.group(1).startswith(fence[0]) and len(m.group(1)) >= len(fence)):
                if fence is None:
                    fence, dotenv_block, first_in_block = m.group(1), m.group(2).lower() in {"dotenv", "env"}, True
                else:
                    fence = None
                continue
            if fence is not None and first_in_block and line.strip():
                first_in_block = False
                if line.lstrip().startswith("#") and _DOTENV_TOKEN.search(line):
                    dotenv_block = True  # e.g. a block that opens with `# ~/.CyClaw/.env`
            names = _ASSIGN_ANYWHERE.findall(line)
            if not names:
                continue
            if (fence is not None and dotenv_block) or _DOTENV_TOKEN.search(line):
                for name in names:
                    found.setdefault(f"{rel}:{name}", f"{rel}:{lineno} shows {name} in a dotenv file")
    return sorted(found.items())


# ── baseline + driver ───────────────────────────────────────────────────────
def load_baseline(path: Path) -> dict[tuple[str, str], str]:
    if not path.is_file():
        raise EnvError(f"baseline not found: {path}")
    entries: dict[tuple[str, str], str] = {}
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parts = [p.strip() for p in raw.split("\t")]
        if len(parts) != 3 or not all(parts):
            raise EnvError(f"{path}:{n}: want RULE<TAB>KEY<TAB>REASON, all non-empty")
        rule, key, reason = parts
        if rule not in RULES:
            raise EnvError(f"{path}:{n}: unknown rule {rule!r}")
        if (rule, key) in entries:
            raise EnvError(f"{path}:{n}: duplicate entry {rule} {key}")
        entries[(rule, key)] = reason
    return entries


def run(root: Path, baseline_path: Path) -> int:
    baseline = load_baseline(baseline_path)
    files = tracked_files(root)
    # A str result is a skip reason; a ProbeError fails closed.
    results: dict[str, list[Finding] | ProbeError | str] = {}
    probe_note = ""

    for rule, fn in (("K1", lambda: check_k1(root, files)), ("K2", lambda: check_k2(root, files)),
                     ("K3", lambda: check_k3(root))):
        try:
            results[rule] = fn()
        except ProbeError as exc:
            results[rule] = exc
    if os.name == "nt":
        results["K4"] = results["K5"] = "POSIX-only probe; not run on this platform (CI runs it on Linux)"
    else:
        try:
            results["K4"], results["K5"], stores = probe_keys_script(root)
            probe_note = f"probe ran; fake Keychain received {len(stores)} store(s): {', '.join(stores)}"
        except ProbeError as exc:
            results["K4"], results["K5"] = exc, "the shared probe failed; see K4"
    results["K6"] = check_k6(root, files)
    results["K7"] = check_k7(root, files)

    new = stale = known = 0
    failed = False
    for rule in RULES:
        print(f"{rule} {TITLES[rule]}")
        res = results[rule]
        if isinstance(res, str):
            print(f"  skip  [{rule}] {res}")
            continue
        if rule == "K4" and probe_note:
            print(f"  info  [K4] {probe_note}")
        if isinstance(res, ProbeError):
            print(f"  FAIL  [{rule}] could not run: {res}")
            failed = True
            continue
        res = list(dict(res).items())  # one line per key, even if a probe repeats itself
        keys = {key for key, _ in res}
        for key, detail in res:
            if (rule, key) in baseline:
                known += 1
                print(f"  KNOWN [{rule}] {detail} (baseline: {baseline[(rule, key)]})")
            else:
                new += 1
                print(f"  FAIL  [{rule}] {detail}")
        for (b_rule, b_key) in baseline:
            if b_rule == rule and b_key not in keys:
                stale += 1
                print(f"  FAIL  [{rule}] stale baseline entry {b_key!r} matches nothing now; delete it from {baseline_path.name}")
        if not res and not any(b_rule == rule for b_rule, _ in baseline):
            print(f"  ok    [{rule}] clean")

    print()
    print(f"{new} new, {stale} stale, {known} known (baselined)")
    return 2 if (failed or new or stale) else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--repo-root", type=Path, default=None)
    p.add_argument("--baseline", type=Path, default=None,
                   help="defaults to <repo-root>/.claude/skills/dotenv-guard/baseline.txt")
    args = p.parse_args(argv)
    root = (args.repo_root or Path(__file__).resolve().parents[3]).resolve()
    baseline = args.baseline or root / ".claude" / "skills" / "dotenv-guard" / "baseline.txt"
    print(f"== dotenv-guard: {root} ==")
    try:
        return run(root, baseline)
    except EnvError as exc:
        print(f"env error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
