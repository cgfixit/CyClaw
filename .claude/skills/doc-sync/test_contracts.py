#!/usr/bin/env python3
"""Focused regressions through the public doc-sync CLI."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CHECKER = ROOT / ".claude/skills/doc-sync/doc_sync.py"
GIT = shutil.which("git")


class ContractTests(unittest.TestCase):
    def test_stale_timeout_cannot_borrow_unrelated_correct_number(self) -> None:
        self.assertIsNotNone(GIT, "Git is required for the synthetic repository fixture")
        with tempfile.TemporaryDirectory(prefix="doc-sync-contract-") as temporary:
            root = Path(temporary)
            paths = subprocess.run(  # noqa: S603 - resolved Git, owned fixture paths, no shell
                [GIT, "-C", str(ROOT), "ls-files", "-z"],
                check=True, capture_output=True, text=True,
            ).stdout.split("\0")
            for relative in filter(None, paths):
                source = ROOT / relative
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            subprocess.run([GIT, "init", "-q", str(root)], check=True)  # noqa: S603 - owned fixture
            subprocess.run([GIT, "-C", str(root), "add", "."], check=True)  # noqa: S603 - owned fixture

            def run_checker() -> subprocess.CompletedProcess[str]:
                return subprocess.run(  # noqa: S603 - current interpreter and maintained CLI, no shell
                    [sys.executable, str(CHECKER), "--repo-root", str(root)],
                    capture_output=True, text=True, check=False,
                )

            baseline = run_checker()
            self.assertEqual(baseline.returncode, 0, baseline.stdout + baseline.stderr)
            claude_path = root / "CLAUDE.md"
            claude = claude_path.read_text(encoding="utf-8")
            original = "| `780` | `api.graph_timeout_sec` |"
            self.assertEqual(claude.count(original), 1)
            claude_path.write_text(
                claude.replace(original, "| `779` | `api.graph_timeout_sec` |")
                + "\nUnrelated example identifier: 780.\n",
                encoding="utf-8",
            )
            result = run_checker()
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("DRIFT [D3]", result.stdout)


if __name__ == "__main__":
    unittest.main()
