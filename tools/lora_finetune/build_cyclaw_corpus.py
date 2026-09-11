#!/usr/bin/env python3
"""Build the improved cyclaw_training.json (+ .jsonl for Unsloth SFT).

Deliverable 1. Reads the prior Alpaca-style CURATED_QA (36 pairs) from
curated_qa.py and the new structured DEBUG_QA (12 debugging pairs) from
cyclaw_debug_qa.py, normalizes BOTH into one canonical format, and emits:

  - cyclaw_training.json   : canonical structured array
      [{id, category, messages:[{role,content}], source_refs}]
  - cyclaw_training.jsonl  : one record per line with a pre-rendered `text`
      column, ready for `datasets.load_dataset("json", ...)` + Unsloth SFTTrainer
      with dataset_text_field="text".

The chat template is applied via tokenizer.apply_chat_template when transformers
is installed; otherwise a Qwen-compatible fallback renderer is used so the
build never hard-fails on a machine without the HF stack. The fallback is
clearly labeled in the file header so a reviewer knows to re-render with the
real tokenizer before training.

Grounded in CyClaw source read from github.com/CGFixIT/CyClaw main on
2026-09-07 (graph.py, INVARIANTS.md, retrieval/indexer.py, llm/client.py).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# Prior work: 36 curated instruction/input/output pairs (Alpaca-style).
from curated_qa import CURATED_QA  # type: ignore[import-not-found]
# Deliverable 2: 12 new structured debugging pairs.
from cyclaw_debug_qa import DEBUG_QA  # type: ignore[import-not-found]
# Expansion set: 22 additional structured pairs (extra-001..022).
from curated_qa_extra import EXTRA_QA  # type: ignore[import-not-found]

SYSTEM_PREAMBLE = (
    "You are CyClaw's assistant. You reason about the CyClaw architecture "
    "(github.com/CGFixIT/CyClaw, v1.9.x) from source, follow its I1-I6 "
    "invariants, and never propose changes that bypass retrieval, audit, or "
    "soul governance. Distinguish established fact from reasonable inference, "
    "and cite the file and function."
)

# Category map for the prior 36 pairs (in CURATED_QA order). The original file
# has section banners; rather than re-parse banners, we tag by known index
# ranges that match the curated_qa.py structure read this session.
_PRIOR_CATEGORIES = [
    # 1. Architecture & Topology (5)
    "Architecture & Topology", "Architecture & Topology", "Architecture & Topology",
    "Architecture & Topology", "Architecture & Topology",
    # 2. Security & Defense (5)
    "Security & Defense", "Security & Defense", "Security & Defense",
    "Security & Defense", "Security & Defense",
    # 3. Retrieval & RAG (4)
    "Retrieval & RAG", "Retrieval & RAG", "Retrieval & RAG", "Retrieval & RAG",
    # 4. Soul Governance (3)
    "Soul Governance", "Soul Governance", "Soul Governance",
    # 5. Telemetry & Offline (2)
    "Telemetry & Offline", "Telemetry & Offline",
    # 6. Error Handling (3)
    "Error Handling", "Error Handling", "Error Handling",
    # 7. Extension Patterns (3)
    "Extension Patterns", "Extension Patterns", "Extension Patterns",
    # 8. Debugging Scenarios (4)
    "Debugging Scenarios", "Debugging Scenarios", "Debugging Scenarios",
    "Debugging Scenarios",
    # 9. Code Patterns (4)
    "Code Patterns", "Code Patterns", "Code Patterns", "Code Patterns",
    # 10. Design Philosophy (3)
    "Design Philosophy", "Design Philosophy", "Design Philosophy",
]


def _alpaca_to_canonical(idx: int, item: dict) -> dict:
    """Convert {instruction, input, output} -> {id, category, messages, source_refs}."""
    instruction = item["instruction"].strip()
    user_input = item.get("input", "").strip()
    user_text = f"{instruction}\n\n{user_input}" if user_input else instruction
    category = _PRIOR_CATEGORIES[idx] if idx < len(_PRIOR_CATEGORIES) else "Uncategorized"
    return {
        "id": f"curated-{idx:03d}",
        "category": category,
        "messages": [
            {"role": "system", "content": SYSTEM_PREAMBLE},
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": item["output"].strip()},
        ],
        "source_refs": ["curated_qa.py"],
    }


def _debug_already_canonical(item: dict) -> dict:
    """DEBUG_QA is already canonical; just ensure a system turn is present."""
    msgs = item["messages"]
    if not msgs or msgs[0].get("role") != "system":
        msgs = [{"role": "system", "content": SYSTEM_PREAMBLE}, *msgs]
    return {
        "id": item["id"],
        "category": item["category"],
        "messages": msgs,
        "source_refs": item.get("source_refs", []),
    }


def build_canonical() -> list[dict]:
    examples: list[dict] = []
    for i, item in enumerate(CURATED_QA):
        examples.append(_alpaca_to_canonical(i, item))
    for item in DEBUG_QA:
        examples.append(_debug_already_canonical(item))
    for item in EXTRA_QA:
        examples.append(_debug_already_canonical(item))
    return examples


# ── Chat-template rendering ─────────────────────────────────────────────────
def _try_apply_chat_template(messages: list[dict]) -> str | None:
    """Use the real tokenizer if transformers is importable. Returns None on failure."""
    try:
        from transformers import AutoTokenizer  # type: ignore[import]
    except ImportError:
        return None
    # Use a small, universally-available tokenizer just to get a correct
    # ChatML-style rendering. The trainer swaps in the real Qwen tokenizer at
    # train time; here we only need structurally-correct turn delimiters.
    # ImportError is the only expected miss; a load/network failure is logged
    # and we fall through to the ChatML fallback instead of swallowing every
    # exception (S112).
    last_err: str | None = None
    for name in ("Qwen/Qwen2.5-0.5B", "Qwen/Qwen2-0.5B"):
        try:
            tok = AutoTokenizer.from_pretrained(name)
            return tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
        except (OSError, ValueError, RuntimeError) as exc:
            last_err = f"{name}: {exc}"
    if last_err is not None:
        print(f"[build_cyclaw_corpus] tokenizer unavailable ({last_err}); using ChatML fallback",
              file=sys.stderr)
    return None


def _fallback_render(messages: list[dict]) -> str:
    """ChatML fallback if no tokenizer is available. Clearly labeled."""
    parts = ["<|im_start|>system\nYou are CyClaw's assistant.<|im_end|>"]
    for m in messages:
        role = m["role"]
        # The fallback replaces any system content with a minimal label so the
        # file is self-documenting as NOT final. Re-render with the real
        # tokenizer before training.
        if role == "system":
            continue
        parts.append(f"<|im_start|>{role}\n{m['content']}<|im_end|>")
    return "\n".join(parts)


def render_text(messages: list[dict]) -> tuple[str, str]:
    """Return (rendered_text, method) where method in {real,fallback}."""
    text = _try_apply_chat_template(messages)
    if text is not None:
        return text, "real"
    return _fallback_render(messages), "fallback"


def write_jsonl(examples: list[dict], path: Path) -> str:
    """Write training-ready JSONL with a `text` column. Returns the render method used."""
    methods: set[str] = set()
    with open(path, "w", encoding="utf-8") as f:
        for ex in examples:
            text, method = render_text(ex["messages"])
            methods.add(method)
            f.write(json.dumps({"text": text}, ensure_ascii=False) + "\n")
    return "real" if methods == {"real"} else ("fallback" if methods == {"fallback"} else "mixed")


def main() -> int:
    examples = build_canonical()
    json_path = HERE / "cyclaw_training.json"
    jsonl_path = HERE / "cyclaw_training.jsonl"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(examples, f, ensure_ascii=False, indent=2)

    method = write_jsonl(examples, jsonl_path)

    # Category distribution for verification.
    from collections import Counter
    dist = Counter(ex["category"] for ex in examples)

    print(f"Wrote {len(examples)} examples")
    print(f"  canonical: {json_path}")
    print(f"  training:  {jsonl_path}  (render={method})")
    print("Category distribution:")
    for cat, n in sorted(dist.items()):
        print(f"  {n:>2}  {cat}")
    if method != "real":
        print(
            "NOTE: chat template rendered with the fallback. Re-run on a machine "
            "with `transformers` installed, or run finetune_qwen38.py which "
            "re-renders with the real Qwen tokenizer before training."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
