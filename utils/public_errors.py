"""Keep server filesystem layout and credentials out of HTTP diagnostics."""

import os
import re
from pathlib import Path, PureWindowsPath

from utils.logger import redact_sensitive

# Whitespace is legal immediately after a path root; diagnostics fail closed.
_PATH_START = r"(?:[A-Za-z]:[\\/]|\\\\|/)"
# Paths may contain spaces, quotes and brackets. Unstructured diagnostics have
# no reliable end delimiter, so discard the remainder of the diagnostic once a
# local absolute path starts, including any diagnostic prose after it.
# POSIX filenames can contain newlines, so a line break is not a safe delimiter.
_ABSOLUTE_PATH = re.compile(rf"""(?<![\w:/\\])["']?{_PATH_START}[\s\S]*""")

# Model answers are content, not diagnostics: replace only the path token so
# an answer that mentions "/health" keeps the prose after it (#1635 review).
_PATH_TOKEN = re.compile(r"""(?<![\w:/\\])["']?(?:[A-Za-z]:[\\/]|\\\\(?=\S)|/(?=\S))[^\s'"<>]+["']?""")


def public_error(value: object, cfg: dict) -> str:
    return _ABSOLUTE_PATH.sub("[local path]", redact_sensitive(str(value), cfg))


def public_answer(value: object, cfg: dict) -> str:
    return _PATH_TOKEN.sub("[local path]", redact_sensitive(str(value), cfg))


def source_label(source: str, corpus: str) -> str:
    """Preserve corpus-relative citations without publishing host directories."""
    windows_source = PureWindowsPath(source)
    if windows_source.drive or source.startswith("\\"):
        windows_corpus = PureWindowsPath(corpus)
        if windows_source.is_absolute() and windows_corpus.is_absolute() and ".." not in windows_source.parts:
            try:
                label = windows_source.relative_to(windows_corpus).as_posix()
            except ValueError:
                return windows_source.name
            if os.name == "nt":
                # On a real Windows host, a link inside the corpus may point
                # outside it; such a source gets the basename, as on POSIX.
                try:
                    Path(source).resolve().relative_to(Path(corpus).resolve())
                except (ValueError, OSError, RuntimeError):
                    return windows_source.name
            return label
        return windows_source.name
    path = Path(source)
    # Windows slash-rooted paths have a root but no drive; resolve them against
    # the current drive rather than exposing them as already-relative labels.
    if not path.is_absolute() and not path.root:
        return source
    try:
        # Resolve only to prove containment: a link or ".." that leaves the
        # corpus gets the basename, never its host directory.
        root = Path(corpus).expanduser().resolve()
        contained = path.resolve().relative_to(root)
    except (ValueError, OSError, RuntimeError):
        return path.name
    # Label by the stored name. load_corpus indexes an in-corpus symlink under
    # its own name, so labelling it by its target would merge distinct citations.
    for base in (Path(corpus).expanduser(), root):
        try:
            return Path(os.path.normpath(path)).relative_to(os.path.normpath(base)).as_posix()
        except ValueError:
            continue
    return contained.as_posix()
