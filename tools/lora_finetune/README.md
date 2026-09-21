# CyClaw Qwen3.8-27B LoRA Fine-Tune Kit

**CUDA training install blocked (verified 2026-09-21).** The pinned Unsloth
dependency ranges conflict with the patched Transformers/TRL/Datasets pins
in this kit's `requirements.txt`; pip reports `ResolutionImpossible`.
Keep those pins and do not bypass resolution with `--no-deps` or an
Unsloth-only install. Dataset generation and mocked tests remain usable;
CyClaw's core runtime does not install this training profile.

> Interesting to learn more about but not compatible with current GPU

^ ha that's not even true!:
LoRA is compatible (just gotta not be an idiot mindlessly letting ai tell me things) with Apple Silicon through MLX-LM, and `mlx_lm.lora` supports **QLoRA automatically** when you point it at a quantized MLX model. Your Mac is not incompatible with LoRA; it is incompatible with the specific **CUDA/Unsloth** kit currently in CyClaw.

That distinction is the entire issue.

## The direct answer

```text
Apple Silicon + MLX-LM             → LoRA: yes
Apple Silicon + MLX-LM quantized base → QLoRA: yes
Apple Silicon + Unsloth CUDA kit   → no
Ollama + external MLX LoRA adapter → no
MLX-fused model → Ollama deployment → possible, via compatible import/GGUF path
```

MLX-LM’s own LoRA documentation says exactly:

> If `--model` points to a quantized model, training uses **QLoRA**; otherwise it uses regular LoRA.

It also exposes `mlx_lm.lora` as an official installed command-line entry point.[1]

## What that means for your Mac

On your M5 MacBook Pro with 48 GB unified memory, you can plausibly run a **Mac-native MLX QLoRA experiment** against an MLX 4-bit model, assuming the particular Qwen architecture is supported and the sequence length, batch size, and adapter targets fit into available unified memory.

The key relationship is:

```text
Non-quantized MLX model
→ mlx_lm.lora
→ normal LoRA

Quantized MLX model, e.g. 4-bit
→ mlx_lm.lora
→ QLoRA
```

You do not need NVIDIA CUDA, BitsAndBytes, or Unsloth for that path. MLX uses Apple Silicon’s GPU through the MLX runtime, with CPU/GPU sharing unified memory.

## The commands

A minimal MLX QLoRA setup looks like this:

```bash
python -m pip install -U mlx-lm

mlx_lm.lora \
  --model /path/to/qwen-mlx-4bit \
  --train \
  --data /path/to/training-data \
  --adapter-path ./cyclaw-mlx-adapter \
  --iters 100 \
  --batch-size 1 \
  --num-layers 16
```

The exact data layout and flags depend on the installed MLX-LM release, so treat this as the shape of the command, then use:

```bash
mlx_lm.lora --help
```

The authoritative behavior is: a quantized `--model` selects QLoRA; an unquantized model selects regular LoRA.[1]

## Why the README was confusing

The CyClaw README describes a **different stack**:

```text
CUDA GPU
→ Unsloth
→ BitsAndBytes 4-bit base
→ QLoRA
→ Unsloth merged Q4_K_M GGUF export
→ Ollama
```

That is why it says Apple Silicon is unsupported: *that script* targets Unsloth/NVIDIA CUDA.

Your possible MLX path is instead:

```text
Apple Silicon
→ MLX-LM
→ MLX 4-bit base
→ mlx_lm.lora QLoRA
→ MLX adapter
→ validate with MLX dynamic adapter inference
→ mlx_lm.fuse --dequantize
→ compatible Ollama import or GGUF conversion
→ Ollama
```

Both are QLoRA workflows. They are just different runtimes, model formats, quantization implementations, adapter formats, and export paths.

## The caveat that matters

Do **not** expect artifacts to cross these stacks freely:

| Artifact | Usable by |
|---|---|
| Unsloth/BitsAndBytes LoRA adapter | Unsloth/Hugging Face setup built around its exact base |
| MLX LoRA adapter | MLX-LM built around its exact MLX base |
| Ollama GGUF | Ollama / llama.cpp |
| MLX fused output | MLX directly; potentially Ollama after supported Safetensors import or GGUF conversion |

The correct rule is:

> Train, dynamically validate, and fuse within the same runtime/base-model lineage. Export only the fused final model to a different runtime.

MLX-LM has explicit support for quantized-model LoRA training and a separate `mlx_lm.fuse` command with a `--dequantize` option for producing a dequantized fused model.[1][2]

## Bottom line

