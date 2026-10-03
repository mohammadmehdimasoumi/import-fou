"""Reading files from disk with robust error reporting."""

from __future__ import annotations

import io
import tokenize
from typing import Optional


class ReadFailure(Exception):
    """A file could not be read or decoded."""

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _read_bytes(abs_path: str) -> bytes:
    try:
        with open(abs_path, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise ReadFailure(type(exc).__name__, exc.strerror or str(exc)) from None


def read_python_source(abs_path: str) -> str:
    """Read Python source honouring BOMs and PEP 263 coding cookies."""
    data = _read_bytes(abs_path)
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
        text = data.decode(encoding)
    except UnicodeDecodeError as exc:
        raise ReadFailure("UnicodeDecodeError", str(exc)) from None
    except (SyntaxError, LookupError) as exc:
        raise ReadFailure(type(exc).__name__, str(getattr(exc, "msg", None) or exc)) from None
    return _normalize_newlines(text)


def read_plain_text(abs_path: str) -> Optional[str]:
    """Read a non-Python file as text; ``None`` means the file looks binary."""
    data = _read_bytes(abs_path)
    if b"\0" in data[:8192]:
        return None
    return _normalize_newlines(data.decode("utf-8", errors="replace"))
