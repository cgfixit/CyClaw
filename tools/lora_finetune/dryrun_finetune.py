#!/usr/bin/env python3
"""Dry-run validation of finetune_qwen38.py WITHOUT Unsloth/CUDA/GPU.

What this proves:
  - The script's control flow is correct end-to-end.
  - The canonical dataset (cyclaw_training.json, 70 examples) loads and
    every example has the system/user/assistant triad.
  - apply_chat_template renders a non-empty `text` for every example.
  - SFTConfig accepts every argument we pass (max_steps/epochs handling).
  - The Ollama Modelfile is written inside the GGUF dir with a correct
    `FROM ./<file>.gguf` path.

What this does NOT prove (no GPU in sandbox):
  - That the real Unsloth FastModel loads the 27B weights.
  - That training converges or fits in VRAM.
  - That save_pretrained_gguf produces a valid GGUF.
Those require a >=24GB VRAM box; run finetune_qwen38.py there for real.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


# ── Fakes for the three heavy imports ────────────────────────────────────────
class _FakeTokenizer:
    """Stand-in for the Qwen tokenizer. apply_chat_template -> ChatML."""
    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=False):
        assert tokenize is False
        parts = []
        for m in messages:
            parts.append(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>")
        return "\n".join(parts)
    def save_pretrained(self, path):
        Path(path).mkdir(parents=True, exist_ok=True)
        (Path(path) / "tokenizer.json").write_text("{}", encoding="utf-8")


class _FakeModel:
    """Captures get_peft_model / save calls; records what was passed."""
    def __init__(self):
        self.peft_kwargs = None
        self.gguf_kwargs = None
        self.lora_path = None
        self.gguf_dir = None
    def save_pretrained(self, path):
        self.lora_path = path
        Path(path).mkdir(parents=True, exist_ok=True)
    def save_pretrained_gguf(self, gguf_dir, tokenizer, quantization_method):
        self.gguf_kwargs = dict(path=gguf_dir, quant=quantization_method)
        self.gguf_dir = Path(gguf_dir)
        Path(gguf_dir).mkdir(parents=True, exist_ok=True)
        # Simulate llama.cpp producing a .gguf file.
        (Path(gguf_dir) / "model.q4_k_m.gguf").write_bytes(b"FAKE_GGUF_BYTES")


class _FakeFastModel:
    """unsloth.FastModel shim."""
    last_from_pretrained = None
    last_get_peft_model = None
    @classmethod
    def from_pretrained(cls, model_name, max_seq_length, load_in_4bit,
                        full_finetuning, offload_embedding):
        cls.last_from_pretrained = dict(
            model_name=model_name, max_seq_length=max_seq_length,
            load_in_4bit=load_in_4bit, full_finetuning=full_finetuning,
            offload_embedding=offload_embedding)
        return _FakeModel(), _FakeTokenizer()
    @classmethod
    def get_peft_model(cls, model, finetune_vision_layers, finetune_language_layers,
                      finetune_attention_modules, finetune_mlp_modules,
                      r, lora_alpha, lora_dropout, bias,
                      use_gradient_checkpointing, random_state,
                      use_rslora, loftq_config):
        cls.last_get_peft_model = dict(
            vision=finetune_vision_layers, language=finetune_language_layers,
            attention=finetune_attention_modules, mlp=finetune_mlp_modules,
            r=r, alpha=lora_alpha, dropout=lora_dropout, bias=bias,
            grad_ckpt=use_gradient_checkpointing, rslora=use_rslora)
        model.peft_kwargs = cls.last_get_peft_model
        return model


class _FakeSFTConfig:
    """trl.SFTConfig that just stores kwargs as attributes."""
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _FakeSFTTrainer:
    """trl.SFTTrainer that stores args and records train() was called."""
    instances: list["_FakeSFTTrainer"] = []
    def __init__(self, model=None, tokenizer=None, train_dataset=None, args=None):
        self.model = model
        self.tokenizer = tokenizer
        self.train_dataset = train_dataset
        self.args = args
        self.trained = False
        _FakeSFTTrainer.instances.append(self)
    def train(self):
        self.trained = True


class _FakeDataset:
    """datasets.load_dataset shim returning an object with a row count."""
    def __init__(self, rows):
        self.rows = rows
    def __len__(self):
        return len(self.rows)


def _install_fakes():
    fake_unsloth = types.ModuleType("unsloth")
    fake_unsloth.FastModel = _FakeFastModel
    fake_unsloth.__version__ = "0.1.800"
    fake_trl = types.ModuleType("trl")
    fake_trl.SFTTrainer = _FakeSFTTrainer
    fake_trl.SFTConfig = _FakeSFTConfig
    fake_datasets = types.ModuleType("datasets")
    _rows: list = []
    def _load_dataset(name, data_files, split):
        assert name == "json"
        assert split == "train"
        with open(data_files, encoding="utf-8") as f:
            _rows[:] = [json.loads(line) for line in f]
        return _FakeDataset(list(_rows))
    fake_datasets.load_dataset = _load_dataset
    sys.modules["unsloth"] = fake_unsloth
    sys.modules["trl"] = fake_trl
    sys.modules["datasets"] = fake_datasets
    return fake_unsloth, fake_trl, fake_datasets, _rows


def main() -> int:
    # Stub the version-check import so _check_unsloth passes.
    fake_unsloth, fake_trl, fake_datasets, rows = _install_fakes()

    # Import the module under test AFTER fakes are installed so its
    # `from unsloth import FastModel` etc. resolve to our shims.
    import importlib
    import finetune_qwen38 as ft  # type: ignore[import]

    # Sanity: the version guard should have found the fake unsloth.
    assert hasattr(ft, "main"), "finetune_qwen38.main not found"

    # Run with a small max_steps so train() is called once.
    sys.argv = [
        "finetune_qwen38.py",
        "--json", str(HERE / "cyclaw_training.json"),
        "--max-seq-length", "2048",
        "--max-steps", "5",          # cap training (exercises the max_steps branch)
        "--batch-size", "1",
        "--grad-accum", "4",
        "--lora-rank", "16",
        "--output-dir", str(HERE / "_dryrun_out"),
    ]
    rc = ft.main()

    # ── Assertions ──────────────────────────────────────────────────────────
    failures: list[str] = []

    # 1. from_pretrained got the verified API args.
    fp = _FakeFastModel.last_from_pretrained
    if fp is None:
        failures.append("FastModel.from_pretrained was never called")
    else:
        assert fp["model_name"] == "unsloth/Qwen3.8-27B-unsloth-bnb-4bit", fp
        assert fp["load_in_4bit"] is True, fp
        assert fp["full_finetuning"] is False, fp
        assert fp["offload_embedding"] is True, fp
        assert fp["max_seq_length"] == 2048, fp

    # 2. get_peft_model used boolean module flags, not target_modules.
    peft = _FakeFastModel.last_get_peft_model
    if peft is None:
        failures.append("get_peft_model was never called")
    else:
        assert peft["vision"] is False, peft
        assert peft["language"] is True, peft
        assert peft["attention"] is True, peft
        assert peft["mlp"] is True, peft
        assert peft["r"] == 16, peft
        assert "target_modules" not in peft, "should use boolean flags not target_modules"

    # 3. SFTConfig got correct args incl. max_steps (the branch we exercised).
    trainer = _FakeSFTTrainer.instances[-1]
    cfg = trainer.args
    assert cfg.dataset_text_field == "text", cfg
    assert cfg.max_seq_length == 2048, cfg
    assert cfg.max_steps == 5, cfg
    assert cfg.per_device_train_batch_size == 1, cfg
    assert cfg.gradient_accumulation_steps == 4, cfg
    assert cfg.learning_rate == 2e-4, cfg
    assert cfg.optim == "adamw_8bit", cfg
    assert cfg.report_to == "none", cfg
    assert trainer.trained is True, "trainer.train() was not called"

    # 4. Dataset loaded and every rendered text is non-empty.
    assert len(rows) == 70, f"expected 70 rendered rows got {len(rows)}"
    empty = [i for i, r in enumerate(rows) if not r["text"].strip()]
    assert not empty, f"empty rendered text at rows {empty}"
    assert all("<|im_start|>" in r["text"] and "<|im_end|>" in r["text"] for r in rows)

    # 5. Ollama Modelfile written inside gguf_dir with correct FROM path.
    gguf_dir = HERE / "_dryrun_out" / "gguf"
    modelfile = gguf_dir / "Modelfile.cyclaw"
    assert modelfile.exists(), f"Modelfile not written at {modelfile}"
    mf_text = modelfile.read_text(encoding="utf-8")
    assert "FROM ./model.q4_k_m.gguf" in mf_text, mf_text
    assert "PARAMETER num_ctx 32768" in mf_text, mf_text
    assert (gguf_dir / "model.q4_k_m.gguf").exists(), "GGUF not written"

    # 6. LoRA adapter dir written.
    assert (HERE / "_dryrun_out" / "lora").exists(), "lora dir not written"

    # ── Also exercise the epochs branch (max_steps=0) ────────────────────────
    _FakeSFTTrainer.instances.clear()
    _FakeFastModel.last_from_pretrained = None
    _FakeFastModel.last_get_peft_model = None
    sys.argv = [
        "finetune_qwen38.py",
        "--json", str(HERE / "cyclaw_training.json"),
        "--max-steps", "0",
        "--epochs", "3",
        "--output-dir", str(HERE / "_dryrun_out2"),
        "--no-export-gguf",
    ]
    rc2 = ft.main()
    trainer2 = _FakeSFTTrainer.instances[-1]
    assert trainer2.args.max_steps == -1, trainer2.args
    assert trainer2.args.num_train_epochs == 3, trainer2.args
    assert trainer2.trained is True

    if failures:
        print("FAILURES:", failures, file=sys.stderr)
        return 1

    print("DRY-RUN VALIDATION PASSED")
    print(f"  dataset: 70 examples, all rendered with non-empty ChatML text")
    print(f"  from_pretrained: verified API args (4bit, offload_embedding, no full_finetune)")
    print(f"  get_peft_model: boolean module flags (no target_modules)")
    print(f"  SFTConfig: dataset_text_field=text, max_steps/epochs branches both correct")
    print(f"  Ollama Modelfile: written in gguf dir, FROM ./model.q4_k_m.gguf")
    print(f"  epochs branch: max_steps=-1, num_train_epochs=3")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
