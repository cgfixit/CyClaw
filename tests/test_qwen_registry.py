"""Qwen manifest loader — no weight download."""

from __future__ import annotations

import httpx
import pytest

from guardrails.errors import GuardrailsConfigError
from guardrails.qwen_registry import check_model_digest, load_qwen_manifest, provenance_ids_for_docs


def test_shipped_manifest_loads_non_strict() -> None:
    man = load_qwen_manifest()
    assert man["tag"] == "qwen3.8:27b-mlx"
    assert man["strict"] is False
    assert man["sha256"] == ""


def test_strict_without_digest_fails(tmp_path) -> None:
    p = tmp_path / "m.yaml"
    p.write_text("tag: qwen3.8:27b-mlx\nsha256: ''\nstrict: true\n", encoding="utf-8")
    with pytest.raises(GuardrailsConfigError, match="sha256"):
        load_qwen_manifest(p)


def test_provenance_ids_omit_raw_text() -> None:
    ids = provenance_ids_for_docs(
        [{"source": "rrf.md", "chunk_id": 0, "text": "SECRET CHUNK"}]
    )
    assert ids == ("rrf.md:0",)
    assert "SECRET" not in "".join(ids)


_FULL = "c69cc4be857d" + "0" * 52


def _client(models: object, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(status, json={"models": models})

    return httpx.Client(transport=httpx.MockTransport(handler))


def _manifest(sha: str = "") -> dict:
    return {"tag": "qwen3.8:27b-mlx", "sha256": sha, "source_url": "", "strict": False}


def _check(manifest: dict, client: httpx.Client, model: str = "qwen3.8:27b-mlx") -> dict:
    return check_model_digest(manifest, base_url="http://127.0.0.1:11434/v1", model=model, client=client)


def test_unpinned_reports_the_digest_to_pin() -> None:
    res = _check(_manifest(), _client([{"name": "qwen3.8:27b-mlx", "digest": _FULL}]))
    assert (res["status"], res["observed"], res["problems"]) == ("unpinned", _FULL, [])


@pytest.mark.parametrize("pin", [_FULL, _FULL[:12]])
def test_full_or_ollama_list_prefix_pin_matches(pin: str) -> None:
    res = _check(_manifest(pin), _client([{"name": "qwen3.8:27b-mlx", "digest": _FULL}]))
    assert (res["status"], res["problems"]) == ("match", [])


def test_other_digest_is_a_mismatch() -> None:
    res = _check(_manifest("5642e97495e1"), _client([{"name": "qwen3.8:27b-mlx", "digest": _FULL}]))
    assert res["status"] == "mismatch"
    assert "c69cc4be857d" in res["problems"][0]


def test_missing_model_and_bad_listing_are_problems_not_crashes() -> None:
    assert _check(_manifest(), _client([{"name": "other:1b", "digest": _FULL}]))["status"] == "not_installed"
    assert _check(_manifest(), _client([], status=500))["status"] == "unreachable"
    assert _check(_manifest(), _client(["not-a-dict", None]))["status"] == "not_installed"


def test_manifest_tag_must_be_the_configured_model() -> None:
    res = _check(_manifest(), _client([{"name": "qwen3.8:27b-mlx", "digest": _FULL}]), model="qwen3.8:9b")
    assert any("guardrails.model" in p for p in res["problems"])


def test_non_loopback_base_url_is_refused_before_any_request() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request may leave the box")

    res = check_model_digest(
        _manifest(), base_url="http://example.com:11434/v1", model="qwen3.8:27b-mlx",
        client=httpx.Client(transport=httpx.MockTransport(boom)),
    )
    assert res["status"] == "refused"


def test_malformed_pin_is_rejected_at_load(tmp_path) -> None:
    p = tmp_path / "m.yaml"
    p.write_text("tag: qwen3.8:27b-mlx\nsha256: 'not-hex'\n", encoding="utf-8")
    with pytest.raises(GuardrailsConfigError, match="hex"):
        load_qwen_manifest(p)
    p.write_text(f"tag: qwen3.8:27b-mlx\nsha256: 'SHA256:{_FULL.upper()}'\n", encoding="utf-8")
    assert load_qwen_manifest(p)["sha256"] == _FULL
