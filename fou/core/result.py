"""The result object every Fou module returns.

Inspection methods never just print: they return a :class:`Result`.  A result
can be rendered for humans (``str(result)`` / ``result.show()``) or serialized
for machines (``result.to_dict()`` / ``result.save(...)``).  Future modules
(find, locate, relation, ...) subclass this and get ``save`` for free.
"""

from __future__ import annotations

import json
import os
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import IO, Any, Dict, Optional

from .errors import InvalidSaveFormatError, InvalidSavePathError, SaveError

#: Version of the machine-readable output layout.  Bump on breaking changes.
SCHEMA_VERSION = "1.0"

SUPPORTED_FORMATS = ("json",)


class Result(ABC):
    """Base class of all Fou results."""

    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """Return the structured, JSON-compatible representation."""

    @abstractmethod
    def render(self, **options: Any) -> str:
        """Return the human-readable (terminal) representation.

        Subclasses define which keyword ``options`` they understand.
        """

    def __str__(self) -> str:
        return self.render()

    def to_json(self, *, indent: Optional[int] = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def show(self, file: Optional[IO[str]] = None, **options: Any) -> None:
        """Print the human-readable representation."""
        print(self.render(**options), file=file)

    def save(self, format: str = "json", path: Any = None) -> Path:  # noqa: A002
        """Serialize this result to ``path`` and return the absolute path.

        Only ``format="json"`` is supported for now.  The parent directory of
        ``path`` must already exist; the file is written atomically.
        """
        fmt = _check_format(format)
        target = _check_path(path)
        if fmt == "json":
            payload = self.to_json() + "\n"
        else:  # pragma: no cover - guarded by _check_format
            raise InvalidSaveFormatError(f"Unsupported save format {format!r}.")
        _atomic_write(target, payload)
        return target


def _check_format(fmt: Any) -> str:
    if not isinstance(fmt, str) or fmt.strip().lower() not in SUPPORTED_FORMATS:
        raise InvalidSaveFormatError(
            f"Unsupported save format {fmt!r}. Supported formats: "
            f"{', '.join(SUPPORTED_FORMATS)}."
        )
    return fmt.strip().lower()


def _check_path(path: Any) -> Path:
    if path is None:
        raise InvalidSavePathError("A save path is required, e.g. save(format='json', path='./out.json').")
    if not isinstance(path, (str, os.PathLike)):
        raise InvalidSavePathError(
            f"Save path must be a string or path-like object, got {type(path).__name__}."
        )
    raw = os.fspath(path)
    if isinstance(raw, bytes):
        raise InvalidSavePathError("Save path must be text, not bytes.")
    if not raw.strip():
        raise InvalidSavePathError("Save path must not be empty.")
    if "\0" in raw:
        raise InvalidSavePathError("Save path must not contain null characters.")
    target = Path(os.path.abspath(os.path.expanduser(raw)))
    if target.is_dir():
        raise InvalidSavePathError(f"Save path is a directory, not a file: {target}")
    if not target.parent.is_dir():
        raise InvalidSavePathError(f"Directory does not exist: {target.parent}")
    return target


def _atomic_write(target: Path, payload: str) -> None:
    tmp_name: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=str(target.parent),
            prefix=".fou-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_name = handle.name
            handle.write(payload)
        os.replace(tmp_name, target)
        tmp_name = None
    except OSError as exc:
        raise SaveError(f"Could not write {target}: {exc.strerror or exc}") from exc
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
