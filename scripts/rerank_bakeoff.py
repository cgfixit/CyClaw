#!/usr/bin/env python3
"""Choose the vault-hit veto: score candidate cross-encoders on the RAG probe windows (issue #1456).

    python scripts/rerank_bakeoff.py [--cache-dir DIR] [--json PATH]

Needs the full install and network access to Hugging Face on a cold cache: each
candidate is fetched into --cache-dir, and the embedder into the repo's
models.embeddings.cache_dir. Asserts nothing. It prints a report and exits 0
unless it crashes.

What it measures. It builds two real indexes, data/corpus alone and data/corpus
plus docs/. For every probe in tests/ci_rag_smoke.py and tests/rerank_probes.py
it takes the LOCAL_CONTEXT_CHUNKS window from HybridRetriever.hybrid_search, the
window graph.retrieve_node hands the model. Only windows whose best cosine
clears retrieval.min_semantic_score count, since the veto can only turn a vault
hit into a miss. tests/rerank_probes.py labels each one: a good hit when an
answer key is in the window, a bad hit otherwise. No score goes into a label.
Every candidate then scores every such window twice: chunk by chunk, as
graph.retrieve_node does today, and passage by passage
(retrieval.rerank.split_passages, best passage per chunk). The window's score
is its best one, the number route_by_score_node compares.

The rule below was committed before any candidate scored the fresh probes.

* A veto at threshold t turns every window scoring below t into a miss. Per
  corpus, FHR is the share of bad hits still passing and LAR the share of good
  hits lost. J = 1.5 * FHR + LAR, averaged over the two corpora. A false hit
  costs as much as 1.5 lost answers, so false hits weigh slightly more, and
  using rates keeps the probe mix from deciding. No veto scores J = 1.5.
* Calibration uses the probes that existed before this script: the smoke's
  lists. For each model and granularity, t is the midpoint of the gap between
  adjacent calibration scores that gives the lowest J, among gaps that lose at
  most 10% of good hits on each corpus. Ties go to the lower loss, then to the
  wider gap.
* The chosen configuration has the lowest calibration J among those that load,
  beat no veto, and score a window in at most 3,000 ms on average on the
  machine running this. Within 0.05 of that J, the fastest wins.
* The choice then faces FRESH_ANSWERABLE and FRESH_LOOKALIKE. It passes if it
  loses at most 15% of good hits on each corpus and its mean J is at most 1.0.
  If it fails, no threshold ships.
"""

from __future__ import annotations

import argparse
import copy
import gc
import json
import math
import shutil
import statistics
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Before any third-party import, as every other entry point does.
from utils.telemetry_kill import apply_telemetry_kill  # noqa: E402

apply_telemetry_kill()

import yaml  # noqa: E402

from retrieval.embeddings import EMBED_DEVICE  # noqa: E402
from retrieval.hybrid_search import HybridRetriever  # noqa: E402
from retrieval.indexer import build_index  # noqa: E402
from retrieval.rerank import split_passages  # noqa: E402
from tests import ci_rag_smoke as smoke  # noqa: E402
from tests import rerank_probes as probes  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
WINDOW = smoke.CONTEXT_CHUNKS

FALSE_HIT_WEIGHT = 1.5
NO_VETO_J = FALSE_HIT_WEIGHT
CALIBRATION_MAX_LOST = 0.10
FRESH_MAX_LOST = 0.15
FRESH_MAX_J = 1.0
MAX_WINDOW_MS = 3000.0
NEAR_TIE = 0.05
GRANULARITIES = ("chunk", "passage")

CALIBRATION = "calibration"
FRESH = "fresh"
SMALL = "data/corpus"
BIG = "data/corpus + docs/"
CORPORA = (SMALL, BIG)


@dataclass(frozen=True)
class Candidate:
    model: str
    revision: str | None
    about: str


