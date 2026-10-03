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
    @classmethod
    def setUpClass(cls) -> None:
        if GIT is None:
            raise RuntimeError("Git is required for synthetic repository fixtures")
        cls.temporary = tempfile.TemporaryDirectory(prefix="doc-sync-contract-")
        cls.base = Path(cls.temporary.name) / "base"
        cls.base.mkdir()
        paths = cls.git(ROOT, "ls-files", "-z").stdout.split("\0")
        for relative in filter(None, paths):
            source = ROOT / relative
            destination = cls.base / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        cls.git(cls.base, "init", "-q")
        cls.git(cls.base, "add", ".")
        baseline = cls.run_checker(cls.base)
        if baseline.returncode:
            cls.temporary.cleanup()
            raise AssertionError(baseline.stdout + baseline.stderr)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def setUp(self) -> None:
        self.root = Path(self.temporary.name) / "case"
        shutil.copytree(self.base, self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    @staticmethod
    def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 - resolved Git, fixture arguments, no shell
            [GIT, "-C", str(root), *args], check=True, capture_output=True, text=True,
        )

    @staticmethod
    def run_checker(root: Path, wrapper: bool = False) -> subprocess.CompletedProcess[str]:
        checker = ROOT / ".codex/skills/doc-sync/doc_sync.py" if wrapper else CHECKER
        return subprocess.run(  # noqa: S603 - current interpreter and repository CLI
            [sys.executable, str(checker), "--repo-root", str(root), "--json"],
            capture_output=True, text=True, check=False,
        )

    def replace(self, relative: str, old: str, new: str) -> None:
        path = self.root / relative
        source = path.read_text(encoding="utf-8")
        self.assertIn(old, source)
        path.write_text(source.replace(old, new), encoding="utf-8")

    def assert_drift(self, check: str, wrapper: bool = False) -> None:
        result = self.run_checker(self.root, wrapper)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(f"DRIFT [{check}]", result.stdout)
        self.assertIn(f'"check": "{check}"', result.stdout)

    def assert_clean(self, wrapper: bool = False) -> None:
        result = self.run_checker(self.root, wrapper)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_stale_timeout_cannot_borrow_unrelated_correct_number(self) -> None:
        self.replace("CLAUDE.md", "| `780` | `api.graph_timeout_sec` |",
                     "| `779` | `api.graph_timeout_sec` |")
        with (self.root / "CLAUDE.md").open("a", encoding="utf-8") as handle:
            handle.write("\nUnrelated example identifier: 780.\n")
        self.assert_drift("D3")
        self.assert_drift("D3", wrapper=True)

    def test_each_numeric_row_is_independent(self) -> None:
        path = self.root / "CLAUDE.md"
        original = path.read_text(encoding="utf-8")
        for value, key in (("127.0.0.1:8787", "api.host`/`api.port"),
                           ("0.028", "retrieval.min_score"), ("60", "retrieval.rrf_k"),
                           ("8000", "personality.soul_max_chars")):
            with self.subTest(key=key):
                path.write_text(original.replace(f"| `{value}` | `{key}` |",
                                                 f"| `123456` | `{key}` |")
                                + f"\nUnrelated example: {value}.\n", encoding="utf-8")
                self.assert_drift("D3")

    def test_missing_malformed_and_duplicate_numeric_values(self) -> None:
        path = self.root / "CLAUDE.md"
        original = path.read_text(encoding="utf-8")
        for value in ("", "7800", "NaN", "-780", "0"):
            with self.subTest(value=value):
                path.write_text(original.replace("| `780` | `api.graph_timeout_sec` |",
                                                 f"| `{value}` | `api.graph_timeout_sec` |"), encoding="utf-8")
                self.assert_drift("D3")
        path.write_text(original + "\n| `779` | `api.graph_timeout_sec` | stale duplicate |\n", encoding="utf-8")
        self.assert_drift("D3")

    def test_missing_value_cannot_borrow_number_from_notes(self) -> None:
        self.replace("CLAUDE.md", "| `780` | `api.graph_timeout_sec` |",
                     "|  | `api.graph_timeout_sec` | notes contain 780; ")
        self.assert_drift("D3")

    def test_assignment_in_table_note_is_checked_independently(self) -> None:
        self.replace("CLAUDE.md", "| `780` | `api.graph_timeout_sec` | must exceed",
                     "| `780` | `api.graph_timeout_sec` | `api.graph_timeout_sec=779`; must exceed")
        self.assert_drift("D3")

    def test_malformed_table_delimiter_is_drift(self) -> None:
        self.replace("README.md", "| Path | Git status | Contents and behavior |\n|---|---|---|",
                     "| Path | Git status | Contents and behavior |\n|not|a|delimiter|")
        self.assert_drift("D12")

    def test_optional_and_equivalent_numeric_citations(self) -> None:
        self.replace("CLAUDE.md", "| `780` | `api.graph_timeout_sec` |",
                     "| `780.0` | `api.graph_timeout_sec` |")
        self.assert_clean(wrapper=True)
        path = self.root / "CLAUDE.md"
        path.write_text("\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
                                  if not (line.startswith("|") and "`api.graph_timeout_sec`" in line)),
                        encoding="utf-8")
        self.assert_clean()
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\napi.graph_timeout_sec = 779\n")
        self.assert_drift("D3")

    def test_tracked_soul_cannot_be_declared_ignored(self) -> None:
        self.replace("README.md", "| `data/personality/soul.md` | tracked |",
                     "| `data/personality/soul.md` | ignored |")
        self.assert_drift("D12")

    def test_record_row_removal_is_drift(self) -> None:
        path = self.root / "README.md"
        path.write_text("\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
                                  if not line.startswith("| `data/personality/soul.md`")), encoding="utf-8")
        self.assert_drift("D12")

    def test_tracked_wins_over_ignore_rule(self) -> None:
        with (self.root / ".gitignore").open("a", encoding="utf-8") as handle:
            handle.write("\ndata/personality/soul.md\n")
        self.assert_clean()

    def test_forced_tracked_ignored_descendant_is_drift(self) -> None:
        path = self.root / "index/forced.txt"
        path.parent.mkdir(exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
        self.git(self.root, "add", "-f", "index/forced.txt")
        self.assert_drift("D12")

    def test_negated_ignore_rule_is_drift(self) -> None:
        with (self.root / ".gitignore").open("a", encoding="utf-8") as handle:
            handle.write("\n!data/personality/soul.md.bak\n")
        self.assert_drift("D12")

    def test_secret_store_operation_and_flag(self) -> None:
        path = self.root / "README.md"
        original = path.read_text(encoding="utf-8")
        for old, new in (("| Keychain |", "| dotenv |"),
                         ("| Credential Manager |", "| dotenv |"),
                         ("Migrate existing plaintext secrets", "Generate missing key"),
                         ("| `-WriteEnvFile` |", "| none |")):
            with self.subTest(old=old):
                path.write_text(original.replace(old, new), encoding="utf-8")
                self.assert_drift("D13")

    def test_missing_secret_contract_is_drift(self) -> None:
        self.replace("README.md", "**Secret persistence.**", "**Installer details.**")
        self.assert_drift("D13")

    def test_comment_cannot_supply_windows_call(self) -> None:
        self.replace("powershell/Install-CyClaw.ps1", "\nSync-CyclawPlaintextToCredentialManager ",
                     "\n# Sync-CyclawPlaintextToCredentialManager ")
        self.assert_drift("D13")

    def test_changed_macos_default_is_drift(self) -> None:
        self.replace("macos/setup-cyclaw-keys.sh", "\nDO_KEYCHAIN=1\n", "\nDO_KEYCHAIN=0\n")
        self.assert_drift("D13")

    def test_missing_git_is_environment_error(self) -> None:
        shutil.rmtree(self.root / ".git")
        result = self.run_checker(self.root)
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
