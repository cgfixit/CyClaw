"""OpenTweet HTTP client: never confirms online; draft omits publish_now."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
import yaml

from opentweet import client
from opentweet.config import load_opentweet_config
from utils.errors import OpenTweetRuntimeError
from utils.logger import reset_config_cache


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_config_cache()
    client.reset_http_client_for_tests()
    yield
    client.reset_http_client_for_tests()
    reset_config_cache()


def _cfg(tmp_path: Path) -> str:
    raw = {
        "logging": {"audit_file": str(tmp_path / "audit.jsonl")},
        "opentweet": {
            "enabled": True,
            "topic_file": str(tmp_path / "topic.txt"),
            "query": {"base_url": "http://127.0.0.1:8787"},
        },
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return str(path)


def test_post_query_never_confirms_online(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENTWEET_API_KEY", "ot_test")
    cfg = load_opentweet_config(_cfg(tmp_path))
    captured: dict = {}

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        captured["url"] = url
        captured["json"] = json
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"answer": "ok", "hit_count": 1, "model_used": "local"}
        return resp

    mock_http = MagicMock()
    mock_http.post.side_effect = fake_post
    with patch("opentweet.client._get_loopback_http_client", return_value=mock_http):
        client.post_query(cfg, "hello topic")
    assert captured["json"]["user_confirmed_online"] is False
    assert "online_provider" not in captured["json"]
    assert captured["url"].endswith("/query")


def test_create_post_draft_omits_publish_and_schedule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENTWEET_API_KEY", "ot_test")
    cfg = load_opentweet_config(_cfg(tmp_path))
    captured: dict = {}

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        captured["json"] = json
        captured["headers"] = headers
        resp = MagicMock()
        resp.status_code = 201
        resp.json.return_value = {"success": True, "posts": [{"id": "abc"}]}
        return resp

    mock_http = MagicMock()
    mock_http.post.side_effect = fake_post
    with patch("opentweet.client._get_opentweet_http_client", return_value=mock_http):
        client.create_post(cfg, "body")
    assert captured["json"] == {"text": "body"}
    assert "publish_now" not in captured["json"]
    assert "scheduled_date" not in captured["json"]
    assert str(captured["headers"]["Authorization"]).startswith("Bearer ")


def test_create_post_schedule_sends_future_iso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENTWEET_API_KEY", "ot_test")
    cfg = load_opentweet_config(_cfg(tmp_path))
    captured: dict = {}

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        captured["json"] = json
        resp = MagicMock()
        resp.status_code = 201
        resp.json.return_value = {"success": True, "posts": [{"id": "abc"}]}
        return resp

    mock_http = MagicMock()
    mock_http.post.side_effect = fake_post
    iso = "2026-08-24T13:00:00-04:00"
    with patch("opentweet.client._get_opentweet_http_client", return_value=mock_http):
        client.create_post(cfg, "body", scheduled_date=iso)
    assert captured["json"]["scheduled_date"] == iso
    assert "publish_now" not in captured["json"]


def test_post_query_uses_split_connect_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Connect should have its own short ceiling so a black-holed handshake does
    not burn the entire request timeout."""
    monkeypatch.setenv("OPENTWEET_API_KEY", "ot_test")
    cfg = load_opentweet_config(_cfg(tmp_path))
    captured: dict = {}

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        captured["timeout"] = timeout
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"answer": "ok"}
        return resp

    mock_http = MagicMock()
    mock_http.post.side_effect = fake_post
    with patch("opentweet.client._get_loopback_http_client", return_value=mock_http):
        client.post_query(cfg, "hello topic")
    assert isinstance(captured["timeout"], httpx.Timeout)
    assert captured["timeout"].connect == 10.0
    assert captured["timeout"].read == float(cfg.query.timeout_sec)


@pytest.mark.parametrize("status, expected", [
    (429, True),
    (500, True),
    (502, True),
    (400, False),
    (401, False),
    (403, False),
])
def test_post_query_marks_only_transient_statuses_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int, expected: bool,
) -> None:
    """4xx client errors are not retryable; 5xx and 429 are."""
    monkeypatch.setenv("OPENTWEET_API_KEY", "ot_test")
    cfg = load_opentweet_config(_cfg(tmp_path))

    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = None
    mock_http = MagicMock()
    mock_http.post.return_value = resp
    with patch("opentweet.client._get_loopback_http_client", return_value=mock_http):
        with pytest.raises(OpenTweetRuntimeError) as exc_info:
            client.post_query(cfg, "hello topic")
    assert exc_info.value.details.get("retryable") is expected