def candidates(cfg: dict[str, Any]) -> list[Candidate]:
    """The shipped reranker first, then four alternatives that load through CrossEncoder without remote code.

    ``revision`` None measures the Hub's main at run time; the report prints the
    snapshot it loaded, which is what a configuration would pin.
    """
    shipped = cfg["models"]["reranker"]
    return [
        Candidate(shipped["model"], shipped.get("revision"), "shipped; MS MARCO; 22.7M parameters"),
        Candidate("mixedbread-ai/mxbai-rerank-xsmall-v1", None, "DeBERTa-v3-xsmall; 70.8M parameters"),
        Candidate("Alibaba-NLP/gte-reranker-modernbert-base", None, "ModernBERT-base; 149M parameters"),
        Candidate("ibm-granite/granite-embedding-reranker-english-r2", None, "ModernBERT-base; 149M parameters"),
        Candidate("cross-encoder/qnli-electra-base", None, "QNLI answerability; ELECTRA-base; 110M parameters"),
    ]


def probe_sets() -> list[tuple[str, str, list[str]]]:
    """(split, group, queries). Calibration is every list the smoke had before this script."""
    return [
        (CALIBRATION, "verbatim", [q for q, _ in smoke.QUERIES]),
        (CALIBRATION, "paraphrase", [q for q, _ in smoke.PARAPHRASE_QUERIES]),
        (CALIBRATION, "known gap", [q for q, _ in smoke.KNOWN_GAP_ANSWERABLE]),
        (CALIBRATION, "held-out answerable", [q for q, _ in smoke.HELD_OUT_ANSWERABLE]),
        (CALIBRATION, "docs paraphrase", list(smoke.DOCS_PARAPHRASE_QUERIES)),
        (CALIBRATION, "off-topic", list(smoke.OFF_TOPIC_QUERIES)),
        (CALIBRATION, "look-alike", list(smoke.LOOKALIKE_QUERIES)),
        (CALIBRATION, "held-out look-alike", list(smoke.HELD_OUT_LOOKALIKE)),
        (FRESH, "fresh answerable", [q for q, _ in probes.FRESH_ANSWERABLE]),
        (FRESH, "fresh look-alike", list(probes.FRESH_LOOKALIKE)),
    ]


def check_labels() -> None:
    """Every answerable probe needs answer keys, and every key must belong to a probe."""
    answerable = [q for q, _ in smoke.QUERIES + smoke.PARAPHRASE_QUERIES + smoke.KNOWN_GAP_ANSWERABLE]
    answerable += [q for q, _ in smoke.HELD_OUT_ANSWERABLE] + list(smoke.DOCS_PARAPHRASE_QUERIES)
    answerable += [q for q, _ in probes.FRESH_ANSWERABLE]
    missing = sorted(set(answerable) - set(probes.ANSWER_KEYS))
    stray = sorted(set(probes.ANSWER_KEYS) - set(answerable))
    if missing or stray:
        raise SystemExit(f"answer keys out of step with the probe lists: missing={missing} stray={stray}")


@dataclass
class Window:
    corpus: str
    split: str
    group: str
    query: str
    best_cosine: float
    good: bool
    texts: list[str]
    scores: dict[str, float] = field(default_factory=dict)
    ms: dict[str, float] = field(default_factory=dict)


def build_retriever(tmp: Path, roots: Sequence[Path], cfg: dict[str, Any], name: str) -> HybridRetriever:
    """Index ``roots`` into ``tmp`` with the shipped settings, as tests/ci_rag_smoke.py --with-docs does."""
    corpus = tmp / "corpus"
    corpus.mkdir()
    extensions = {ext.lower() for ext in cfg["corpus"]["extensions"]}
    for root in roots:
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix.lower() in extensions:
                # Flattened names keep same-named files from different folders apart.
                shutil.copyfile(path, corpus / "__".join((root.name, *path.relative_to(root).parts)))
    local = copy.deepcopy(cfg)
    local["corpus"] = {**local["corpus"], "path": str(corpus)}
    local["indexing"] = {
        **local["indexing"],
        "chroma_path": str(tmp / "chroma"),
        "bm25_path": str(tmp / "bm25.json"),
        "collection_name": name,
    }
    embeddings = local["models"]["embeddings"]
    if embeddings.get("cache_dir"):
        embeddings["cache_dir"] = str((REPO / embeddings["cache_dir"]).resolve())
    config_path = tmp / "config.yaml"
    config_path.write_text(yaml.safe_dump(local), encoding="utf-8")
    build_index(str(config_path))
    return HybridRetriever(str(config_path))


