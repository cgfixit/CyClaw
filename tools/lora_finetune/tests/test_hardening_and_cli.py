# Regression tests for the LoRA kit's hardening (revision-pinned tokenizer
# loads) and finetune_qwen38.py's CLI error paths, plus a couple of
# repo-hygiene checks (.gitignore) that the existing unit/integration suites
# do not cover. See tools/lora_finetune/audit-report.md for the finding this
# closes (build_cyclaw_corpus.py:131, AutoTokenizer.from_pretrained without
# revision pinning).
# Run:  cd tools/lora_finetune && python3 -m pytest tests/ -q
from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import build_cyclaw_corpus as bcc  # type: ignore[import]  # noqa: E402


# ── Revision pinning (hardened.diff / audit-report.md) ──────────────────────
class _RecordingTokenizer:
    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=False):
        return "<|im_start|>ok<|im_end|>"


class TestRevisionPinning:
    def test_from_pretrained_called_with_pinned_sha(self, monkeypatch):
        """Every AutoTokenizer.from_pretrained call must pass a 40-char hex
        revision, never the mutable "main" branch — see audit-report.md's
        top must-fix finding and hardened.diff."""
        calls: list[dict] = []

        class _FakeAutoTokenizer:
            @staticmethod
            def from_pretrained(name, revision=None):
                calls.append({"name": name, "revision": revision})
                return _RecordingTokenizer()

        fake_transformers = types.ModuleType("transformers")
        fake_transformers.AutoTokenizer = _FakeAutoTokenizer
        monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

        result = bcc._try_apply_chat_template(
            [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        )

        assert result == "<|im_start|>ok<|im_end|>"
        assert calls, "AutoTokenizer.from_pretrained was never called"
        for call in calls:
            assert call["revision"] is not None, call
            assert call["revision"] != "main", "revision must be a pinned commit SHA, not a branch"
            assert len(call["revision"]) == 40, f"expected a 40-char commit SHA, got {call['revision']!r}"
            int(call["revision"], 16)  # must be valid hex

    def test_falls_back_to_second_repo_on_first_failure(self, monkeypatch):
        """If the first pinned repo/revision is unreachable, the second
        candidate is tried before falling back to the ChatML renderer."""
        attempted: list[str] = []

        class _FlakyAutoTokenizer:
            @staticmethod
            def from_pretrained(name, revision=None):
                attempted.append(name)
                if name == "Qwen/Qwen2.5-0.5B":
                    raise OSError("simulated network failure")
                return _RecordingTokenizer()

        fake_transformers = types.ModuleType("transformers")
        fake_transformers.AutoTokenizer = _FlakyAutoTokenizer
        monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

        result = bcc._try_apply_chat_template([{"role": "user", "content": "hi"}])

        assert result == "<|im_start|>ok<|im_end|>"
        assert attempted == ["Qwen/Qwen2.5-0.5B", "Qwen/Qwen2-0.5B"]

    def test_returns_none_when_transformers_not_installed(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "transformers", None)
        assert bcc._try_apply_chat_template([{"role": "user", "content": "hi"}]) is None


# ── finetune_qwen38.py CLI error paths ───────────────────────────────────────
@pytest.fixture
def ft_module_no_unsloth(monkeypatch):
    """Import finetune_qwen38 without touching sys.modules for unsloth/trl/
    datasets — only load_canonical_dataset/_check_unsloth are exercised, and
    neither needs those heavy imports to be present."""
    import finetune_qwen38 as ft  # type: ignore[import]
    importlib.reload(ft)
    return ft


class TestLoadCanonicalDatasetErrors:
    def test_missing_file_exits_with_friendly_message(self, ft_module_no_unsloth, tmp_path):
        missing = tmp_path / "does_not_exist.json"
        with pytest.raises(SystemExit) as exc:
            ft_module_no_unsloth.load_canonical_dataset(missing)
        assert "not found" in str(exc.value)
        assert str(missing) in str(exc.value)

    def test_malformed_json_exits_with_friendly_message(self, ft_module_no_unsloth, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            ft_module_no_unsloth.load_canonical_dataset(bad)
        assert "not valid JSON" in str(exc.value)

    def test_empty_list_exits(self, ft_module_no_unsloth, tmp_path):
        empty = tmp_path / "empty.json"
        empty.write_text("[]", encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            ft_module_no_unsloth.load_canonical_dataset(empty)
        assert "non-empty JSON array" in str(exc.value)

    def test_non_list_json_exits(self, ft_module_no_unsloth, tmp_path):
        obj = tmp_path / "obj.json"
        obj.write_text('{"id": 1}', encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            ft_module_no_unsloth.load_canonical_dataset(obj)
        assert "non-empty JSON array" in str(exc.value)

    def test_valid_dataset_loads(self, ft_module_no_unsloth, tmp_path):
        data = [{"id": "x", "messages": []}]
        path = tmp_path / "ok.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        assert ft_module_no_unsloth.load_canonical_dataset(path) == data


class TestCheckUnsloth:
    def test_missing_unsloth_exits_with_install_instructions(self, ft_module_no_unsloth, monkeypatch):
        monkeypatch.setitem(sys.modules, "unsloth", None)
        with pytest.raises(SystemExit) as exc:
            ft_module_no_unsloth._check_unsloth()
        msg = str(exc.value)
        assert "not installed" in msg
        assert "pip install" in msg
        assert "unsloth" in msg

    def test_present_unsloth_does_not_exit(self, ft_module_no_unsloth, monkeypatch):
        fake_unsloth = types.ModuleType("unsloth")
        fake_unsloth.__version__ = "0.1.900"
        monkeypatch.setitem(sys.modules, "unsloth", fake_unsloth)
        ft_module_no_unsloth._check_unsloth()  # must not raise


# ── Repo hygiene: .gitignore must exclude real training output ─────────────
class TestGitignoreHygiene:
    def test_output_dir_and_gguf_artifacts_are_ignored(self):
        """finetune_qwen38.py's default --output-dir is outputs_qwen38/, and
        it writes multi-GB *.gguf checkpoints under it. Both must be excluded
        so a stray `git add -A` can't commit them."""
        gitignore = (HERE / ".gitignore").read_text(encoding="utf-8").splitlines()
        assert "outputs_qwen38/" in gitignore
        assert "*.gguf" in gitignore
        assert ".gguf" not in gitignore, "bare '.gguf' (no wildcard) does not match real *.gguf files"
