"""Route-level tests for gate_ops.py — the four /ops/* endpoints.

Until now the /ops/* surface was covered only by static route introspection
(tests/test_terminal_contract.py: the routes exist and accept POST) and by
utils/ops_runner.py unit tests (argv construction). The handlers themselves —
auth dependency wiring, rate-limit-before-subprocess ordering, OpsError -> 400
mapping, sanitized 500s, audit events, and the per-subsystem ``config`` block
the console renders — had no HTTP-level coverage (gate_ops.py sat at 25%).

register_ops_routes takes gate.py's security callables by injection, so these
tests build a minimal FastAPI app and inject fakes — no gate.py import (which
would trigger full app init) and no subprocess ever launches: the runner
functions are patched at the gate_ops namespace boundary.
"""

from __future__ import annotations

import hmac
import os
import subprocess
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from gate_ops import register_ops_routes
from utils.ops_runner import OpsError, OpsOutputLimitError, OpsResult

_TEST_CFG: dict[str, Any] = {
    "sync": {"enabled": True, "direction": "pull", "max_delete": 25,
             "max_transfer": "500M", "schedule_hour": 2, "schedule_min": 30},
    "fsconnect": {"enabled": False, "allowed_roots": ["/srv/share"],
                  "writes_enabled": False, "max_file_bytes": 1024},
}

_OPS_ROUTES = ("/ops/sync", "/ops/fsconnect")
_ROUTE_BODIES = {
    "/ops/sync": {"action": "status"},
    "/ops/fsconnect": {"action": "status"},
}


def _build_app(*, rate_limited: bool = False):
    """A minimal FastAPI app with the ops routes registered and fakes injected."""
    audit_events: list[dict[str, Any]] = []

    async def audit(event: dict[str, Any]) -> None:
        audit_events.append(event)

    async def enforce_rate_limit(request: Request) -> None:
        if rate_limited:
            raise HTTPException(
                status_code=429, detail={"error": "rate limit", "code": "RATE_LIMIT"}
            )

    def sanitize_error(exc: Exception) -> str:
        return "sanitized"

    async def require_api_key(request: Request) -> None:
        # Mirrors gate.py's fail-closed contract: unset key rejects everything.
        key = os.environ.get("CYCLAW_API_KEY", "")
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if not key or not hmac.compare_digest(token, key):
            raise HTTPException(
                status_code=401, detail={"error": "unauthorized", "code": "UNAUTHORIZED"}
            )

    app = FastAPI()
    register_ops_routes(
        app, _TEST_CFG, audit, enforce_rate_limit, sanitize_error, require_api_key
    )
    return TestClient(app, raise_server_exceptions=False), audit_events


def _result(subsystem: str, action: str) -> OpsResult:
    return OpsResult(subsystem, action, 0, True, "ok", "some stdout", "")


