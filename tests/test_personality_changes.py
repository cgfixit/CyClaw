"""Unit tests for v1.3 changes in utils/personality.py"""

import tempfile
from pathlib import Path
from unittest.mock import patch

from utils.personality import PersonalityManager


def test_personality_init_and_version():
    """Test basic init, version tracking, and soul load."""
    # ignore_cleanup_errors: PersonalityManager keeps its sqlite connection open
    # for its lifetime, and on Windows an open file handle blocks directory
    # removal (WinError 32). The DB assertions all run before teardown; only the
    # cleanup needs to tolerate the still-open handle. (POSIX unlinks open files
    # fine, so this is a no-op there.)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        soul_path = Path(tmp) / "soul.md"
        db_path = Path(tmp) / "test_soul.db"

        initial_soul = "# Test Soul\nYou are a test AI."
        soul_path.write_text(initial_soul)

        cfg = {
            "personality": {
                "soul_path": str(soul_path),
                "db_path": str(db_path),
                "interaction_ttl_days": 90,
                "enabled": True
            }
        }

        with patch("utils.personality.audit_log"):
            pm = PersonalityManager(cfg)
        assert pm.get_version() >= 1, "Version should be at least 1 after init"
        assert "Test Soul" in pm.get_system_prompt_additive()


def test_propose_apply_evolution():
    """Test propose and apply with atomic write (v1.3)."""
    # ignore_cleanup_errors: PersonalityManager keeps its sqlite connection open
    # for its lifetime, and on Windows an open file handle blocks directory
    # removal (WinError 32). The DB assertions all run before teardown; only the
    # cleanup needs to tolerate the still-open handle. (POSIX unlinks open files
    # fine, so this is a no-op there.)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        soul_path = Path(tmp) / "soul.md"
        db_path = Path(tmp) / "test_soul.db"

        initial = "# Initial\nBe helpful."
        soul_path.write_text(initial)

        cfg = {"personality": {"soul_path": str(soul_path), "db_path": str(db_path), "interaction_ttl_days": 30}}

        with patch("utils.personality.audit_log"):
            pm = PersonalityManager(cfg)
        v1 = pm.get_version()

        new_soul = "# Evolved\nBe brutally honest."
        proposal = pm.propose_evolution(new_soul, "test reason")
        assert "proposed" in proposal["status"]
        assert proposal["current_sha"] != proposal["proposed_sha"]

        with patch("utils.personality.audit_log"):
            pm.apply_evolution(new_soul, "test reason")
        v2 = pm.get_version()
        assert v2 > v1, "Version should increment"
        assert "brutally honest" in pm.get_system_prompt_additive()

        assert not (soul_path.with_suffix(".tmp")).exists()


def test_drift_detection():
    """Test SHA-256 drift detection and auto-recovery (v1.3)."""
    # ignore_cleanup_errors: PersonalityManager keeps its sqlite connection open
    # for its lifetime, and on Windows an open file handle blocks directory
    # removal (WinError 32). The DB assertions all run before teardown; only the
    # cleanup needs to tolerate the still-open handle. (POSIX unlinks open files
    # fine, so this is a no-op there.)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        soul_path = Path(tmp) / "soul.md"
        db_path = Path(tmp) / "test_soul.db"

        initial = "# Drift Test\nOriginal."
        soul_path.write_text(initial)

        cfg = {"personality": {"soul_path": str(soul_path), "db_path": str(db_path), "interaction_ttl_days": 30}}

        with patch("utils.personality.audit_log"):
            pm = PersonalityManager(cfg)
        v1 = pm.get_version()

        tampered = "# Drift Test\nTAMPERED CONTENT!"
        soul_path.write_text(tampered)

        with patch("utils.personality.audit_log"):
            pm2 = PersonalityManager(cfg)
        v2 = pm2.get_version()
        assert v2 > v1, "Drift should trigger new version"
        assert "TAMPERED" in pm2.get_system_prompt_additive()


def test_ttl_maintenance():
    """Test interaction TTL prune on init (v1.3)."""
    # ignore_cleanup_errors: PersonalityManager keeps its sqlite connection open
    # for its lifetime, and on Windows an open file handle blocks directory
    # removal (WinError 32). The DB assertions all run before teardown; only the
    # cleanup needs to tolerate the still-open handle. (POSIX unlinks open files
    # fine, so this is a no-op there.)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        soul_path = Path(tmp) / "soul.md"
        db_path = Path(tmp) / "test_soul.db"

        soul_path.write_text("# TTL Test")

        cfg = {"personality": {"soul_path": str(soul_path), "db_path": str(db_path), "interaction_ttl_days": 1}}

        with patch("utils.personality.audit_log"):
            pm = PersonalityManager(cfg)

        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO interactions (timestamp, query_hash, outcome) VALUES (?, ?, ?)",
                     ("2020-01-01T00:00:00+00:00", "oldhash", "test"))
        conn.commit()
        conn.close()

        with patch("utils.personality.audit_log"):
            pm2 = PersonalityManager(cfg)
        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]
        conn.close()
        assert count == 0, "Old interaction should be pruned"