def collect(retriever: HybridRetriever, corpus: str, floor: float) -> tuple[list[Window], dict[str, int]]:
    """Return the windows that clear the cosine gate, labeled, plus per-split counts of all probes."""
    windows: list[Window] = []
    counts: dict[str, int] = {}
    for split, group, queries in probe_sets():
        for query in queries:
            counts[f"{split} probes"] = counts.get(f"{split} probes", 0) + 1
            hits = retriever.hybrid_search(query)[:WINDOW]
            cosines = [h.semantic_score for h in hits if h.semantic_score is not None]
            if not cosines or max(cosines) < floor:
                continue
            texts = [h.text for h in hits]
            good = probes.answer_in_window(query, texts)
            label = "good" if good else "bad"
            counts[f"{split} {label}"] = counts.get(f"{split} {label}", 0) + 1
            windows.append(Window(corpus, split, group, query, max(cosines), good, texts))
    return windows, counts


def load_model(candidate: Candidate, cache_dir: Path) -> Any:
    from sentence_transformers import CrossEncoder
    from torch import nn

    return CrossEncoder(
        candidate.model,
        revision=candidate.revision,
        cache_folder=str(cache_dir),
        device=EMBED_DEVICE,
        activation_fn=nn.Identity(),
        trust_remote_code=False,
    )


def snapshot(candidate: Candidate, cache_dir: Path) -> str:
    """The commit hash of the files actually loaded, read from the Hugging Face cache layout."""
    try:
        from huggingface_hub import try_to_load_from_cache

        cached = try_to_load_from_cache(
            candidate.model, "config.json", cache_dir=str(cache_dir), revision=candidate.revision
        )
    except Exception:  # noqa: BLE001 -- provenance is informational only
        return "unknown"
    return Path(cached).parent.name if isinstance(cached, str) else "unknown"


def score(model: Any, windows: list[Window], config: str, granularity: str) -> None:
    """Record each window's best score and wall time, one predict call per window as graph.retrieve_node makes."""
    for window in windows:
        if granularity == "chunk":
            pairs = [(window.query, text) for text in window.texts]
        else:
            pairs = [(window.query, passage) for text in window.texts for passage in split_passages(text)]
        start = time.perf_counter()
        raw = model.predict(pairs, batch_size=len(pairs), show_progress_bar=False, convert_to_numpy=True).tolist()
        window.ms[config] = 1000 * (time.perf_counter() - start)
        if any(isinstance(value, list) for value in raw):
            raise ValueError(f"{config} returned more than one score per pair; the veto needs exactly one")
        finite = [float(value) for value in raw if math.isfinite(value)]
        window.scores[config] = max(finite) if finite else -math.inf


@dataclass
class Rates:
    good: int
    lost: int
    bad: int
    kept: int

    @property
    def lar(self) -> float:
        return self.lost / self.good if self.good else 0.0

    @property
    def fhr(self) -> float:
        return self.kept / self.bad if self.bad else 0.0

    @property
    def j(self) -> float:
        return FALSE_HIT_WEIGHT * self.fhr + self.lar


def rates(windows: list[Window], config: str, threshold: float | None) -> dict[str, Rates]:
    """Per corpus, how a veto at ``threshold`` (None: no veto) treats the labeled windows."""

    def vetoed(w: Window) -> bool:
        return threshold is not None and w.scores[config] < threshold

    out = {}
    for corpus in CORPORA:
        good = [w for w in windows if w.corpus == corpus and w.good]
        bad = [w for w in windows if w.corpus == corpus and not w.good]
        out[corpus] = Rates(len(good), sum(vetoed(w) for w in good), len(bad), sum(not vetoed(w) for w in bad))
    return out


def mean_j(by_corpus: dict[str, Rates]) -> float:
    return statistics.fmean(r.j for r in by_corpus.values())


def pick_threshold(calibration: list[Window], config: str) -> tuple[float | None, float]:
    """The pre-registered threshold search; returns (threshold or None for no veto, its mean J)."""
    values = sorted({w.scores[config] for w in calibration})
    best: tuple[tuple[float, float, float], float | None] | None = None
    options: list[tuple[float | None, float]] = [(None, math.inf)]
    options += [((low + high) / 2, high - low) for low, high in zip(values, values[1:], strict=False)]
    for threshold, gap in options:
        by_corpus = rates(calibration, config, threshold)
        if any(r.lar > CALIBRATION_MAX_LOST for r in by_corpus.values()):
            continue
        key = (mean_j(by_corpus), statistics.fmean(r.lar for r in by_corpus.values()), -gap)
        if best is None or key < best[0]:
            best = (key, threshold)
    if best is None:  # unreachable: "no veto" loses nothing, so it is always feasible
        raise RuntimeError("threshold search found no feasible option")
    return best[1], best[0][0]


