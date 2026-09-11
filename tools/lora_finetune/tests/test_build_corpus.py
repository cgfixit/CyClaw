# Unit tests for the CyClaw LoRA dataset builders.
# Run:  cd cyclaw-finetune && python3 -m pytest tests/ -q
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import build_cyclaw_corpus as bcc  # type: ignore[import]
import curated_qa_extra as extra  # type: ignore[import]
import cyclaw_debug_qa as debug  # type: ignore[import]


# Fixtures
@pytest.fixture(scope="module")
def canonical() -> list[dict]:
    return bcc.build_canonical()


@pytest.fixture(scope="module")
def rendered_jsonl(tmp_path_factory) -> Path:
    examples = bcc.build_canonical()
    out = tmp_path_factory.mktemp("data") / "train.jsonl"
    bcc.write_jsonl(examples, out)
    return out


# Structure
class TestDatasetStructure:
    def test_seventy_examples(self, canonical):
        assert len(canonical) == 70, len(canonical)

    def test_triad_on_every_example(self, canonical):
        for ex in canonical:
            roles = [m["role"] for m in ex["messages"]]
            assert roles == ["system", "user", "assistant"], (ex["id"], roles)

    def test_canonical_keys(self, canonical):
        for ex in canonical:
            assert set(ex.keys()) == {"id", "category", "messages", "source_refs"}, ex

    def test_ids_unique(self, canonical):
        ids = [ex["id"] for ex in canonical]
        assert len(set(ids)) == len(ids), "duplicate ids"

    def test_no_empty_turns(self, canonical):
        for ex in canonical:
            for m in ex["messages"]:
                assert isinstance(m["content"], str) and m["content"].strip(), (ex["id"], m["role"])

    def test_source_refs_is_list(self, canonical):
        for ex in canonical:
            assert isinstance(ex["source_refs"], list), ex["id"]


# Provenance / staleness
class TestProvenance:
    def test_no_stale_min_score(self, canonical):
        blob = json.dumps(canonical)
        assert "0.030" not in blob, "stale min_score 0.030 leaked into dataset"
        assert "0.028" in blob, "expected 0.028 (live config.yaml value) missing"

    def test_extra_ids_present(self, canonical):
        ids = [ex["id"] for ex in canonical]
        for n in range(1, 23):
            prefix = f"extra-{n:03d}"
            assert any(i.startswith(prefix) for i in ids), prefix

    def test_debug_ids_present(self, canonical):
        ids = {ex["id"] for ex in canonical}
        assert "debug-005-external-never-fires" in ids
        assert "debug-016-banned-patterns-homoglyph" in ids


# Extra set well-formedness
class TestExtraSet:
    def test_twenty_two_extras(self):
        assert len(extra.EXTRA_QA) == 22, len(extra.EXTRA_QA)

    def test_extra_categories_valid(self):
        valid = {
            "Architecture & Topology", "Security & Defense", "Retrieval & RAG",
            "Soul Governance", "Telemetry & Offline", "Error Handling",
            "Extension Patterns", "Debugging Scenarios", "Code Patterns",
            "Design Philosophy",
        }
        for ex in extra.EXTRA_QA:
            assert ex["category"] in valid, ex

    def test_debug_set_well_formed(self):
        assert len(debug.DEBUG_QA) == 12
        for ex in debug.DEBUG_QA:
            assert ex["messages"][0]["role"] == "system", ex["id"]


# Category distribution
class TestCategoryDistribution:
    def test_total_seventy(self, canonical):
        from collections import Counter
        dist = Counter(ex["category"] for ex in canonical)
        assert sum(dist.values()) == 70

    def test_debugging_count(self, canonical):
        n = sum(1 for ex in canonical if ex["category"] == "Debugging Scenarios")
        assert n == 19, n  # 4 prior + 12 debug + 3 extra

    def test_every_category_present(self, canonical):
        from collections import Counter
        dist = Counter(ex["category"] for ex in canonical)
        assert len(dist) == 10, sorted(dist)


# Rendering
class TestRendering:
    def test_jsonl_has_seventy_lines(self, rendered_jsonl):
        with open(rendered_jsonl, encoding="utf-8") as handle:
            line_count = sum(1 for _ in handle)
        assert line_count == 70

    def test_jsonl_text_non_empty(self, rendered_jsonl):
        for line in open(rendered_jsonl):
            rec = json.loads(line)
            assert rec["text"].strip(), rec

    def test_fallback_render_is_chatml(self):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a"},
        ]
        text, method = bcc.render_text(msgs)
        assert method in {"real", "fallback"}
        assert "<|im_start|>user\nq<|im_end|>" in text
        assert "<|im_start|>assistant\na<|im_end|>" in text


# JSON file round-trip
class TestJsonRoundTrip:
    def test_json_file_valid_and_matches(self, tmp_path):
        examples = bcc.build_canonical()
        p = tmp_path / "cyclaw_training.json"
        with open(p, "w", encoding="utf-8") as f:
            json.dump(examples, f, ensure_ascii=False, indent=2)
        with open(p, encoding="utf-8") as f:
            back = json.load(f)
        assert back == examples
        assert len(back) == 70
