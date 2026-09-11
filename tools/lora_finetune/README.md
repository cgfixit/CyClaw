# CyClaw Qwen3.8-27B LoRA Fine-Tune Kit

> Interesting to learn more about but not compatible with current GPU

Fine-tune **Qwen3.8-27B** with QLoRA via [Unsloth](https://unsloth.ai) on a
curated CyClaw (github.com/CGFixIT/CyClaw) Q&A dataset. Grounded in the live
CyClaw source read from `main` on 2026-09-07 (`graph.py`, `INVARIANTS.md`,
`retrieval/indexer.py`, `llm/client.py`, `config.yaml`).

This is an **offline operator toolkit**. The CyClaw runtime install
(`requirements.txt`, `pyproject.toml` extras, Docker, conda) does **not**
install Unsloth, Transformers, TRL, Datasets, or Accelerate. Train only on
a CUDA box after `pip install -r tools/lora_finetune/requirements.txt`.

The kit `requirements.txt` lists **direct** operator packages only (current
patched pins as of 2026-09-11). It is **not** a lockfile of Unsloth's GPU
tree. CyClaw's OSV-Scanner walk excludes `tools/lora_finetune`
(`--experimental-exclude=r:lora_finetune`) because OSV
v2 resolves `requirements.txt` transitives and Unsloth's published graph
still expands to known-vulnerable wheels (pillow 9.5, aiohttp 3.9.5,
torch 2.9.1) that this repo never installs. After you install on the GPU
box, run `pip-audit -r tools/lora_finetune/requirements.txt` there.

Unsloth 2026.9.4 still publishes `transformers<=5.5.0` / `trl<=0.24.0` /
`datasets<4.4`. If `pip install -r requirements.txt` refuses the patched
HF pins, install Unsloth alone and let it resolve that stack:

```bash
pip install --upgrade --force-reinstall --no-cache-dir unsloth==2026.9.4
```

## Files

| File | Purpose |
|---|---|
| `cyclaw_training.json` | **Canonical dataset** — 70 examples as `{id, category, messages:[system/user/assistant], source_refs}`. This is the deliverable. |
| `cyclaw_training.jsonl` | Preview only — `text` column rendered with a ChatML fallback because the sandbox lacks `transformers`. The fine-tune script re-renders with the real Qwen tokenizer. |
| `curated_qa.py` | The original 36 curated Q&A (Alpaca `instruction/input/output`), now patched (`min_score` 0.030 → 0.028 to match `config.yaml`). |
| `cyclaw_debug_qa.py` | 12 structured debugging Q&A (debug-005 … debug-016), grounded in `graph.py`/`INVARIANTS.md`/`indexer.py`/`llm/client.py`. |
| `curated_qa_extra.py` | **22 expansion pairs** (extra-001 … extra-022), grounded in `utils/personality.py`, `utils/telemetry_kill.py`, `utils/errors.py`, `utils/sanitizer.py`, `graph.py`. |
| `build_cyclaw_corpus.py` | Builds `cyclaw_training.json` + `.jsonl` from all three sources. |
| `finetune_qwen38.py` | Unsloth QLoRA training script (verified API). |
| `requirements.txt` | Optional operator pins — direct packages only (`unsloth`/`transformers`/`trl`/`datasets`/`accelerate`). Not part of the CyClaw runtime install; not an OSV lockfile. |
| `dryrun_finetune.py` | Dry-run harness: mocks `unsloth`/`trl`/`datasets` and runs `finetune_qwen38.py` end-to-end without a GPU. |
| `tests/test_build_corpus.py` | Unit tests: dataset structure, provenance, rendering, JSON round-trip (19 tests). |
| `tests/test_finetune_integration.py` | Integration tests: mocked control-flow for `finetune_qwen38.py` (8 tests). |
| `tests/test_hardening_and_cli.py` | Revision-pinning regression tests (audit-report.md's must-fix finding), `finetune_qwen38.py` CLI error paths (missing/malformed/empty dataset, missing Unsloth), and `.gitignore` hygiene (11 tests). |
| `README.md` | This file. |

## Dataset shape

70 examples across 10 categories, built from three tiers:

- **Tier 1** (36): `curated_qa.py` — the reasoning core (architecture, security, retrieval, soul, telemetry, errors, extension, debugging, code patterns, philosophy).
- **Tier 2** (12): `cyclaw_debug_qa.py` — debugging scenarios grounded in live source.
- **Tier 3** (22): `curated_qa_extra.py` — expansion pairs grounded in `personality.py`, `telemetry_kill.py`, `errors.py`, `sanitizer.py`, `graph.py`.

Debugging Scenarios = 19 (4 prior + 12 debug + 3 extra).

```
 7  Architecture & Topology      4  Extension Patterns
 8  Security & Defense           6  Retrieval & RAG
 5  Code Patterns                6  Soul Governance
19  Debugging Scenarios          5  Telemetry & Offline
 4  Design Philosophy           6  Error Handling
```

## Hardware

QLoRA on a 27B model needs **≥24 GB VRAM** (tight; 48 GB is the comfortable
single-card zone) ([Unsloth Qwen3.8 docs](https://unsloth.ai/docs/models/qwen3.8/train),
[YottaLabs](https://www.yottalabs.ai/post/how-to-fine-tune-qwen-3-8-27b-with-unsloth-2026),
[van Riel](https://zenvanriel.com/ai-engineer-blog/fine-tune-qwen-3-27b-on-consumer-hardware/)).
Chris's primary machine is an M5 Mac with **no GPU** — run this on a rented
GPU pod (RunPod / Vast.ai / Lambda) or a 2×T4 Kaggle notebook.

## Run

```bash
# 0. (optional) regenerate the canonical dataset
python build_cyclaw_corpus.py

# 0b. run the test suites (no GPU needed)
pip install pytest
python -m pytest tests/ -q          # 38 tests -- run from tools/lora_finetune/
python dryrun_finetune.py            # end-to-end control-flow check
# NOTE: these tests live outside pyproject.toml's testpaths = ["tests"], so a
# root-level `pytest tests/` does NOT collect them -- it runs the main suite
# instead. CI covers this kit in .github/workflows/lora-finetune.yml.

# 1. fine-tune (on a CUDA box with >=24 GB VRAM)
pip install -r requirements.txt
python finetune_qwen38.py --json cyclaw_training.json

# 2. load in Ollama (the script writes outputs_qwen38/gguf/Modelfile.cyclaw)
cd outputs_qwen38/gguf
ollama create cyclaw-qwen -f Modelfile.cyclaw
ollama run cyclaw-qwen
```

### Fine-tune script flags

| Flag | Default | Effect |
|---|---|---|
| `--model-name` | `unsloth/Qwen3.8-27B-unsloth-bnb-4bit` | Override the base checkpoint (see model-name caveat). |
| `--max-seq-length` | 2048 | Max sequence length for `FastModel.from_pretrained` and `SFTConfig`. |
| `--lora-rank` / `--lora-alpha` | 16 / 16 | LoRA rank and alpha. |
| `--max-steps` | 0 | If >0, cap training to N steps. If 0, use `--epochs`. |
| `--epochs` | 3 | Used only when `--max-steps` is 0. |
| `--batch-size` / `--grad-accum` | 1 / 4 | Per-device batch and gradient accumulation. The VRAM-tier and epoch-count guidance below assumes `--batch-size 2` (effective batch 8) — pass it explicitly; the script's own default is 1 (effective batch 4). |
| `--learning-rate` | 2e-4 | AdamW 8-bit learning rate. |
| `--no-export-gguf` | off | Skip the GGUF + Modelfile export (LoRA adapter only). |
| `--no-offload-embedding` | off | Disable `offload_embedding=True` (not recommended). |

## What 70 examples actually teach

This is a **behavioral / style / debugging-priors seed**, not a knowledge
injection. 70 examples will teach the model CyClaw's answer shape, invariant
discipline (I1–I6), and where to look when a symptom appears — it will **not**
teach the full repo. RAG (Tier 1) remains the source-of-truth path for code
facts; this LoRA nudges the model toward correct CyClaw reasoning on top of
that. For deeper internalization you'd need ~3–5M tokens of curated pairs.

## Training recommendations

**Hyperparameters (defaults are sane for a 70-example seed):**

- `lora_rank=16`, `lora_alpha=16`, `lora_dropout=0` — r=16 is the right size
  for a small dataset; higher ranks (32/64) overfit 70 examples. Match
  alpha to rank (1:1) unless you have a reason to scale.
- `learning_rate=2e-4`, `optim=adamw_8bit` — the standard QLoRA pair. Lower to
  1e-4 if loss diverges in the first 20 steps.
- `max_seq_length=2048` — every example in the 70-pair set renders under
  ~1500 tokens, so 2048 leaves headroom. Don't increase to 4096 unless you
  add longer examples; it raises VRAM without benefit.
- `epochs=3` (when `--max-steps 0`) or `--max-steps 50–100` as a cap. With 70
  examples and batch 2 / grad-accum 4 (effective batch 8), one epoch is ~9
  steps; 3 epochs ≈ 27 steps. Set `--max-steps 60` to stop early if loss
  plateaus. Monitor for overfitting past epoch 3 — at this dataset size the
  model memorizes fast.
- `gradient_accumulation_steps=4` — keeps the effective batch at 8 even on a
  24 GB card where batch 2 is the per-device max.
- `use_gradient_checkpointing="unsloth"` — required to fit 27B QLoRA on 24 GB;
  costs ~20% throughput.
- `report_to="none"` — no W&B/MLflow; the dataset is too small to justify
  external tracking infra.

**Order of operations:**

1. Run `python -m pytest tests/ -q` first (38 tests, no GPU). This catches
   dataset-structure regressions and script control-flow bugs before you pay
   for GPU time.
2. Run `python dryrun_finetune.py` — confirms the script's control flow,
   chat-template rendering, and save-path logic without Unsloth installed.
3. Only then spin up the GPU pod and run `finetune_qwen38.py` for real.

**Overfitting guardrails (this dataset is small):**

- 70 examples is a behavioral nudge, not a knowledge base. The model will
  memorize exact phrasings after a few epochs — set `--max-steps 60` or
  `--epochs 3` as a ceiling, and evaluate against held-out CyClaw questions
  (not the training set) before declaring success.
- Don't treat rising training accuracy as progress. The signal that matters
  is: does the fine-tuned model, when given a CyClaw debugging question it
  wasn't trained on, reach the same diagnostic as the source code? If not, the
  LoRA didn't generalize — add more diverse pairs rather than more epochs.
- Save a checkpoint early (`--max-steps 30` run, then a `--max-steps 60` run)
  and compare. The earlier checkpoint often generalizes better on a dataset
  this small.

**VRAM tier:**

- 24 GB (e.g. RTX 4090, A10): fits with `use_gradient_checkpointing`, batch 2,
  grad-accum 4. This is the minimum; expect ~1.5–2.5 hours for 60 steps.
- 48 GB (A6000, L40): comfortable; you can raise batch to 4 and drop
  grad-accum to 2, halving wall-clock.
- 2×24 GB: Unsloth supports multi-GPU but for 70 examples single-card is
  simpler and fast enough — don't bother with DDP unless you scale the dataset.
- Apple Silicon (M5 Mac): **not supported** for this script. Unsloth targets
  NVIDIA CUDA. Run on a rented pod (RunPod/Vast.ai/Lambda ~$0.30–0.60/hr for
  an A10) or a 2×T4 Kaggle notebook.

## Model-name caveat

Default `--model-name` is `unsloth/Qwen3.8-27B-unsloth-bnb-4bit` (the current
Unsloth-supported 27B). CyClaw's `config.yaml` ships `qwen3.8:27b-mlx` as the
local Ollama model. If you want the fine-tuned adapter to load on top of that
exact Ollama base, **verify first** that the HF checkpoint shares the same
architecture/weights family as the Ollama `qwen3.8:27b-mlx` tag — mismatched
base models break LoRA. The safe path is to export a full merged GGUF (the
script does this by default) and load THAT in Ollama, not an `ADAPTER` on a
different base.