class TestOpsAuth:
    """Every /ops/* route is API-key gated; an unset server key fails closed."""

    @pytest.mark.parametrize("path", _OPS_ROUTES)
    def test_unset_server_key_fails_closed(self, monkeypatch, path):
        monkeypatch.delenv("CYCLAW_API_KEY", raising=False)
        client, _ = _build_app()
        resp = client.post(
            path, json=_ROUTE_BODIES[path],
            headers={"Authorization": "Bearer anything"},
        )
        assert resp.status_code == 401

    @pytest.mark.parametrize("path", _OPS_ROUTES)
    def test_wrong_key_rejected(self, monkeypatch, path):
        monkeypatch.setenv("CYCLAW_API_KEY", "test-key-123")
        client, _ = _build_app()
        resp = client.post(
            path, json=_ROUTE_BODIES[path],
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 401


class TestOpsFailedAuthDoesNotBypassRateLimit:
    """Each /ops/* route's dependencies=[...] list now runs the rate limiter
    BEFORE require_api_key (previously the limiter ran only inside the handler
    body, after auth had already accepted or rejected). A wrong/missing API key
    used to always hit 401 first, so unlimited key guesses against /ops/* were
    never throttled. With an exhausted budget the caller now gets 429
    regardless of whether the key presented is right, wrong, or missing."""

    @pytest.mark.parametrize("path", _OPS_ROUTES)
    def test_429_not_401_when_budget_spent_with_wrong_key(self, monkeypatch, path):
        monkeypatch.setenv("CYCLAW_API_KEY", "test-key-123")
        client, _ = _build_app(rate_limited=True)
        resp = client.post(
            path, json=_ROUTE_BODIES[path],
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 429
        assert resp.json()["detail"]["code"] == "RATE_LIMIT"

    @pytest.mark.parametrize("path", _OPS_ROUTES)
    def test_429_not_401_when_budget_spent_with_missing_key(self, monkeypatch, path):
        monkeypatch.setenv("CYCLAW_API_KEY", "test-key-123")
        client, _ = _build_app(rate_limited=True)
        resp = client.post(path, json=_ROUTE_BODIES[path])
        assert resp.status_code == 429
        assert resp.json()["detail"]["code"] == "RATE_LIMIT"


class TestOpsSync:
    def test_unknown_action_rejected_at_schema_boundary(self, monkeypatch):
        monkeypatch.setenv("CYCLAW_API_KEY", "test-key-123")
        client, _ = _build_app()
        with patch("gate_ops.run_sync_op") as runner:
            resp = client.post(
                "/ops/sync", json={"action": "nuke"},
                headers={"Authorization": "Bearer test-key-123"},
            )
        assert resp.status_code == 422
        runner.assert_not_called()

    def test_status_success_payload_config_and_audit(self, monkeypatch):
        monkeypatch.setenv("CYCLAW_API_KEY", "test-key-123")
        client, audit_events = _build_app()
        with patch("gate_ops.run_sync_op", return_value=_result("sync", "status")) as runner:
            resp = client.post(
                "/ops/sync", json={"action": "status"},
                headers={"Authorization": "Bearer test-key-123"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["label"] == "ok"
        assert data["exit_code"] == 0
        # The console renders the shipped sync gates from this block.
        assert data["config"] == {
            "enabled": True, "direction": "pull", "max_delete": 25,
            "max_transfer": "500M", "schedule": "02:30",
        }
        runner.assert_called_once_with("status", dry_run=False)
        assert [e["event"] for e in audit_events] == ["ops_sync_executed"]
        assert audit_events[0]["action"] == "status"

    def test_dry_run_forwarded_only_for_sync_action(self, monkeypatch):
        monkeypatch.setenv("CYCLAW_API_KEY", "test-key-123")
        client, _ = _build_app()
        with patch("gate_ops.run_sync_op", return_value=_result("sync", "sync")) as runner:
            resp = client.post(
                "/ops/sync", json={"action": "sync", "dry_run": True},
                headers={"Authorization": "Bearer test-key-123"},
            )
        assert resp.status_code == 200
        runner.assert_called_once_with("sync", dry_run=True)

    def test_ops_error_maps_to_400(self, monkeypatch):
        monkeypatch.setenv("CYCLAW_API_KEY", "test-key-123")
        client, audit_events = _build_app()
        with patch("gate_ops.run_sync_op", side_effect=OpsError("bad action")):
            resp = client.post(
                "/ops/sync", json={"action": "status"},
                headers={"Authorization": "Bearer test-key-123"},
            )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "OPS_BAD_ACTION"
        assert [e["event"] for e in audit_events] == ["ops_sync_rejected"]

    def test_unexpected_error_is_sanitized_500(self, monkeypatch):
        monkeypatch.setenv("CYCLAW_API_KEY", "test-key-123")
        client, audit_events = _build_app()
        with patch("gate_ops.run_sync_op", side_effect=RuntimeError("/home/operator/secret-path")):
            resp = client.post(
                "/ops/sync", json={"action": "status"},
                headers={"Authorization": "Bearer test-key-123"},
            )
        assert resp.status_code == 500
        detail = resp.json()["detail"]
        assert detail["code"] == "OPS_ERROR"
        assert detail["error"] == "sanitized"
        assert "secret-path" not in resp.text
        assert [e["event"] for e in audit_events] == ["ops_sync_error"]

    def test_timeout_is_a_typed_504(self, monkeypatch):
        """A budget-killed CLI is a 504 OPS_TIMEOUT (matching the harness
        console's AGENTIC_TIMEOUT for the identical failure), never a generic
        500 -- and the argv inside TimeoutExpired's repr is never echoed."""
        monkeypatch.setenv("CYCLAW_API_KEY", "test-key-123")
        client, audit_events = _build_app()
        boom = subprocess.TimeoutExpired(cmd=["python", "-m", "sync.cli", "sync"], timeout=3660)
        with patch("gate_ops.run_sync_op", side_effect=boom):
            resp = client.post(
                "/ops/sync", json={"action": "sync"},
                headers={"Authorization": "Bearer test-key-123"},
            )
        assert resp.status_code == 504
        detail = resp.json()["detail"]
        assert detail["code"] == "OPS_TIMEOUT"
        assert detail["timeout_sec"] == 3660
        assert "sync.cli" not in resp.text
        assert [e["event"] for e in audit_events] == ["ops_sync_timeout"]


class TestOpsFsConnect:
    def test_read_forwards_scoped_args(self, monkeypatch):
        monkeypatch.setenv("CYCLAW_API_KEY", "test-key-123")
        client, audit_events = _build_app()
        with patch("gate_ops.run_fsconnect_op", return_value=_result("fsconnect", "read")) as runner:
            resp = client.post(
                "/ops/fsconnect",
                json={"action": "read", "root": "/srv/share", "path": "notes/a.md"},
                headers={"Authorization": "Bearer test-key-123"},
            )
        assert resp.status_code == 200
        assert resp.json()["config"] == {
            "enabled": False, "allowed_roots": ["/srv/share"],
            "writes_enabled": False, "max_file_bytes": 1024,
        }
        runner.assert_called_once_with(
            "read", root="/srv/share", path="notes/a.md",
            pattern=None, regex=False, recursive=True,
        )
        assert [e["event"] for e in audit_events] == ["ops_fsconnect_executed"]

    def test_regex_grep_rejected_at_schema_boundary(self, monkeypatch):
        monkeypatch.setenv("CYCLAW_API_KEY", "test-key-123")
        client, _ = _build_app()
        with patch("gate_ops.run_fsconnect_op") as runner:
            resp = client.post(
                "/ops/fsconnect",
                json={"action": "grep", "pattern": "(a+)+$", "regex": True},
                headers={"Authorization": "Bearer test-key-123"},
            )
        assert resp.status_code == 422
        runner.assert_not_called()


class TestOpsErrorMapping:
    """The OpsError -> 400 / unexpected -> sanitized 500 contract is uniform
    for the fsconnect route (the sync route's
    mapping is covered explicitly in TestOpsSync above)."""

    _CASES = (
        ("/ops/fsconnect", {"action": "status"}, "gate_ops.run_fsconnect_op",
         "ops_fsconnect_rejected", "ops_fsconnect_error"),
    )

    @pytest.mark.parametrize(
        "path,body,patch_target,rejected_event,_error_event", _CASES
    )
    def test_ops_error_maps_to_400(
        self, monkeypatch, path, body, patch_target, rejected_event, _error_event
    ):
        monkeypatch.setenv("CYCLAW_API_KEY", "test-key-123")
        client, audit_events = _build_app()
        with patch(patch_target, side_effect=OpsError("bad action")):
            resp = client.post(
                path, json=body, headers={"Authorization": "Bearer test-key-123"}
            )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "OPS_BAD_ACTION"
        assert [e["event"] for e in audit_events] == [rejected_event]

    @pytest.mark.parametrize(
        "path,body,patch_target,_rejected_event,error_event", _CASES
    )
    def test_unexpected_error_is_sanitized_500(
        self, monkeypatch, path, body, patch_target, _rejected_event, error_event
    ):
        monkeypatch.setenv("CYCLAW_API_KEY", "test-key-123")
        client, audit_events = _build_app()
        with patch(patch_target, side_effect=RuntimeError("/home/operator/secret-path")):
            resp = client.post(
                path, json=body, headers={"Authorization": "Bearer test-key-123"}
            )
        assert resp.status_code == 500
        detail = resp.json()["detail"]
        assert detail["code"] == "OPS_ERROR"
        assert detail["error"] == "sanitized"
        assert "secret-path" not in resp.text
        assert [e["event"] for e in audit_events] == [error_event]


class TestOpsRateLimit:
    """The shared rate limiter runs before any subprocess launch."""

    @pytest.mark.parametrize("path", _OPS_ROUTES)
    def test_rate_limited_429_before_subprocess(self, monkeypatch, path):
        monkeypatch.setenv("CYCLAW_API_KEY", "test-key-123")
        client, _ = _build_app(rate_limited=True)
        with (
            patch("gate_ops.run_sync_op") as sync_runner,
            patch("gate_ops.run_fsconnect_op") as fs_runner,
        ):
            resp = client.post(
                path, json=_ROUTE_BODIES[path],
                headers={"Authorization": "Bearer test-key-123"},
            )
        assert resp.status_code == 429
        assert resp.json()["detail"]["code"] == "RATE_LIMIT"
        for runner in (sync_runner, fs_runner):
            runner.assert_not_called()


def test_output_limit_is_a_distinct_resource_error(monkeypatch):
    monkeypatch.setenv("CYCLAW_API_KEY", "test-key-123")
    client, events = _build_app()
    with patch("gate_ops.run_fsconnect_op", side_effect=OpsOutputLimitError("output limit")):
        response = client.post("/ops/fsconnect", json={"action": "list"},
                               headers={"Authorization": "Bearer test-key-123"})
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "OPS_OUTPUT_LIMIT"
    assert events[-1]["event"] == "ops_fsconnect_output_limit"


class TestRemovedOpsRoutes:
    """/ops/agentic and /ops/sqlconnect were removed with their subsystems."""

    @pytest.mark.parametrize("path", ["/ops/agentic", "/ops/sqlconnect"])
    def test_removed_route_is_not_registered(self, monkeypatch, path):
        monkeypatch.setenv("CYCLAW_API_KEY", "test-key-123")
        client, audit_events = _build_app()
        resp = client.post(
            path, json={"action": "status"},
            headers={"Authorization": "Bearer test-key-123"},
        )
        assert resp.status_code == 404
        assert audit_events == []