Your Mac **can train LoRA and QLoRA** using `mlx_lm.lora`. The CyClaw Unsloth script cannot, because Unsloth’s workflow is CUDA-specific. So the future MLX section is not merely theoretical—it describes a legitimate alternative local training path for you.

^standby for something in birh this and cg-agent soon... if i can get something to work haha
--

ELI5: Ollama is like a CD player that only plays finished albums. A LoRA adapter is like a remix you’d layer over a song — but Ollama can’t apply the remix live while the song plays. You have to bake the remix into a brand-new album first (that’s “fusing”), then Ollama plays that.
Tech101: A LoRA adapter is a set of low-rank delta weights applied on top of a quantized base model. Ollama’s runtime loads GGUF models and has no path to apply an external MLX-format adapter at inference — the on-disk formats and the loaders are incompatible, not just unsupported. Fusing merges the adapter deltas into the base to produce one standalone model Ollama can load directly. There is no shortcut: skip the fuse and Ollama simply has no way to use your training.

<hr>


Fine-tune **Qwen3.8-27B** with QLoRA via [Unsloth](https://unsloth.ai) on a
curated CyClaw (github.com/CGFixIT/CyClaw) Q&A dataset. Grounded in the live
CyClaw source read from `main` on 2026-09-07 (`graph.py`, `INVARIANTS.md`,
`retrieval/indexer.py`, `llm/client.py`, `config.yaml`).

This is a separate **operator training toolkit**. CyClaw's runtime profiles
do not install this directory's training requirements. Transformers already
arrives through the base sentence-transformers dependency; that does not
provide or validate the Unsloth training stack. Training needs a compatible
CUDA dependency profile; the current requirements are blocked as described
below. Model/tokenizer loading can fetch Hugging Face assets;
seed their caches first if training must run without egress.

The kit `requirements.txt` lists **direct** operator packages only (current
patched pins as of 2026-09-11). It is **not** a lockfile of Unsloth's GPU
tree. CyClaw's OSV-Scanner walk excludes `tools/lora_finetune`
(`--experimental-exclude=r:lora_finetune`) because OSV
v2 resolves `requirements.txt` transitives and Unsloth's published graph
still expands to known-vulnerable wheels (pillow 9.5, aiohttp 3.9.5,
torch 2.9.1) that this repo never installs. After you install on the GPU
box, run `pip-audit -r tools/lora_finetune/requirements.txt` there.

[Unsloth 2026.9.4](https://pypi.org/pypi/unsloth/2026.9.4/json) and
[2026.9.7](https://pypi.org/pypi/unsloth/2026.9.7/json) both require
`transformers<=5.5.0` / `trl<=0.24.0` / `datasets<4.4`, incompatible with this
kit's `transformers==5.17.0` / `trl==1.13.0` / `datasets==5.0.1`.
This is a confirmed resolver failure, not a platform-specific warning.
Installing Unsloth alone abandons the patched pins and is not a supported
workaround. `finetune_qwen38.py` requires Unsloth's `FastModel` and GGUF APIs;
there is no separate Transformers-only training path in this kit.

<hr>


Deep dive for later maybe: 

CyClaw-specific revision for your Apple Silicon MLX → Ollama LoRA workflow.

## CyClaw LoRA → Ollama

For your CyClaw setup, think of the LoRA as a small behavioral upgrade trained against your local MLX base model. It can teach the model your agent conventions, RAG behavior, output style, or domain-specific patterns—but Ollama cannot generally load that **MLX adapter** alongside its base model at runtime.

You must first fuse the adapter into the exact MLX base checkpoint that trained it. After that, you have a standalone fine-tuned model that can either stay in MLX or be deployed through Ollama.[1]

```text
MLX base + MLX LoRA adapter
          │
          ├─ Dynamic adapter inference in MLX
          │    Best reference/testing path
          │
          └─ mlx_lm.fuse
                │
                ├─ Direct Ollama Safetensors import, if compatible
                └─ Or convert to GGUF for Ollama/llama.cpp deployment
```

For your MacBook Pro M5 with 48 GB unified memory, the sensible approach is:

- Keep the adapter and fused MLX model as your **source-of-truth artifacts**.
- Validate the fused model in MLX before introducing Ollama or GGUF.
- Prefer direct Ollama import of the fused model directory if Ollama accepts it.
- Use GGUF when you need a known llama.cpp/Ollama deployment format or want a smaller quantized artifact.
- Start evaluation at F16, Q8, Q6_K, or Q5_K_M; use Q4_K_M only after testing that CyClaw’s tool calls, JSON, and agent behavior remain reliable.

## Fuse it

Always use the **identical MLX base** used during LoRA training—not an Ollama pull, not a similar Qwen release, and not a different quantization.

```bash
mlx_lm.fuse \
  --model /path/to/exact-mlx-training-base \
  --adapter-path /path/to/cyclaw-adapter \
  --save-path ./cyclaw-fused \
  --dequantize
```

`--dequantize` matters when your training base is MLX 4-bit/QLoRA. It materializes the quantized base weights before applying the LoRA delta, producing a more portable fused checkpoint.[1]

Before doing anything else, compare the dynamic-adapter and fused outputs with the same CyClaw-style prompt:

```bash
# Dynamic MLX adapter: reference behavior
mlx_lm.generate \
  --model /path/to/exact-mlx-training-base \
  --adapter-path /path/to/cyclaw-adapter \
  --prompt "Return a valid CyClaw tool-routing response for..." \
  --temp 0

# Fused MLX model: verifies fusion
mlx_lm.generate \
  --model ./cyclaw-fused \
  --prompt "Return a valid CyClaw tool-routing response for..." \
  --temp 0
```

If fused MLX is materially worse than adapter-loaded MLX, stop. That is a fuse/base/adapter compatibility problem—not an Ollama problem.

## Deploy with Ollama

First, try direct import of the fused directory. Current Ollama can import supported Safetensors model directories, so GGUF may be optional.

```text
# Modelfile
FROM /absolute/path/to/cyclaw-fused

PARAMETER temperature 0
PARAMETER num_ctx 16384
```

```bash
ollama create cyclaw-fused:fp -f Modelfile
ollama run cyclaw-fused:fp "Run a representative CyClaw prompt."
```

If Ollama rejects the fused directory, convert it to GGUF:

```bash
python3 convert_hf_to_gguf.py ./cyclaw-fused \
  --outfile ./cyclaw-fused-f16.gguf \
  --outtype f16
```

Test that F16 GGUF first:

```text
# Modelfile
FROM ./cyclaw-fused-f16.gguf

PARAMETER temperature 0
PARAMETER num_ctx 16384
```

Then, only if memory or throughput calls for it, quantize:

```bash
llama-quantize \
  ./cyclaw-fused-f16.gguf \
  ./cyclaw-fused-q5_k_m.gguf \
  Q5_K_M
```

```text
# Modelfile
FROM ./cyclaw-fused-q5_k_m.gguf

PARAMETER temperature 0
PARAMETER num_ctx 16384
```

## What to test

Do not judge this by generic chat quality. For CyClaw, test the things that actually break an agent:

- Correct tool-selection decisions.
- Valid JSON or structured output.
- Required fields, enums, and schemas.
- RAG grounding behavior.
- Refusal/safety behavior, if that is part of the LoRA.
- Multi-step task completion and instruction retention.

Run the same fixed evaluation prompts through:

1. MLX base + dynamic adapter.
2. Fused MLX model.
3. Ollama F16/Safetensors import.
4. Ollama Q5/Q4 GGUF.

Use `temperature 0`, identical prompts, and ideally a schema validator or automated eval harness. A quantized model may look “basically fine” in chat while quietly producing malformed tool arguments or choosing the wrong action.

## Bottom line

For CyClaw, **MLX dynamic-adapter inference is the clean reference path**. Fused MLX is the first deployment artifact to validate. Ollama is a deployment choice—not a required step—and GGUF is only needed when direct Safetensors import does not work or when you deliberately want a llama.cpp-compatible, quantized model.

The safe pipeline is:

```text
Train LoRA in MLX
→ verify dynamic adapter
→ fuse into the exact MLX base
→ verify fused MLX
→ try direct Ollama import
→ convert to F16 GGUF only if needed
→ quantize only after F16 passes CyClaw evaluation
```

That preserves a debuggable, high-fidelity baseline while still giving you an Ollama-native artifact for the CyClaw runtime.

<hr>

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
| `requirements.txt` | Optional operator pins — direct packages only (`unsloth`/`transformers`/`trl`/`datasets`/`accelerate`). Currently blocked by incompatible upstream ranges. Not part of the CyClaw runtime install; not an OSV lockfile. |
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
Apple Silicon has an integrated GPU, but this training script targets
NVIDIA CUDA; the local Mac is not a compatible training host.

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

# STOP: the current training requirements do not resolve.
# Continue only after a compatible CUDA profile is verified.
```

Once that blocker is resolved and the training dependencies are installed on
a CUDA host with >=24 GB VRAM, the script/deployment sequence is:

```bash
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
3. Resolve the blocked training dependency profile before provisioning a GPU
   pod or running `finetune_qwen38.py` for real.

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
