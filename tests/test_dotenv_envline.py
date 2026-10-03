"""Lock the dotenv-guard env-line tokenizer to envline_vectors.tsv.

The vectors file is the shared table a shell loader can reimplement.
This module does not start a service and does not import gate.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
_SKILL = _REPO / ".claude" / "skills" / "dotenv-guard"
_ENVLINE_PATH = _SKILL / "envline.py"
_VECTORS = _SKILL / "envline_vectors.tsv"
_BASELINE = _SKILL / "baseline.txt"

# K4/K5 rows owned by draft #1507. A later edit may add lines; these must stay.
_K4_K5_BASELINE = (
    "K4\t~/.CyClaw/.env:CYCLAW_API_KEY\tmain: setup-cyclaw-keys.sh writes secrets to ~/.CyClaw/.env (mode 600) by default. Open draft #1507 proposes Keychain-only storage; delete if it lands.",
    "K4\t~/.CyClaw/.env:GROK_API_KEY\tmain: same default write (--grok-dummy exercises it). Open draft #1507 proposes Keychain-only storage; delete if it lands.",
    "K4\t<checkout>/.env:CYCLAW_API_KEY\tmain: --repo-path writes a sibling checkout .env with secrets. Open draft #1507 proposes not writing it; delete if it lands.",
    "K4\t<checkout>/.env:GROK_API_KEY\tmain: same checkout .env write. Open draft #1507 proposes not writing it; delete if it lands.",
    "K5\t~/.zshrc:$HOME/.CyClaw/.env\tmain: the rc keys block raw-sources ~/.CyClaw/.env into every new shell. Open draft #1507 proposes a filtered loader; delete if it lands.",
)


def _envline() -> Any:
    spec = importlib.util.spec_from_file_location("cyclaw_dotenv_envline", _ENVLINE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_vectors_match_reference_tokenizer() -> None:
    envline = _envline()
    errors = envline.check_vectors(_VECTORS)
    assert errors == []


def test_dotenv_filenames() -> None:
    envline = _envline()
    yes = (
        ".env",
        "app.env",
        ".env.local",
        ".env.example",
        "app.env.example",
        ".envrc",
        "foo.envrc",
        ".env-local",
        ".env-production",
    )
    no = (".environment", ".envbackup", "notes.txt", "env", "settings.yaml")
    for name in yes:
        assert envline.is_dotenv_filename(name), name
    for name in no:
        assert not envline.is_dotenv_filename(name), name


def test_secret_names_are_case_insensitive_and_suffixed() -> None:
    envline = _envline()
    assert envline.is_secret_name("GROK_API_KEY")
    assert envline.is_secret_name("grok_api_key")
    assert envline.is_secret_name("Grok_Api_Key")
    assert envline.is_secret_name("GH_PAT")
    assert envline.is_secret_name("SENTRY_DSN")
    assert envline.is_secret_name("DB_CREDENTIALS")
    assert envline.is_secret_name("AWS_ACCESS_KEY")
    assert envline.is_secret_name("PRINT_KEY")
    # Bare API_KEY ends in _KEY, so the widened suffix classifies it.
    assert envline.is_secret_name("API_KEY")
    assert not envline.is_secret_name("CYCLAW_GATE_PORT")
    assert not envline.is_secret_name("_GROK_API_KEY")
    assert not envline.is_secret_name("MY_KEYBOARD")


def test_literal_scan_sees_quoted_text_the_tokenizer_does_not() -> None:
    envline = _envline()
    text = 'echo "grok_api_key+=$k"'
    assert envline.assignments(text) == []
    assert envline.literal_secret_names(text) == ["grok_api_key"]


def test_k4_k5_baseline_entries_are_unchanged() -> None:
    lines = _BASELINE.read_text(encoding="utf-8").splitlines()
    for entry in _K4_K5_BASELINE:
        assert entry in lines
