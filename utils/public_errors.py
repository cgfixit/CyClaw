"""Keep server filesystem layout and credentials out of HTTP diagnostics."""

import re
from pathlib import Path, PureWindowsPath

from utils.logger import redact_sensitive

_ABSOLUTE_PATH = re.compile(
    r"\"(?:[A-Za-z]:[\\/]|/)[^\"\r\n]*\"|'(?:[A-Za-z]:[\\/]|/)[^'\r\n]*'"
    r"|(?<![\w:/])(?:[A-Za-z]:[\\/]|/)[^\s'\"<>]+"
)


def public_error(value: object, cfg: dict) -> str:
    return _ABSOLUTE_PATH.sub("[local path]", redact_sensitive(str(value), cfg))


def source_label(source: str, corpus: str) -> str:
    """Preserve corpus-relative citations without publishing host directories."""
    if PureWindowsPath(source).is_absolute():
        return PureWindowsPath(source).name
    path = Path(source)
    if not path.is_absolute():
        return source
    try:
        return str(path.relative_to(Path(corpus).expanduser().resolve()))
    except ValueError:
        return path.name
