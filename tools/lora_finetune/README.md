# CyClaw Qwen3.8-27B LoRA fine-tune kit

This directory is an optional operator toolkit for training a CyClaw-specific
QLoRA adapter with Unsloth on NVIDIA CUDA. CyClaw does not import it, and the
runtime, Docker, Conda, and `full` install profiles do not install its
dependencies.

**The CUDA training profile is blocked.** The direct pins in
`requirements.txt` do not resolve together. Unsloth `2026.9.4` constrains
Transformers, TRL, and Datasets below the patched versions that this kit pins.
Do not bypass the resolver with `--no-deps` or an Unsloth-only install. Keep the
patched pins until a compatible CUDA profile has been verified.

Dataset generation, the mocked test suite, and the end-to-end dry run remain
usable without Unsloth, CUDA, or a GPU. CI runs those checks in
`.github/workflows/lora-finetune.yml`.

## What the kit contains

| Path | Purpose |
|---|---|
| `cyclaw_training.json` | Canonical 70-example dataset. Each row has `id`, `category`, `messages`, and `source_refs`. |
| `curated_qa.py` | The original 36 instruction, input, and output pairs. |
| `cyclaw_debug_qa.py` | Twelve structured debugging examples. |
| `curated_qa_extra.py` | Twenty-two expansion examples. |
| `build_cyclaw_corpus.py` | Rebuilds `cyclaw_training.json` and the generated `cyclaw_training.jsonl` preview. |
| `finetune_qwen38.py` | Unsloth QLoRA training and merged GGUF export. |
| `dryrun_finetune.py` | Replaces Unsloth, TRL, and Datasets with fakes and exercises both training branches. |
| `requirements.txt` | Direct CUDA-toolkit pins. This is not a transitive lockfile or a CyClaw runtime profile. |
| `tests/` | Dataset, integration, hardening, and command-line regression tests. |
| `audit-report.md` | Historical findings that led to the revision pins and regression tests. |

The dataset has ten categories. It is a small behavioral seed for CyClaw's
answer shape, invariant discipline, and debugging cues. It is not a substitute
for retrieval over the repository, and it does not teach the full codebase.

`build_cyclaw_corpus.py` uses the Qwen tokenizer when Transformers and the
pinned tokenizer assets are available. Otherwise it writes a clearly labeled
ChatML fallback. The training script always renders the canonical messages with
the base model's real tokenizer before training.

## Verify the offline parts

Use Python 3.12 with the repository test dependencies already installed. From
this directory, run:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m pytest tests/ -q --tb=short
python dryrun_finetune.py
```

The offline flags prevent an installed Transformers package from fetching
tokenizer assets during tests. The root command `python -m pytest tests/` targets the main repository's
`tests/` directory. It does not collect this kit's tests. The dedicated LoRA
workflow runs the commands above with only pytest installed. It does not install
the blocked training profile.

To regenerate the canonical dataset and JSONL preview:

```bash
python build_cyclaw_corpus.py
```

Review both generated files before committing them. A fallback-rendered JSONL
is a preview, not the final text that `finetune_qwen38.py` sends to the trainer.

## Training remains blocked

The current direct profile is:

```text
unsloth==2026.9.4
transformers==5.17.0
trl==1.13.0
datasets==5.0.1
accelerate==1.15.0
```

The conflict is deliberate. The patched Transformers and Datasets floors must
not be lowered merely to make the resolver succeed. `requirements.txt` records
the specific upstream constraints and vulnerability rationale that established
this block.

OSV-Scanner excludes `tools/lora_finetune` from the repository-wide dependency
walk because this optional file is neither installed nor a lockfile. After a
compatible CUDA profile is established and installed on its target host, audit
that environment from the repository root with:

```bash
pip-audit -r tools/lora_finetune/requirements.txt
```

Do not run the training command until the profile resolves normally and the
installed dependency set passes that audit.

## Run on a verified CUDA host

After the dependency block is resolved, run from this directory. Model and
tokenizer loading can download Hugging Face assets; seed their caches first
if training must run without network access:

```bash
python finetune_qwen38.py --json cyclaw_training.json
```

The script loads the configured 4-bit base through Unsloth `FastModel`, applies
language, attention, and MLP adapters, trains with TRL, saves the adapter, and
exports a merged Q4_K_M GGUF unless `--no-export-gguf` is set. It writes the
Ollama `Modelfile.cyclaw` beside the GGUF so its relative `FROM` path resolves.

Load the exported artifact only after training and held-out evaluation pass:

```bash
cd outputs_qwen38/gguf
ollama create cyclaw-qwen -f Modelfile.cyclaw
ollama run cyclaw-qwen
```

The generated Modelfile sets `num_ctx 32768`, which matches CyClaw's shipped
local context profile. The export is a new model artifact. It does not modify
the model named in `config.yaml` until the operator explicitly changes that
configuration.

### Command-line options

| Flag | Default | Effect |
|---|---|---|
| `--json` | `cyclaw_training.json` | Canonical dataset path. |
| `--model-name` | `unsloth/Qwen3.8-27B-unsloth-bnb-4bit` | Base checkpoint. Verify its exact lineage before training. |
| `--max-seq-length` | `2048` | Sequence length passed to `FastModel` and `SFTConfig`. |
| `--epochs` | `3` | Epoch count when `--max-steps` is zero. |
| `--max-steps` | `0` | Positive values replace the epoch schedule with a step cap. |
| `--batch-size` | `1` | Per-device batch size. |
| `--grad-accum` | `4` | Gradient accumulation steps. |
| `--lora-rank` | `16` | Adapter rank. |
| `--lora-alpha` | `16` | Adapter alpha. |
| `--learning-rate` | `2e-4` | Trainer learning rate. |
| `--offload-embedding` / `--no-offload-embedding` | on | Toggle Unsloth embedding offload. |
| `--output-dir` | `outputs_qwen38` | Adapter and merged-model output directory. |
| `--export-gguf` / `--no-export-gguf` | on | Toggle merged GGUF and Modelfile export. |

Treat those values as script defaults, not proven optimal hyperparameters.
This repository has no real GPU training result, quality benchmark, or resource
measurement that establishes an optimal rank, batch size, step count, memory
floor, or wall-clock time.

## Evaluate the artifact

Use held-out prompts that exercise CyClaw's actual failure modes:

- invariant and route selection;
- valid JSON and required fields;
- retrieval-grounded answers;
- refusal and soul-governance behavior;
- debugging questions absent from the training set.

Compare the untouched base model, the adapter-loaded model, and the merged GGUF
with identical prompts and deterministic sampling. Training loss and answers to
the 70 training examples do not establish generalization.

The default Hugging Face checkpoint and CyClaw's shipped Ollama tag must not be
assumed to share an adapter-compatible base. Loading a LoRA adapter on a
different base can produce invalid results even when both names mention Qwen
3.8 and 27B. The script avoids that deployment ambiguity by exporting a full
merged GGUF.

## Apple Silicon is a separate path

The checked-in training script targets Unsloth and NVIDIA CUDA. It does not run
on Apple Silicon. MLX-LM can support LoRA or QLoRA on compatible MLX models, but
this repository contains no MLX training, fusion, conversion, or evaluation
implementation. Treat an MLX workflow as separate engineering work. Keep its
base model, adapter, and fusion lineage together, and verify any converted
Ollama artifact before changing CyClaw's configured model.