def auc(windows: list[Window], config: str, corpus: str) -> float | None:
    """Chance a good hit outscores a bad hit on ``corpus`` (ties count half); threshold-free separability."""
    good = [w.scores[config] for w in windows if w.corpus == corpus and w.good]
    bad = [w.scores[config] for w in windows if w.corpus == corpus and not w.good]
    if not good or not bad:
        return None
    wins = sum((g > b) + 0.5 * (g == b) for g in good for b in bad)
    return wins / (len(good) * len(bad))


def select(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The pre-registered choice among scored configurations, or None when none qualifies."""
    eligible = [
        r
        for r in results
        if r.get("loaded")
        and r["ms_per_window"] <= MAX_WINDOW_MS
        and r["threshold"] is not None
        and r["calibration_j"] < NO_VETO_J
    ]
    if not eligible:
        return None
    best_j = min(r["calibration_j"] for r in eligible)
    near = [r for r in eligible if r["calibration_j"] <= best_j + NEAR_TIE]
    return min(near, key=lambda r: (r["ms_per_window"], r["calibration_j"]))


def fresh_passes(result: dict[str, Any]) -> bool:
    """The pre-registered verdict on the fresh probes for one configuration."""
    return all(v <= FRESH_MAX_LOST for v in result["fresh_lar"].values()) and result["fresh_j"] <= FRESH_MAX_J


def _fmt(by_corpus: dict[str, Rates]) -> str:
    parts = [f"{corpus}: FHR {r.kept}/{r.bad} LAR {r.lost}/{r.good}" for corpus, r in by_corpus.items()]
    return f"J {mean_j(by_corpus):.3f} ({'; '.join(parts)})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reranker bake-off; see the module docstring.")
    parser.add_argument("--cache-dir", type=Path, default=None, help="Hugging Face cache for the candidates")
    parser.add_argument("--json", type=Path, default=None, help="also write every window's scores here")
    args = parser.parse_args(argv)
    check_labels()

    with open(REPO / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    floor = float(cfg["retrieval"]["min_semantic_score"])
    print("=== Reranker bake-off (report only; issue #1456) ===")
    print(
        f"Rule: J = {FALSE_HIT_WEIGHT} * FHR + LAR, mean of both corpora; calibration LAR <= {CALIBRATION_MAX_LOST} "
        f"per corpus; <= {MAX_WINDOW_MS:.0f} ms per window; near-tie {NEAR_TIE} goes to the fastest; fresh "
        f"passes at LAR <= {FRESH_MAX_LOST} per corpus and mean J <= {FRESH_MAX_J}."
    )
    print(f"Window: {WINDOW} chunks; cosine gate: min_semantic_score {floor}")

    windows: list[Window] = []
    with tempfile.TemporaryDirectory(prefix="cyclaw-bakeoff-", ignore_cleanup_errors=True) as tmp:
        for corpus, roots in ((SMALL, [REPO / "data" / "corpus"]), (BIG, [REPO / "data" / "corpus", REPO / "docs"])):
            tag = "small" if corpus == SMALL else "big"
            base = Path(tmp) / tag
            base.mkdir()
            retriever = build_retriever(base, roots, cfg, f"bakeoff_{tag}")
            found, counts = collect(retriever, corpus, floor)
            print(f"{corpus}: {len(retriever.bm25_chunks)} chunks; " + ", ".join(f"{k} {v}" for k, v in counts.items()))
            windows.extend(found)
            retriever.close()

    cache_dir = args.cache_dir or Path(tempfile.gettempdir()) / "cyclaw-rerank-bakeoff"
    cache_dir.mkdir(parents=True, exist_ok=True)
    calibration = [w for w in windows if w.split == CALIBRATION]
    fresh = [w for w in windows if w.split == FRESH]
    results: list[dict[str, Any]] = []
    for candidate in candidates(cfg):
        try:
            model = load_model(candidate, cache_dir)
        except Exception as e:  # noqa: BLE001 -- one candidate failing to load must not end the bake-off
            print(f"\n[{candidate.model}] FAILED TO LOAD: {type(e).__name__}: {e}")
            results.append({"model": candidate.model, "loaded": False, "error": f"{type(e).__name__}: {e}"})
            continue
        loaded = snapshot(candidate, cache_dir)
        print(f"\n[{candidate.model}] {candidate.about}; snapshot {loaded}")
        for granularity in GRANULARITIES:
            config = f"{candidate.model} [{granularity}]"
            try:
                score(model, windows, config, granularity)
            except Exception as e:  # noqa: BLE001 -- report and move on
                print(f"  {granularity}: FAILED TO SCORE: {type(e).__name__}: {e}")
                results.append({"config": config, "loaded": False, "error": f"{type(e).__name__}: {e}"})
                continue
            ms = statistics.fmean(w.ms[config] for w in windows)
            threshold, cal_j = pick_threshold(calibration, config)
            cal = rates(calibration, config, threshold)
            fresh_rates = rates(fresh, config, threshold)
            aucs = {corpus: auc(calibration, config, corpus) for corpus in CORPORA}
            shown = "none (no veto)" if threshold is None else f"{threshold:.4f}"
            print(
                f"  {granularity}: {ms:.0f} ms/window (max {max(w.ms[config] for w in windows):.0f}); "
                "calibration AUC " + ", ".join(f"{c} {a:.3f}" if a is not None else f"{c} n/a" for c, a in aucs.items())
            )
            print(f"    threshold {shown}; calibration {_fmt(cal)}")
            print(f"    fresh at that threshold: {_fmt(fresh_rates)}")
            results.append(
                {
                    "config": config,
                    "model": candidate.model,
                    "snapshot": loaded,
                    "granularity": granularity,
                    "loaded": True,
                    "ms_per_window": ms,
                    "threshold": threshold,
                    "calibration_j": cal_j,
                    "fresh_j": mean_j(fresh_rates),
                    "fresh_lar": {c: r.lar for c, r in fresh_rates.items()},
                    "auc": aucs,
                }
            )
        del model
        gc.collect()

    print("\n=== Selection (pre-registered) ===")
    selected = select(results)
    if selected is None:
        print("No configuration beats no veto on calibration within the latency limit: no threshold ships.")
    else:
        selected["fresh_pass"] = fresh_passes(selected)
        print(
            f"Selected: {selected['config']} @ snapshot {selected['snapshot']}, threshold {selected['threshold']:.4f}, "
            f"{selected['ms_per_window']:.0f} ms/window, calibration J {selected['calibration_j']:.3f}"
        )
        print(
            f"Fresh verdict: {'PASS' if selected['fresh_pass'] else 'FAIL'} "
            f"(J {selected['fresh_j']:.3f} <= {FRESH_MAX_J}? LAR per corpus "
            + ", ".join(f"{c} {v:.3f}" for c, v in selected["fresh_lar"].items())
            + f" <= {FRESH_MAX_LOST}?)"
        )

    print("\n=== Every window (score per configuration; G = answer in window, B = not) ===")
    configs = [r["config"] for r in results if r.get("loaded")]
    for i, config in enumerate(configs):
        print(f"  c{i} = {config}")
    for w in windows:
        cells = " ".join(f"{w.scores[c]:7.2f}" for c in configs)
        tag = "small" if w.corpus == SMALL else "big"
        label = "G" if w.good else "B"
        print(f"{tag:5} {w.split[:5]:5} {label} cos {w.best_cosine:.3f} | {cells} | {w.group}: {w.query[:60]}")

    if args.json:
        payload = {
            "rule": {
                "false_hit_weight": FALSE_HIT_WEIGHT,
                "calibration_max_lost": CALIBRATION_MAX_LOST,
                "fresh_max_lost": FRESH_MAX_LOST,
                "fresh_max_j": FRESH_MAX_J,
                "max_window_ms": MAX_WINDOW_MS,
                "near_tie": NEAR_TIE,
            },
            "results": results,
            "selected": selected["config"] if selected else None,
            "windows": [{k: v for k, v in w.__dict__.items() if k != "texts"} for w in windows],
        }
        args.json.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
