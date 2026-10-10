"""Optional Qwen/Ollama tag manifest. Strict mode default-off. No weight fetch.

STATUS: ``python -m guardrails.cli model`` is the one caller of
``load_qwen_manifest`` and ``check_model_digest`` (operator-run, never on the
request path, so no graph or gate behavior depends on it). ``provenance_ids_for_docs``
still has no caller outside tests: it produces ids for
``GuardrailDecision.provenance_ids``, a field on a ``guardrails/boundary.py``
dataclass that nothing constructs. Kept alongside that module (owner decision);
see its STATUS note.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx
import yaml

from guardrails.errors import GuardrailsConfigError
from utils.endpoint_trust import EndpointTrustError, assert_local_destination

DEFAULT_PATH = Path(__file__).resolve().parent / "qwen_manifest.yaml"

# `ollama list` shows a 12-hex prefix of the sha256 digest; /api/tags returns all 64.
# A pin may be either, so a pasted `ollama list` ID works without a lookup.
_DIGEST_RE = re.compile(r"[0-9a-f]{12,64}")


def load_qwen_manifest(path: Path | None = None, *, strict: bool | None = None) -> dict[str, Any]:
    target = path or DEFAULT_PATH
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise GuardrailsConfigError(f"qwen manifest unreadable: {exc}") from exc
    if not isinstance(raw, dict):
        raise GuardrailsConfigError("qwen manifest must be a mapping")
    tag = str(raw.get("tag") or "").strip()
    if not tag:
        raise GuardrailsConfigError("qwen manifest missing tag")
    digest = str(raw.get("sha256") or "").strip().lower()
    if digest.startswith("sha256:"):
        digest = digest[len("sha256:"):]
    if digest and not _DIGEST_RE.fullmatch(digest):
        raise GuardrailsConfigError("qwen manifest sha256 must be 12-64 hex characters")
    enforce = raw.get("strict", False) if strict is None else strict
    if enforce and not digest:
        raise GuardrailsConfigError("strict qwen manifest requires sha256")
    return {
        "tag": tag,
        "sha256": digest,
        "source_url": str(raw.get("source_url") or ""),
        "strict": bool(enforce),
    }


def check_model_digest(
    manifest: dict[str, Any],
    *,
    base_url: str,
    model: str,
    timeout: float = 5.0,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Compare the pinned digest with what the local Ollama reports for the model.

    Read-only: one loopback GET of ``/api/tags``, no weight fetch, no write.
    Returns ``{"status", "problems", "observed", "expected"}``. ``problems`` is
    empty only when the model is installed, the manifest tag is the configured
    model, and either no digest is pinned (``status="unpinned"``, ``observed``
    is what to pin) or the pin matches (``status="match"``).
    """
    tag = manifest["tag"]
    expected = manifest["sha256"]
    out: dict[str, Any] = {"status": "", "problems": [], "observed": "", "expected": expected}
    if tag != model:
        out["problems"].append(f"manifest tag {tag!r} is not guardrails.model {model!r}")
    try:
        assert_local_destination(base_url)
    except EndpointTrustError as exc:
        out["status"] = "refused"
        out["problems"].append(str(exc))
        return out
    url = base_url.rstrip("/").removesuffix("/v1") + "/api/tags"
    try:
        # trust_env=False: a proxy env var must never intercept a loopback probe.
        if client is None:
            with httpx.Client(timeout=timeout, trust_env=False) as one_shot:
                resp = one_shot.get(url)
        else:
            resp = client.get(url)
        resp.raise_for_status()
        models = resp.json().get("models", [])
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        out["status"] = "unreachable"
        out["problems"].append(f"could not read the Ollama model list: {type(exc).__name__}")
        return out
    want = tag if ":" in tag else f"{tag}:latest"
    found = next((m for m in models if isinstance(m, dict) and m.get("name") == want), None)
    if found is None:
        out["status"] = "not_installed"
        out["problems"].append(f"{want} is not installed in Ollama")
        return out
    observed = str(found.get("digest") or "").lower().removeprefix("sha256:")
    out["observed"] = observed
    if not expected:
        out["status"] = "unpinned"
    elif observed.startswith(expected):
        out["status"] = "match"
    else:
        out["status"] = "mismatch"
        out["problems"].append(f"installed digest {observed[:12]} does not match pinned {expected[:12]}")
    return out


def provenance_ids_for_docs(docs: list[dict[str, Any]]) -> tuple[str, ...]:
    """Untrusted retrieval ids for GuardrailDecision.provenance_ids (no raw text)."""
    out: list[str] = []
    for doc in docs:
        source = str(doc.get("source") or "unknown")
        chunk = doc.get("chunk_id", "")
        out.append(f"{source}:{chunk}")
    return tuple(out)
