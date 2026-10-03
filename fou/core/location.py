"""A source location shared by every Fou module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class Location:
    """Where something lives in the project.

    * ``path`` is relative to the project root and always uses ``/`` separators.
    * ``lineno`` / ``end_lineno`` are 1-based (like :mod:`ast`).
    * ``col`` / ``end_col`` are 0-based **character** offsets (unlike
      :mod:`ast`, which reports UTF-8 byte offsets).
    """

    path: str
    lineno: int
    col: int
    end_lineno: int
    end_col: int

    def to_dict(self, include_path: bool = False) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        if include_path:
            data["path"] = self.path
        data["lineno"] = self.lineno
        data["col"] = self.col
        data["end_lineno"] = self.end_lineno
        data["end_col"] = self.end_col
        return data

    def __str__(self) -> str:
        return f"{self.path}:{self.lineno}"
