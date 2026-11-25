# Integration tests for finetune_qwen38.py.
# Run:  cd cyclaw-finetune && python3 -m pytest tests/ -q
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))


# ── Fakes ──────────────────────────────────────────────────────────────────
# One copy, shared with dryrun_finetune.py: two copies of the Unsloth/TRL fakes
# could drift, and a fake that misses a new keyword gives a wrong verdict
# (#1853). Importing it is side-effect free: dryrun_finetune installs its
# fakes into sys.modules only inside _install_fakes(), never at import.
from dryrun_finetune import (  # noqa: E402
    _build_fake_modules,
    _FakeFastModel,
    _FakeSFTTrainer,
)


@pytest.fixture
def fakes_installed(tmp_path, monkeypatch):
    """Install mock unsloth/trl/datasets; reset call recorders each test."""
    _FakeSFTTrainer.instances.clear()
    _FakeFastModel.last_from_pretrained = None
    _FakeFastModel.last_get_peft_model = None

    fake_unsloth, fake_trl, fake_datasets, rows = _build_fake_modules()
    for mod, fake in (("unsloth", fake_unsloth), ("trl", fake_trl), ("datasets", fake_datasets)):
        monkeypatch.delitem(sys.modules, mod, raising=False)
        monkeypatch.setitem(sys.modules, mod, fake)
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
