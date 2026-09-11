# Integration tests for finetune_qwen38.py.
# Run:  cd cyclaw-finetune && python3 -m pytest tests/ -q
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))


# ── Fakes ──────────────────────────────────────────────────────────────────
class _FakeTokenizer:
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
        (Path(gguf_dir) / "model.q4_k_m.gguf").write_bytes(b"FAKE_GGUF_BYTES")


class _FakeFastModel:
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
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _FakeSFTTrainer:
    instances: list[_FakeSFTTrainer] = []
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
    def __init__(self, rows):
        self.rows = rows
    def __len__(self):
        return len(self.rows)


@pytest.fixture
def fakes_installed(tmp_path, monkeypatch):
    """Install mock unsloth/trl/datasets; reset call recorders each test."""
    _FakeSFTTrainer.instances.clear()
    _FakeFastModel.last_from_pretrained = None
    _FakeFastModel.last_get_peft_model = None

    fake_unsloth = types.ModuleType("unsloth")
    fake_unsloth.FastModel = _FakeFastModel
    fake_unsloth.__version__ = "0.1.800"
    fake_trl = types.ModuleType("trl")
    fake_trl.SFTTrainer = _FakeSFTTrainer
    fake_trl.SFTConfig = _FakeSFTConfig
    fake_datasets = types.ModuleType("datasets")

    rows: list = []
    def _load_dataset(name, data_files, split):
        assert name == "json" and split == "train"
        with open(data_files, encoding="utf-8") as f:
            rows[:] = [json.loads(line) for line in f]
        return _FakeDataset(list(rows))
    fake_datasets.load_dataset = _load_dataset

    for mod in ("unsloth", "trl", "datasets"):
        monkeypatch.delitem(sys.modules, mod, raising=False)
        monkeypatch.setitem(sys.modules, mod, {
            "unsloth": fake_unsloth, "trl": fake_trl, "datasets": fake_datasets
        }[mod])
    return rows


@pytest.fixture
def ft_module(fakes_installed):
    """Import finetune_qwen38 with fakes already installed."""
    import importlib
    import finetune_qwen38 as ft  # type: ignore[import]
    importlib.reload(ft)
    return ft


# ── Fixtures for the dataset path ──────────────────────────────────────────
@pytest.fixture(scope="module")
def dataset_json():
    return str(HERE / "cyclaw_training.json")


# ── Tests ─────────────────────────────────────────────────────────────────
class TestModelLoad:
    def test_from_pretrained_uses_verified_api_args(self, ft_module, dataset_json, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "argv", [
            "finetune_qwen38.py", "--json", dataset_json,
            "--max-seq-length", "2048", "--max-steps", "5",
            "--output-dir", str(tmp_path / "out"),
        ])
        ft_module.main()
        fp = _FakeFastModel.last_from_pretrained
        assert fp["model_name"] == "unsloth/Qwen3.8-27B-unsloth-bnb-4bit", fp
        assert fp["load_in_4bit"] is True and fp["full_finetuning"] is False
        assert fp["offload_embedding"] is True
        assert fp["max_seq_length"] == 2048

    def test_get_peft_model_uses_boolean_flags(self, ft_module, dataset_json, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "argv", [
            "finetune_qwen38.py", "--json", dataset_json,
            "--max-steps", "5", "--lora-rank", "32", "--lora-alpha", "32",
            "--output-dir", str(tmp_path / "out"),
        ])
        ft_module.main()
        peft = _FakeFastModel.last_get_peft_model
        assert peft["vision"] is False and peft["language"] is True
        assert peft["attention"] is True and peft["mlp"] is True
        assert peft["r"] == 32 and peft["alpha"] == 32
        assert "target_modules" not in peft


class TestDatasetAndRendering:
    def test_all_seventy_render_non_empty(self, ft_module, dataset_json, tmp_path, monkeypatch, fakes_installed):
        monkeypatch.setattr(sys, "argv", [
            "finetune_qwen38.py", "--json", dataset_json,
            "--max-steps", "5", "--output-dir", str(tmp_path / "out"),
        ])
        ft_module.main()
        assert len(fakes_installed) == 70
        empty = [i for i, r in enumerate(fakes_installed) if not r["text"].strip()]
        assert not empty
        assert all("<|im_start|>" in r["text"] for r in fakes_installed)


class TestSFTConfig:
    def test_max_steps_branch(self, ft_module, dataset_json, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "argv", [
            "finetune_qwen38.py", "--json", dataset_json,
            "--max-steps", "5", "--batch-size", "2", "--grad-accum", "2",
            "--output-dir", str(tmp_path / "out"),
        ])
        ft_module.main()
        cfg = _FakeSFTTrainer.instances[-1].args
        assert cfg.max_steps == 5 and cfg.num_train_epochs is None
        assert cfg.per_device_train_batch_size == 2
        assert cfg.gradient_accumulation_steps == 2
        assert cfg.dataset_text_field == "text"
        assert cfg.optim == "adamw_8bit" and cfg.report_to == "none"

    def test_epochs_branch(self, ft_module, dataset_json, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "argv", [
            "finetune_qwen38.py", "--json", dataset_json,
            "--max-steps", "0", "--epochs", "3",
            "--output-dir", str(tmp_path / "out"), "--no-export-gguf",
        ])
        ft_module.main()
        cfg = _FakeSFTTrainer.instances[-1].args
        assert cfg.max_steps == -1 and cfg.num_train_epochs == 3


class TestOllamaOutput:
    def test_modelfile_inside_gguf_dir(self, ft_module, dataset_json, tmp_path, monkeypatch):
        out = tmp_path / "out"
        monkeypatch.setattr(sys, "argv", [
            "finetune_qwen38.py", "--json", dataset_json,
            "--max-steps", "5", "--output-dir", str(out),
        ])
        ft_module.main()
        gguf_dir = out / "gguf"
        assert (gguf_dir / "Modelfile.cyclaw").exists()
        mf = (gguf_dir / "Modelfile.cyclaw").read_text(encoding="utf-8")
        assert "FROM ./model.q4_k_m.gguf" in mf
        assert "PARAMETER num_ctx 32768" in mf
        assert (gguf_dir / "model.q4_k_m.gguf").exists()

    def test_no_gguf_flag_skips_modelfile(self, ft_module, dataset_json, tmp_path, monkeypatch):
        out = tmp_path / "out"
        monkeypatch.setattr(sys, "argv", [
            "finetune_qwen38.py", "--json", dataset_json,
            "--max-steps", "5", "--output-dir", str(out), "--no-export-gguf",
        ])
        ft_module.main()
        assert not (out / "gguf").exists()


class TestTrainerInvoked:
    def test_train_called_once(self, ft_module, dataset_json, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "argv", [
            "finetune_qwen38.py", "--json", dataset_json,
            "--max-steps", "5", "--output-dir", str(tmp_path / "out"),
        ])
        ft_module.main()
        trained = [t for t in _FakeSFTTrainer.instances if t.trained]
        assert len(trained) == 1
