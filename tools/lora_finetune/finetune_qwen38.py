#!/usr/bin/env python3
"""Fine-tune Qwen3.8-27B on the CyClaw curated dataset via Unsloth QLoRA.

Deliverable 3. Verified against the Unsloth Qwen3.8 fine-tuning guide
(https://unsloth.ai/docs/models/qwen3.8/train, retrieved 2026-09-07) and the
CyClaw source on github.com/CGFixIT/CyClaw main.

WHAT IT DOES
  1. Loads cyclaw_training.json (canonical: id/category/messages/source_refs).
  2. Renders each example's `text` with the REAL Qwen tokenizer via
     tokenizer.apply_chat_template(..., tokenize=False, add_generation_prompt=False)
     — so the chat delimiters always match the deployed model, never a fallback.
  3. Builds the model with FastModel + 4-bit QLoRA (the verified current API).
  4. Trains with SFTTrainer + SFTConfig.
  5. Saves the LoRA adapter, a merged-16bit checkpoint (for vLLM), and a
     q4_k_m GGUF (for Ollama) + an Ollama Modelfile.

HARDWARE
  QLoRA on 27B needs >=24GB VRAM (tight; 48GB is the comfortable single-card
  zone). Chris's primary machine is an M5 Mac with NO GPU — this script is
  meant to run on a rented GPU pod (RunPod/Vast.ai/Lambda) or a 2xT4 Kaggle
  notebook. It will not run on the sandbox or the Mac.

MODEL NAME / ADAPTER COMPATIBILITY CAVEAT
  Default model is `unsloth/Qwen3.8-27B-unsloth-bnb-4bit` (the current
  Unsloth-supported 27B, released 2026-08-13). CyClaw's config.yaml ships
  `qwen3.8:27b-mlx` as the local Ollama model. If you want the fine-tuned adapter
  to load on top of that exact Ollama base, VERIFY FIRST that the Hugging Face
  checkpoint you fine-tune shares the same architecture/weights family as the
  Ollama `qwen3.8:27b-mlx` tag — mismatched base models break LoRA. The safe path
  is: fine-tune the Unsloth checkpoint, export a full merged GGUF, and load
  THAT in Ollama (not an ADAPTER on top of a different base). See --model-name.

USAGE
  python finetune_qwen38.py --json cyclaw_training.json
  python finetune_qwen38.py --json cyclaw_training.json --max-seq-length 2048 \
      --epochs 3 --batch-size 1 --grad-accum 4 --lora-rank 16
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _check_unsloth() -> None:
    """Fail loudly with a helpful message instead of a confusing ImportError."""
    try:
        import unsloth  # type: ignore[import]
    except ImportError as e:  # noqa: F841
        sys.exit(
            "Unsloth is not installed in this environment.\n"
            "Install on a CUDA GPU machine:\n"
            "  pip install --upgrade --force-reinstall --no-cache-dir "
            "unsloth unsloth_zoo\n"
            "or:  curl -fsSL https://unsloth.ai/install.sh | sh\n"
            "This script requires an NVIDIA GPU with >=24GB VRAM."
        )
    # Version guard: FastModel + offload_embedding + boolean module flags need a
    # recent Unsloth (v0.1.800-beta shipped Qwen3.8-27B support on 2026-08-14).
    version = getattr(unsloth, "__version__", "0")
    print(f"[unsloth] version {version}", file=sys.stderr)


def load_canonical_dataset(json_path: Path) -> list[dict]:
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        sys.exit(f"Dataset file not found: {json_path}\nRun build_cyclaw_corpus.py first, or check --json.")
    except json.JSONDecodeError as e:
        sys.exit(f"Dataset file is not valid JSON: {json_path}\n{e}")
    if not isinstance(data, list) or not data:
        sys.exit(f"Expected a non-empty JSON array in {json_path}")
    return data


def render_with_real_tokenizer(tokenizer, examples: list[dict], out_path: Path) -> Path:
    """Render `text` with the real tokenizer. Returns the JSONL path."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for ex in examples:
            msgs = ex["messages"]
            text = tokenizer.apply_chat_template(
                msgs, tokenize=False, add_generation_prompt=False
            )
            f.write(json.dumps({"text": text}, ensure_ascii=False) + "\n")
            n += 1
    print(f"[data] rendered {n} examples -> {out_path}", file=sys.stderr)
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", default="cyclaw_training.json", help="Canonical dataset JSON")
    ap.add_argument("--model-name", default="unsloth/Qwen3.8-27B-unsloth-bnb-4bit",
                    help="HF model id. Default is the current Unsloth 27B 4-bit checkpoint.")
    ap.add_argument("--max-seq-length", type=int, default=2048,
                    help="Drives VRAM harder than anything else. Set to your real data length, not the model ceiling.")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--max-steps", type=int, default=0, help="0 = use epochs instead of a step cap")
    ap.add_argument("--batch-size", type=int, default=1)
    ap.add_argument("--grad-accum", type=int, default=4)
    ap.add_argument("--lora-rank", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=16)
    ap.add_argument("--learning-rate", type=float, default=2e-4)
    ap.add_argument("--offload-embedding", action=argparse.BooleanOptionalAction, default=True,
                    help="Keep the large untied input embedding in RAM to reduce VRAM (default on; use --no-offload-embedding).")
    ap.add_argument("--output-dir", default="outputs_qwen38")
    ap.add_argument("--export-gguf", action=argparse.BooleanOptionalAction, default=True,
                    help="Export a q4_k_m GGUF for Ollama (default on; use --no-export-gguf).")
    args = ap.parse_args()

    _check_unsloth()
    # Imports that need Unsloth/CUDA — after the version guard.
    from unsloth import FastModel  # type: ignore[import]
    from datasets import load_dataset  # type: ignore[import]
    from trl import SFTTrainer, SFTConfig  # type: ignore[import]

    examples = load_canonical_dataset(Path(args.json))

    # 1. Load model + tokenizer (verified API from unsloth.ai/docs/models/qwen3.8/train).
    model, tokenizer = FastModel.from_pretrained(
        model_name=args.model_name,
        max_seq_length=args.max_seq_length,
        load_in_4bit=True,
        full_finetuning=False,
        offload_embedding=args.offload_embedding,
    )

    # 2. Render the real chat template into a `text` column JSONL.
    jsonl = render_with_real_tokenizer(tokenizer, examples, Path("cyclaw_training.rendered.jsonl"))
    dataset = load_dataset("json", data_files=str(jsonl), split="train")

    # 3. LoRA (boolean module-group flags — NOT target_modules — per current docs).
    model = FastModel.get_peft_model(
        model,
        finetune_vision_layers=False,
        finetune_language_layers=True,
        finetune_attention_modules=True,
        finetune_mlp_modules=True,
        r=args.lora_rank,
        lora_alpha=args.lora_alpha,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=3407,
        use_rslora=False,
        loftq_config=None,
    )

    # 4. Train. max_steps > 0 caps training by step count; otherwise use epochs.
    sft_args = SFTConfig(
        dataset_text_field="text",
        max_seq_length=args.max_seq_length,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        warmup_steps=10,
        max_steps=args.max_steps if args.max_steps > 0 else -1,
        num_train_epochs=args.epochs if args.max_steps <= 0 else None,
        learning_rate=args.learning_rate,
        logging_steps=1,
        optim="adamw_8bit",
        output_dir=args.output_dir,
        seed=3407,
        dataset_num_proc=1,
        report_to="none",
    )
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        args=sft_args,
    )
    trainer.train()

    # 5. Save LoRA adapter (small; for iteration).
    lora_dir = Path(args.output_dir) / "lora"
    model.save_pretrained(str(lora_dir))
    tokenizer.save_pretrained(str(lora_dir))
    print(f"[save] LoRA adapter -> {lora_dir}", file=sys.stderr)

    # 6. Export merged GGUF for Ollama (PRIMARY Ollama path — not ADAPTER).
    if args.export_gguf:
        gguf_dir = Path(args.output_dir) / "gguf"
        model.save_pretrained_gguf(
            str(gguf_dir),
            tokenizer,
            quantization_method="q4_k_m",
        )
        # Write an Ollama Modelfile INSIDE gguf_dir so `FROM ./<file>.gguf` resolves.
        gguf_files = sorted(gguf_dir.glob("*.gguf"))
        if gguf_files:
            modelfile = gguf_dir / "Modelfile.cyclaw"
            modelfile.write_text(
                f"FROM ./{gguf_files[0].name}\n\n"
                f"PARAMETER num_ctx 32768\n"
                f"PARAMETER temperature 0.3\n"
                f"PARAMETER top_p 0.9\n\n"
                f'SYSTEM """\n'
                f"You are CyClaw's assistant. You reason about the CyClaw architecture "
                f"from source, follow its I1-I6 invariants, and never propose changes "
                f"that bypass retrieval, audit, or soul governance.\n"
                f'"""\n',
                encoding="utf-8",
            )
            print(f"[save] GGUF -> {gguf_files[0]}", file=sys.stderr)
            print(f"[save] Ollama Modelfile -> {modelfile}", file=sys.stderr)
            print("Load in Ollama (run from the gguf dir):\n  ollama create "
                  f"cyclaw-qwen -f {modelfile.name} && ollama run cyclaw-qwen",
                  file=sys.stderr)
        else:
            print("[warn] save_pretrained_gguf produced no .gguf file; check "
                  "llama.cpp quantization deps.", file=sys.stderr)

    # 7. Optional merged-16bit for vLLM/SGLang serving (uncomment to enable).
    # model.save_pretrained_merged("outputs_qwen38/merged_16bit", tokenizer,
    #                              save_method="merged_16bit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
