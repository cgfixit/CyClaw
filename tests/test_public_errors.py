"""Public diagnostics hide whole paths while citations retain corpus identity."""

import pytest

from utils.public_errors import public_answer, public_error, source_label


@pytest.mark.parametrize(
    "path",
    [
        "/home/you/private person/team A/run book.md",
        "/ Sensitive Customer/plan.md",
        "/\tSensitive Customer/plan.md",
        "/\nSensitive Customer/plan.md",
        "/private/Team [sensitive] Customer/plan.md",
        "/private/O'Brian/private-notes/plan.md",
        "/private/team\nsensitive document/file.md",
        '/private/Team "sensitive" Customer/plan.md',
        r"C:\Users\you\private person\team A\run book.md",
        r"\\private-server\private-share\team A\run book.md",
        "//private-server/private-share/team A/run book.md",
    ],
)
@pytest.mark.parametrize("quote", ["", "'", '"'])
def test_error_hides_complete_paths(path, quote):
    assert public_error(f"cannot open {quote}{path}{quote}", {}) == "cannot open [local path]"


def test_ordinary_diagnostics_and_url_are_preserved():
    text = "LLM_SERVICE_ERROR: unavailable at https://localhost:8787"
    assert public_error(text, {}) == text
    assert public_error("[LLM Error: missing /private/model file.gguf]", {}) == "[LLM Error: missing [local path]"


def test_rate_limit_diagnostic_uses_unambiguous_prose():
    text = "Rate limit exceeded (60 req per 60s)"
    assert public_error(text, {}) == text


def test_ambiguous_slash_diagnostic_fails_closed():
    assert public_error("ratio 3 / 4 is fine", {}) == "ratio 3 [local path]"


def test_answers_keep_prose_after_a_path_token():
    answer = "Use the /srv/cyclaw/run.sh script, then restart. See C:\\vault\\a.md too."
    assert public_answer(answer, {}) == "Use the [local path] script, then restart. See [local path] too."


@pytest.mark.parametrize("corpus", [r"C:\vault", r"\\server\share\vault", "/private/vault"])
def test_citations_keep_distinct_corpus_paths(corpus):
    for team in ("teamA", "teamB"):
        assert source_label(f"{corpus}/{team}/runbook.md", corpus) == f"{team}/runbook.md"


@pytest.mark.parametrize(
    "source",
    [
        r"C:\private\book.md",
        r"C:private\book.md",
        r"\private\book.md",
        r"C:\vault\..\private\book.md",
        r"\\other\share\book.md",
    ],
)
def test_windows_paths_outside_corpus_are_basename_only(source):
    assert source_label(source, r"C:\vault") == "book.md"


def test_stale_symlink_citation_falls_back_to_basename(tmp_path):
    path = tmp_path / "loop.md"
    path.symlink_to(path)
    assert source_label(str(path), str(tmp_path)) == "loop.md"


def test_slash_rooted_path_outside_corpus_is_basename_only():
    assert source_label("/private/outside/book.md", "/private/vault") == "book.md"


def test_slash_rooted_citations_with_windows_path_semantics(monkeypatch):
    from pathlib import PureWindowsPath
    from utils import public_errors

    class WindowsPathProbe(PureWindowsPath):
        def resolve(self):
            return self

        def expanduser(self):
            return self

    monkeypatch.setattr(public_errors, "Path", WindowsPathProbe)
    assert source_label("/private/vault/team/runbook.md", "/private/vault") == "team/runbook.md"
    assert source_label("/private/outside/book.md", "/private/vault") == "book.md"
