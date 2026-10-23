"""Optional, fail-closed yara-gate checks of retained UTF-8 consumer text."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from utils.errors import RAGError
from utils.telemetry_kill import build_telemetry_safe_env

from .results import SearchResult


class ContentGateError(RAGError):
    """A content refusal, distinct from a retriever's degradable failure."""

    def __init__(self, *, blocked: bool = False) -> None:
        super().__init__(
            "External content rejected" if blocked else "External content scan incomplete",
            code="CONTENT_GATE_BLOCKED" if blocked else "CONTENT_GATE_INCOMPLETE",
        )


def gate_texts(texts: Iterable[str], cfg: dict[str, Any]) -> None:
    """Scan private snapshots; only complete, identity-pinned clean receipts allow use.

    The caller retains and consumes these strings, never reopens their source paths.
    Each field is scanned separately so one field cannot suppress another's match.
    """
    try:
        settings = cfg.get("policy", {}).get("content_gate", {})
        if not isinstance(settings, dict):
            raise ContentGateError()
        enabled = settings.get("enabled", False)
        if enabled is False:
            return
        if enabled is not True:
            raise ContentGateError()
        executable = Path(settings["executable"])
        rules = Path(settings["rules"])
        fingerprint = settings["ruleset_sha256"]
        engine = settings["engine_version"]
        if (
            not executable.is_absolute()
            or not executable.is_file()
            or not rules.is_absolute()
            or not rules.is_dir()
            or not isinstance(fingerprint, str)
            or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None
            or not isinstance(engine, str)
            or not engine
        ):
            raise ContentGateError()
        # Bound each invocation, including returned metadata and pre-existing indexes.
        snapshots: dict[str, bytes] = {}
        total = 0
        for text in texts:
            raw = text.encode("utf-8")
            digest = hashlib.sha256(raw).hexdigest()
            if digest in snapshots:
                continue
            if len(raw) > 10 * 1024 * 1024:
                raise ContentGateError()
            if total + len(raw) > 64 * 1024 * 1024 or len(snapshots) >= 512:
                _scan_snapshots(snapshots, executable, rules, fingerprint, engine)
                snapshots = {}
                total = 0
            total += len(raw)
            snapshots[digest] = raw
        if not snapshots:
            snapshots[hashlib.sha256(b"").hexdigest()] = b""
        _scan_snapshots(snapshots, executable, rules, fingerprint, engine)
    except ContentGateError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, subprocess.SubprocessError):
        # Scanner output, source paths and matched text never enter diagnostics.
        raise ContentGateError() from None


def _scan_snapshots(
    snapshots: dict[str, bytes],
    executable: Path,
    rules: Path,
    fingerprint: str,
    engine: str,
) -> None:
    """Validate one bounded batch of scanner receipts, including process status."""
    with tempfile.TemporaryDirectory(prefix="cyclaw-content-gate-") as tmp:
        root = Path(tmp)
        inputs = root / "inputs"
        inputs.mkdir(mode=0o700)
        for index, raw in enumerate(snapshots.values()):
            (inputs / f"{index}.txt").write_bytes(raw)
        env = build_telemetry_safe_env()
        env["XDG_CACHE_HOME"] = str(root / "cache")
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            result = subprocess.run(  # noqa: S603 - operator-pinned local executable, fixed argv
                [
                    str(executable),
                    "scan",
                    str(inputs),
                    "--json",
                    "--policy",
                    "agent-ingest",
                    "--home",
                    str(root / "home"),
                    "--rules",
                    str(rules),
                ],
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=errors,
                env=env,
                timeout=30,
                check=False,
            )
            output.seek(0)
            report = output.read(4 * 1024 * 1024 + 1)
        if len(report) > 4 * 1024 * 1024:
            raise ContentGateError()
        records = [json.loads(line) for line in report.splitlines()]
        seen: set[str] = set()
        blocked = False
        for record in records:
            digest = record["sha256"]
            if (
                digest not in snapshots
                or digest in seen
                or record["ruleset_sha256"] != fingerprint
                or record["engine_version"] != engine
                or record["policy"] != "agent-ingest"
                or type(record["skipped_rule_files"]) is not int
                or record["skipped_rule_files"] != 0
                or record["incomplete_reason"] is not None
                or type(record["exit_code"]) is not int
            ):
                raise ContentGateError()
            seen.add(digest)
            if record["verdict"] == "block" and record["exit_code"] == 1:
                blocked = True
            elif not (
                record["verdict"] == "clean"
                and record["exit_code"] == 0
                and record["advisory"] is False
                and record["findings"] == []
            ):
                raise ContentGateError()
        if seen != snapshots.keys() or result.returncode != int(blocked):
            raise ContentGateError()
        if blocked:
            raise ContentGateError(blocked=True)


def gate_results(results: list[SearchResult], cfg: dict[str, Any]) -> list[SearchResult]:
    """Check returned text/metadata, including memory hits; preserve scores and order."""

    def texts() -> Iterable[str]:
        for result in results:
            yield from (result.text, result.source, result.source_sha256, result.retrieval_mode, *result.stem_tags)
        yield json.dumps([asdict(result) for result in results], ensure_ascii=False)

    gate_texts(texts(), cfg)
    return results
