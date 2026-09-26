"""The reranker bake-off's labels and its pre-registered selection rule.

Covers tests/rerank_probes.py (answer keys and the fresh probe set) and the
pure functions of scripts/rerank_bakeoff.py. No model is loaded and no index is
built: the rule is arithmetic over labeled windows, tested on hand-built ones
whose right answer is known. The script is loaded by path, like
tests/test_measure_local_llm_throughput.py, since scripts/ is not a package.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from tests import ci_rag_smoke as smoke
from tests import rerank_probes as probes

_REPO = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO / "scripts" / "rerank_bakeoff.py"


@pytest.fixture(scope="module")
def bakeoff():
    spec = importlib.util.spec_from_file_location("rerank_bakeoff", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # dataclasses resolve the script's string annotations through
    # sys.modules[cls.__module__], so the module must be registered first.
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
        yield mod
    finally:
        sys.modules.pop(spec.name, None)


def _window(bakeoff, corpus: str, good: bool, score: float, split: str = "calibration"):
    return bakeoff.Window(corpus, split, "g", f"q{score}", 0.5, good, [], scores={"c": score})


def _windows(bakeoff, small_good, small_bad, big_good, big_bad, split="calibration"):
    out = [_window(bakeoff, bakeoff.SMALL, True, s, split) for s in small_good]
    out += [_window(bakeoff, bakeoff.SMALL, False, s, split) for s in small_bad]
    out += [_window(bakeoff, bakeoff.BIG, True, s, split) for s in big_good]
    out += [_window(bakeoff, bakeoff.BIG, False, s, split) for s in big_bad]
    return out


# --- labels ---------------------------------------------------------------


def test_answer_keys_cover_exactly_the_answerable_probes(bakeoff) -> None:
    bakeoff.check_labels()


def test_every_answer_key_occurs_somewhere_in_the_corpus() -> None:
    texts = [
        probes.normalize_for_keys(path.read_text(encoding="utf-8", errors="ignore"))
        for root in (_REPO / "data" / "corpus", _REPO / "docs")
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".md", ".txt"}
    ]
    missing = [
        (query, key)
        for query, keys in probes.ANSWER_KEYS.items()
        for key in keys
        if not any(probes.normalize_for_keys(key) in text for text in texts)
    ]
    assert not missing, f"answer keys that no corpus file contains (typo?): {missing}"


def test_answer_in_window_ignores_case_curly_quotes_emphasis_and_spacing() -> None:
    query = "Which character in the tale acts as the group's conscience and is slowest to authorize intervention?"
    assert probes.answer_in_window(query, ["other text", "**Opus-Prime** functions as the COUNCIL’S\n  conscience"])
    assert not probes.answer_in_window(query, ["Opus-Prime is the eldest"])


def test_probes_without_keys_are_never_answered() -> None:
    assert not probes.answer_in_window(probes.FRESH_LOOKALIKE[0], ["hot brew and cold brew coffee"])
    assert not probes.answer_in_window("a query nobody labeled", ["anything at all"])


def test_fresh_probes_are_new_and_look_alikes_carry_no_keys() -> None:
    earlier = {q for q, _ in smoke.QUERIES + smoke.PARAPHRASE_QUERIES + smoke.KNOWN_GAP_ANSWERABLE}
    earlier |= {q for q, _ in smoke.HELD_OUT_ANSWERABLE} | set(smoke.DOCS_PARAPHRASE_QUERIES)
    earlier |= set(smoke.OFF_TOPIC_QUERIES) | set(smoke.LOOKALIKE_QUERIES) | set(smoke.HELD_OUT_LOOKALIKE)
    fresh = [q for q, _ in probes.FRESH_ANSWERABLE] + list(probes.FRESH_LOOKALIKE)
    assert len(set(fresh)) == len(fresh)
    assert not earlier & set(fresh)
    assert not set(probes.FRESH_LOOKALIKE) & set(probes.ANSWER_KEYS)


# --- the rule -------------------------------------------------------------


def test_rates_count_lost_good_hits_and_kept_bad_hits(bakeoff) -> None:
    windows = _windows(bakeoff, [5, 1], [0.5, 3], [2], [])
    by_corpus = bakeoff.rates(windows, "c", 2.0)
    small, big = by_corpus[bakeoff.SMALL], by_corpus[bakeoff.BIG]
    assert (small.good, small.lost, small.bad, small.kept) == (2, 1, 2, 1)
    assert small.lar == pytest.approx(0.5) and small.fhr == pytest.approx(0.5)
    assert small.j == pytest.approx(1.5 * 0.5 + 0.5)
    # No bad hits on a corpus: nothing to let through, so FHR is 0 there.
    assert (big.good, big.lost, big.bad, big.kept, big.fhr) == (1, 0, 0, 0, 0.0)
    no_veto = bakeoff.rates(windows, "c", None)
    assert no_veto[bakeoff.SMALL].lost == 0 and no_veto[bakeoff.SMALL].kept == 2


def test_threshold_is_the_midpoint_of_the_best_feasible_gap(bakeoff) -> None:
    # Scores 1 (a small-corpus good hit) and 1.0 (a big-corpus bad hit) tie, so
    # removing every bad hit would cost 1 of 5 good hits (20% > 10%). The best
    # feasible veto removes the small corpus's bad hits and keeps the big
    # corpus's 1.0: J = mean(0, 1.5 * 1/2) = 0.375, at the midpoint of 0.5 and 1.0.
    windows = _windows(bakeoff, [5, 4, 3, 2, 1], [0.5, 0.2], [5, 4, 3, 2, 1.5], [1.0, 0.1])
    threshold, j = bakeoff.pick_threshold(windows, "c")
    assert threshold == pytest.approx(0.75)
    assert j == pytest.approx(0.375)


def test_threshold_search_respects_the_ten_percent_loss_cap(bakeoff) -> None:
    # Ten good hits per corpus: losing one (10%) is allowed, losing two is not.
    small_good = [0.1, 0.2] + [9.0] * 8
    windows = _windows(bakeoff, small_good, [0.3], [9.0] * 10, [0.3])
    threshold, j = bakeoff.pick_threshold(windows, "c")
    by_corpus = bakeoff.rates(windows, "c", threshold)
    assert all(r.lar <= bakeoff.CALIBRATION_MAX_LOST for r in by_corpus.values())
    # Vetoing 0.3 would also veto both small-corpus 0.1 and 0.2 (20%), so the
    # bad hits stay: the best feasible choice is no veto at all.
    assert threshold is None
    assert j == pytest.approx(bakeoff.NO_VETO_J)


def test_no_veto_wins_when_every_veto_costs_more_than_it_saves(bakeoff) -> None:
    windows = _windows(bakeoff, [1.0] + [5.0] * 9, [9.0], [5.0] * 10, [9.0])
    threshold, j = bakeoff.pick_threshold(windows, "c")
    assert threshold is None
    assert j == pytest.approx(1.5)


def test_a_clean_separation_vetoes_every_bad_hit_at_the_middle_of_the_gap(bakeoff) -> None:
    # Bad hits at 0 and 1, good hits from 5 up: any threshold in (1, 5)
    # removes both bad hits and loses nothing, and the search takes its middle.
    windows = _windows(bakeoff, [5.0, 6.0], [0.0], [5.0, 7.0], [1.0])
    threshold, j = bakeoff.pick_threshold(windows, "c")
    assert threshold == pytest.approx(3.0)
    assert j == pytest.approx(0.0)


def test_auc_is_the_chance_a_good_hit_outscores_a_bad_one(bakeoff) -> None:
    windows = _windows(bakeoff, [3, 4], [1, 2], [1], [1])
    assert bakeoff.auc(windows, "c", bakeoff.SMALL) == pytest.approx(1.0)
    assert bakeoff.auc(windows, "c", bakeoff.BIG) == pytest.approx(0.5)
    assert bakeoff.auc(_windows(bakeoff, [1], [], [], []), "c", bakeoff.SMALL) is None


def _result(j: float, ms: float, threshold: float | None = 0.0, loaded: bool = True, config: str = "x") -> dict:
    return {"config": config, "loaded": loaded, "ms_per_window": ms, "threshold": threshold, "calibration_j": j}


def test_selection_drops_slow_unloaded_and_non_improving_configurations(bakeoff) -> None:
    assert bakeoff.select([]) is None
    assert bakeoff.select([_result(0.2, bakeoff.MAX_WINDOW_MS + 1)]) is None
    assert bakeoff.select([_result(0.2, 100, threshold=None)]) is None
    assert bakeoff.select([_result(bakeoff.NO_VETO_J, 100)]) is None
    assert bakeoff.select([{"model": "m", "loaded": False}, _result(0.4, 100, config="ok")])["config"] == "ok"


def test_selection_prefers_the_fastest_within_the_near_tie(bakeoff) -> None:
    slow_best, fast_close = _result(0.50, 2000, config="slow"), _result(0.54, 300, config="fast")
    assert bakeoff.select([slow_best, fast_close])["config"] == "fast"
    fast_worse = _result(0.56, 300, config="fast")
    assert bakeoff.select([slow_best, fast_worse])["config"] == "slow"


def test_fresh_verdict(bakeoff) -> None:
    ok = {"fresh_j": 0.8, "fresh_lar": {bakeoff.SMALL: 0.1, bakeoff.BIG: 0.15}}
    assert bakeoff.fresh_passes(ok)
    assert not bakeoff.fresh_passes({**ok, "fresh_j": 1.01})
    assert not bakeoff.fresh_passes({**ok, "fresh_lar": {bakeoff.SMALL: 0.16, bakeoff.BIG: 0.0}})
