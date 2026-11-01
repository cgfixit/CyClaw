"""Replace generated files only after a complete, flushed same-directory write."""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from pathlib import Path


def write_atomic(path: Path, data: bytes, *, mode: int) -> None:
    """Write bytes with explicit permissions; preserve the target on failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        os.chmod(temporary, mode)
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