def test_post_query_non_object_json_is_not_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed JSON body will not change on retry, so do not mark it retryable."""
    monkeypatch.setenv("OPENTWEET_API_KEY", "ot_test")
    cfg = load_opentweet_config(_cfg(tmp_path))

    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = ["not", "a", "dict"]
    mock_http = MagicMock()
    mock_http.post.return_value = resp
    with patch("opentweet.client._get_loopback_http_client", return_value=mock_http):
        with pytest.raises(OpenTweetRuntimeError) as exc_info:
            client.post_query(cfg, "hello topic")
    assert exc_info.value.details.get("retryable") is False


def _transport_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)


def _refuse(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused to secret-host", request=request)


def test_post_query_transport_error_is_audited_without_query_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dead loopback gateway raises a retryable error naming only the exception type, and audits a fingerprint."""
    monkeypatch.setenv("OPENTWEET_API_KEY", "ot_test")
    cfg = load_opentweet_config(_cfg(tmp_path))
    with patch("opentweet.client._get_loopback_http_client", return_value=_transport_client(_refuse)):
        with pytest.raises(OpenTweetRuntimeError) as exc:
            client.post_query(cfg, "private topic words")
    assert exc.value.details == {"method": "POST /query", "retryable": True}
    assert "ConnectError" in str(exc.value)
    assert "secret-host" not in str(exc.value)
    audit = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert '"opentweet_query"' in audit
    assert '"error_type": "ConnectError"' in audit
    assert "private topic words" not in audit


def test_get_me_sends_bearer_and_returns_object(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/v1/me authenticates with the resolved key and returns the JSON object."""
    monkeypatch.setenv("OPENTWEET_API_KEY", "ot_test")
    cfg = load_opentweet_config(_cfg(tmp_path))
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        seen["path"] = request.url.path
        return httpx.Response(200, json={"plan": "free"})

    with patch("opentweet.client._get_opentweet_http_client", return_value=_transport_client(handler)):
        assert client.get_me(cfg) == {"plan": "free"}
    assert seen == {"auth": "Bearer ot_test", "path": "/api/v1/me"}


@pytest.mark.parametrize(
    ("status", "body", "retryable"),
    [(401, {"error": "bad key"}, False), (503, {}, True), (200, ["not", "an", "object"], False)],
)
def test_get_me_rejections_classify_retryability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int, body: object, retryable: bool
) -> None:
    """Non-200 or non-object replies raise; only 5xx/429 are marked retryable."""
    monkeypatch.setenv("OPENTWEET_API_KEY", "ot_test")
    cfg = load_opentweet_config(_cfg(tmp_path))
    transport = _transport_client(lambda request: httpx.Response(status, json=body))
    with patch("opentweet.client._get_opentweet_http_client", return_value=transport):
        with pytest.raises(OpenTweetRuntimeError) as exc:
            client.get_me(cfg)
    assert exc.value.details["retryable"] is retryable
    assert "ot_test" not in str(exc.value)


@pytest.mark.parametrize("call", ["get_me", "create_post"])
def test_opentweet_transport_errors_never_echo_key_or_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, call: str
) -> None:
    """Transport failures toward OpenTweet surface only the exception type, retryable."""
    monkeypatch.setenv("OPENTWEET_API_KEY", "ot_test")
    cfg = load_opentweet_config(_cfg(tmp_path))
    with patch("opentweet.client._get_opentweet_http_client", return_value=_transport_client(_refuse)):
        with pytest.raises(OpenTweetRuntimeError) as exc:
            client.get_me(cfg) if call == "get_me" else client.create_post(cfg, "body")
    assert exc.value.details["retryable"] is True
    assert "ot_test" not in str(exc.value)
    assert "secret-host" not in str(exc.value)


def test_create_post_non_json_reply_is_not_retryable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A 201 whose body is not JSON is a hard failure, not a silent success."""
    monkeypatch.setenv("OPENTWEET_API_KEY", "ot_test")
    cfg = load_opentweet_config(_cfg(tmp_path))
    transport = _transport_client(lambda request: httpx.Response(201, text="<html>"))
    with patch("opentweet.client._get_opentweet_http_client", return_value=transport):
        with pytest.raises(OpenTweetRuntimeError) as exc:
            client.create_post(cfg, "body")
    assert exc.value.details["retryable"] is False
