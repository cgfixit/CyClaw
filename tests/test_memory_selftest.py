"""Unit tests for memory/selftest.py.

The module shipped at 0% coverage. memory.selftest.main() is the
`python -m memory.selftest` pre-flight — a self-contained end-to-end pass over
the whole memory subsystem (SQLite schema, propose/apply governance, FTS5
search, episode staging, injection/reason gates, retrieval fusion, HTML export)
using only a tempdir; no network, no embedding model. This runs it directly and
asserts it returns 0, so a regression anywhere in that chain fails here instead
of only in the ad-hoc CLI.
"""

from __future__ import annotations

import memory.selftest as selftest


class TestMemorySelftest:
    def test_main_returns_zero(self, capsys):
        rc = selftest.main()
        out = capsys.readouterr().out
        assert rc == 0, out
        assert "ALL PASS" in out
        assert "FAIL" not in out

    def test_every_named_check_reports_pass(self, capsys):
        # The selftest prints one "PASS <name>" line per check. Lock the full
        # set so a silently-dropped check (fewer lines, still rc 0) is caught.
        selftest.main()
        out = capsys.readouterr().out
        expected = {
            "schema_create", "propose", "apply", "fts_hit", "episode_stage",
            "reason_gate", "injection_refuse", "fusion", "export_html",
            "fusion_disabled_noop",
        }
        reported = {line.split("PASS", 1)[1].strip()
                    for line in out.splitlines() if "PASS" in line}
        assert expected <= reported, f"missing checks: {expected - reported}"

