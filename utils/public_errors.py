"""Keep server filesystem layout and credentials out of HTTP diagnostics."""

import re
from pathlib import Path, PureWindowsPath

from utils.logger import redact_sensitive

_PATH_START = r"(?:[A-Za-z]:[\\/]|\\\\|/)"
# Paths may contain spaces, quotes and brackets. Unstructured diagnostics have
# no reliable end delimiter, so discard the remainder of the diagnostic once a
# local absolute path starts, including any diagnostic prose after it.
# POSIX filenames can contain newlines, so a line break is not a safe delimiter.
_ABSOLUTE_PATH = re.compile(rf"""(?<![\w:/\\])["']?{_PATH_START}[\s\S]*""")


def public_error(value: object, cfg: dict) -> str:
    return _ABSOLUTE_PATH.sub("[local path]", redact_sensitive(str(value), cfg))


def source_label(source: str, corpus: str) -> str:
    """Preserve corpus-relative citations without publishing host directories."""
    windows_source = PureWindowsPath(source)
    if windows_source.drive or source.startswith("\\"):
        windows_corpus = PureWindowsPath(corpus)
        if windows_source.is_absolute() and windows_corpus.is_absolute() and ".." not in windows_source.parts:
            try:
                return windows_source.relative_to(windows_corpus).as_posix()
            except ValueError:
                pass
        return windows_source.name
    path = Path(source)
    # Windows slash-rooted paths have a root but no drive; resolve them against
    # the current drive rather than exposing them as already-relative labels.
    if not path.is_absolute() and not path.root:
        return source
    try:
        return path.resolve().relative_to(Path(corpus).expanduser().resolve()).as_posix()
    except (ValueError, OSError, RuntimeError):
        return path.name
