"""Local cross-encoder relevance scores for the vault-hit gate (Phase 3 of #1456).

A bi-encoder cosine measures topic, not answerability. Measured on this
corpus, "What is the plot of the horror film The Medium?" sits closer to the
McLuhan chunk (cosine 0.46) than several real paraphrases sit to theirs, so no
min_semantic_score separates look-alikes from answerable questions. A
cross-encoder reads the question and one chunk together and returns a single
relevance logit. graph.py's route_by_score_node uses the best logit in the
context window as a veto on the cosine gate: it can turn a vault hit into a
miss, never a miss into a hit.

The reranker is optional and fail-soft. With models.reranker.enabled false,
rerank_scores returns None and the cosine gate decides alone. When the model
cannot load or score, it raises RerankerError, which graph.retrieve_node
catches: the query still runs on the cosine gate and the audit record says
the reranker was degraded.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from utils.errors import RerankerError

from .embeddings import (
    _MODEL_LOAD_MAX_ATTEMPTS,
    _MODEL_LOAD_RETRY_DELAY_SEC,
    EMBED_DEVICE,
    _index_or_bm25_present,
    _model_offline_eligible,
    resolve_cache_dir,
)

if TYPE_CHECKING:
    # Type-only, like retrieval/embeddings.py: importing this module must not
    # drag in sentence-transformers (and torch) until a query needs a score.
    from sentence_transformers import CrossEncoder

log = logging.getLogger("cyclaw.retrieval.rerank")

# After a failed load, answer "unavailable" straight away for this long instead
# of retrying on every query. lru_cache does not memoize a raised exception, so
# without this an offline machine that never fetched the model would pay the
# full retry loop (_MODEL_LOAD_MAX_ATTEMPTS, with sleeps) on each query. No
# config knob: like the embedder's retry constants, this only shapes a load.
_RETRY_AFTER_SEC = 300.0
_failed_at: dict[tuple[str, str | None, str, bool, str], float] = {}

RerankSettings = tuple[str, str | None, str, bool]


def reranker_settings(cfg: dict[str, Any], config_path: str) -> RerankSettings | None:
    """Return (model, revision, cache_dir, offline_after_index), or None when the reranker is off.

    Only the literal boolean ``models.reranker.enabled: true`` turns it on, so a
    quoted "false" in a hand-edited config cannot enable a model download. The
    model shares models.embeddings' cache_dir and offline_after_index: one
    Hugging Face cache and one offline switch for both local models.
    """
    models = cfg.get("models") or {}
    reranker = models.get("reranker") or {}
    if reranker.get("enabled") is not True:
        return None
    model = reranker.get("model")
    if not isinstance(model, str) or not model:
        return None
    revision = reranker.get("revision")
    embeddings = models.get("embeddings") or {}
    cache_dir = resolve_cache_dir(config_path, embeddings.get("cache_dir"))
    return (
        model,
        revision if isinstance(revision, str) and revision else None,
        cache_dir,
        embeddings.get("offline_after_index") is True,
    )


@lru_cache(maxsize=1)
def _load_cross_encoder(
    model: str, revision: str | None, cache_dir: str, offline_after_index: bool, config_path: str
) -> CrossEncoder:
    """Load the cross-encoder on CPU, from the local cache when it is already there.

    Offline eligibility mirrors retrieval/embeddings.py's _load_model: the
    pinned snapshot already on disk, or offline_after_index with a built
    index. The second case can refuse a model that was never fetched, since
    building an index fetches only the embedder. That is the operator's
    explicit no-fetch choice, so the load fails, the gate falls back to the
    cosine rule, and the audit record says so.

    Unlike _load_model, this never sets HF_HUB_OFFLINE: the embedder has
    always loaded first in this process (hybrid_search runs before any
    rerank), and ``local_files_only`` is what enforces offline loading here.

    ``activation_fn`` is pinned to identity, so scores are raw logits whatever
    a future sentence-transformers default becomes: retrieval.min_rerank_score
    is a threshold on that scale.
    """
    eligible = _model_offline_eligible(model, cache_dir, revision) or (
        offline_after_index and _index_or_bm25_present(config_path)
    )

    from sentence_transformers import CrossEncoder
    from torch import nn

    for attempt in range(_MODEL_LOAD_MAX_ATTEMPTS):
        try:
            encoder: CrossEncoder = CrossEncoder(
                model,
                revision=revision,
                cache_folder=cache_dir or None,
                local_files_only=eligible,
                device=EMBED_DEVICE,
                activation_fn=nn.Identity(),
            )
            return encoder
        except (OSError, RuntimeError):
            if eligible or attempt == _MODEL_LOAD_MAX_ATTEMPTS - 1:
                # A local-only load has no transient network failure to wait out.
                raise
            time.sleep(_MODEL_LOAD_RETRY_DELAY_SEC)
    # Unreachable: the final attempt either returns or re-raises.
    raise RerankerError("cross-encoder load loop exited without return/raise", details={"model": model})  # pragma: no cover


def rerank_scores(query: str, texts: Sequence[str], cfg: dict[str, Any], config_path: str) -> list[float] | None:
    """Return one relevance logit per text for ``query``, or None when the reranker is off.

    Raises RerankerError when it is on but cannot load or score. The caller
    decides what that means; graph.retrieve_node falls back to the cosine gate.
    """
    settings = reranker_settings(cfg, config_path)
    if settings is None or not texts:
        return None
    key = (*settings, config_path)
    failed = _failed_at.get(key)
    if failed is not None and time.monotonic() - failed < _RETRY_AFTER_SEC:
        raise RerankerError("cross-encoder unavailable (recent load failure)", details={"model": settings[0]})
    try:
        model = _load_cross_encoder(*settings, config_path)
        raw = model.predict(
            [(query, text) for text in texts], batch_size=len(texts), show_progress_bar=False, convert_to_numpy=True
        )
        scores = [float(score) for score in raw]
    except Exception as e:  # noqa: BLE001 -- a reranker failure must never take down /query
        _failed_at[key] = time.monotonic()
        log.warning("cross-encoder %s unavailable; the vault-hit gate falls back to the cosine rule: %s", settings[0], e)
        raise RerankerError(f"cross-encoder unavailable: {e}", details={"model": settings[0]}) from e
    _failed_at.pop(key, None)
    if len(scores) != len(texts):
        raise RerankerError(
            "cross-encoder returned a score count that does not match its inputs",
            details={"model": settings[0], "texts": len(texts), "scores": len(scores)},
        )
    return scores
