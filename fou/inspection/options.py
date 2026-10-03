"""Validation and normalization of every user-facing argument."""

from __future__ import annotations

import difflib
import numbers
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from ..core.errors import (
    InvalidDepthError,
    InvalidExcludeError,
    InvalidExtensionsError,
    InvalidInspectionTypeError,
    LocationError,
)

#: The official inspection types, in canonical order.
SUPPORTED_TYPES: Tuple[str, ...] = (
    "files",
    "imports",
    "functions",
    "async_functions",
    "classes",
    "methods",
    "variables",
    "constants",
    "decorators",
)

#: Extensions inspected when ``extensions`` is not given.
DEFAULT_EXTENSIONS: Tuple[str, ...] = (".py",)

#: Names skipped when ``exclude`` is not given.  Pass ``exclude=[]`` to skip nothing.
DEFAULT_EXCLUDE: Tuple[str, ...] = (
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".eggs",
    "*.egg-info",
    ".venv",
    "venv",
    "node_modules",
    "build",
    "dist",
    ".idea",
    ".vscode",
)


@dataclass(frozen=True)
class InspectOptions:
    """Normalized, validated options of one inspected project."""

    location: str  # absolute path
    depth: Optional[int]  # None means "all"
    extensions: Optional[Tuple[str, ...]]  # None means "all"
    exclude: Tuple[str, ...]
    hidden: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "depth": "all" if self.depth is None else self.depth,
            "extensions": "all" if self.extensions is None else list(self.extensions),
            "exclude": list(self.exclude),
            "hidden": self.hidden,
        }


def build_options(
    location: Any,
    depth: Any = "all",
    extensions: Any = None,
    exclude: Any = None,
    hidden: Any = False,
) -> InspectOptions:
    if not isinstance(hidden, bool):
        raise _option_error(f"hidden must be True or False, got {hidden!r}.")
    return InspectOptions(
        location=normalize_location(location),
        depth=normalize_depth(depth),
        extensions=normalize_extensions(extensions),
        exclude=normalize_exclude(exclude),
        hidden=hidden,
    )


def _option_error(message: str):
    from ..core.errors import InvalidOptionError

    return InvalidOptionError(message)


# --------------------------------------------------------------------- location
def normalize_location(location: Any) -> str:
    if not isinstance(location, (str, os.PathLike)):
        raise LocationError(
            f"location must be a string or path-like object, got {type(location).__name__}."
        )
    raw = os.fspath(location)
    if isinstance(raw, bytes):
        raise LocationError("location must be text, not bytes.")
    if not raw.strip():
        raise LocationError("location must not be empty.")
    path = os.path.abspath(os.path.expanduser(raw))
    try:
        info = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        raise LocationError(f"Project location does not exist: {path}") from None
    except PermissionError:
        raise LocationError(f"Permission denied for project location: {path}") from None
    except ValueError as exc:
        raise LocationError(f"Invalid project location {raw!r}: {exc}") from None
    except OSError as exc:
        raise LocationError(
            f"Cannot access project location {path}: {exc.strerror or exc}"
        ) from None
    if not stat.S_ISDIR(info.st_mode):
        raise LocationError(f"Project location is not a directory: {path}")
    if not os.access(path, os.R_OK | os.X_OK):
        raise LocationError(f"Project location is not accessible (permission denied): {path}")
    return os.path.realpath(path)


# ------------------------------------------------------------------------ depth
def normalize_depth(depth: Any) -> Optional[int]:
    """``"all"`` -> ``None``; otherwise a non-negative ``int``.

    Convention: ``depth`` is the number of directory levels *below the project
    root* that are scanned.  ``0`` = only files directly in the root, ``1`` =
    plus one level of sub-directories, and so on.
    """
    if isinstance(depth, str):
        if depth.strip().lower() == "all":
            return None
        raise InvalidDepthError(
            f'Invalid depth {depth!r}: use "all" or a non-negative integer.'
        )
    if isinstance(depth, bool) or not isinstance(depth, numbers.Integral):
        raise InvalidDepthError(
            f'Invalid depth {depth!r}: use "all" or a non-negative integer.'
        )
    if depth < 0:
        raise InvalidDepthError(f"Invalid depth {depth!r}: depth cannot be negative.")
    return int(depth)


# ------------------------------------------------------------------- extensions
def normalize_extensions(extensions: Any) -> Optional[Tuple[str, ...]]:
    """``None`` -> ``(".py",)``; ``"all"`` -> ``None`` (every file)."""
    if extensions is None:
        return DEFAULT_EXTENSIONS
    if isinstance(extensions, str):
        items = [extensions]
    elif isinstance(extensions, (set, frozenset)):
        items = sorted(extensions, key=str)
    elif isinstance(extensions, (list, tuple)):
        items = list(extensions)
    else:
        raise InvalidExtensionsError(
            'extensions must be "all" or a list of extensions such as [".py", ".json"], '
            f"got {type(extensions).__name__}."
        )
    if not items:
        raise InvalidExtensionsError("extensions must not be empty.")
    for item in items:
        if not isinstance(item, str):
            raise InvalidExtensionsError(
                f"Every extension must be a string, got {item!r} ({type(item).__name__})."
            )
    lowered = [item.strip().lower() for item in items]
    if "all" in lowered:
        if len(lowered) == 1:
            return None
        raise InvalidExtensionsError('"all" must be used on its own: extensions="all".')
    result = []
    for original, ext in zip(items, lowered):
        if not ext or ext == ".":
            raise InvalidExtensionsError(f"Invalid extension {original!r}.")
        if any(ch in ext for ch in "/\\*?[]"):
            raise InvalidExtensionsError(
                f"Invalid extension {original!r}: it must not contain path separators or wildcards."
            )
        if not ext.startswith("."):
            ext = "." + ext
        if ext not in result:
            result.append(ext)
    return tuple(result)


# ---------------------------------------------------------------------- exclude
def normalize_exclude(exclude: Any) -> Tuple[str, ...]:
    """``None`` -> :data:`DEFAULT_EXCLUDE`; ``[]`` -> exclude nothing.

    Patterns are shell-style globs (``*``, ``?``, ``[seq]``).  A pattern
    without ``/`` is matched against each file/directory *name*; a pattern with
    ``/`` is matched against the path relative to the project root.  A
    trailing ``/`` restricts the pattern to directories.
    """
    if exclude is None:
        return DEFAULT_EXCLUDE
    if isinstance(exclude, (str, os.PathLike)):
        items = [exclude]
    elif isinstance(exclude, (set, frozenset)):
        items = sorted(exclude, key=str)
    elif isinstance(exclude, (list, tuple)):
        items = list(exclude)
    else:
        raise InvalidExcludeError(
            f"exclude must be a list of patterns, got {type(exclude).__name__}."
        )
    patterns = []
    for item in items:
        if isinstance(item, os.PathLike):
            item = os.fspath(item)
        if not isinstance(item, str):
            raise InvalidExcludeError(
                f"Every exclude pattern must be a string, got {item!r} ({type(item).__name__})."
            )
        pattern = item.strip().replace("\\", "/")
        while pattern.startswith("./"):
            pattern = pattern[2:]
        if not pattern.strip("/") or pattern == ".":
            raise InvalidExcludeError(f"Invalid exclude pattern {item!r}.")
        patterns.append(pattern)
    return tuple(dict.fromkeys(patterns))


# ------------------------------------------------------------------------ types
def normalize_types(requested: Any) -> Tuple[str, ...]:
    """Validate the ``type`` argument of ``query``.

    ``"all"`` -> every type in canonical order; otherwise the requested types
    in the order given, without duplicates.
    """
    if isinstance(requested, str):
        if requested.strip().lower() == "all":
            return SUPPORTED_TYPES
        items = [requested]
    elif isinstance(requested, (list, tuple, set, frozenset)):
        items = list(requested) if not isinstance(requested, (set, frozenset)) else sorted(
            requested, key=str
        )
    else:
        raise InvalidInspectionTypeError(
            'type must be "all" or a list of inspection types, '
            f"got {type(requested).__name__}. Supported types: {', '.join(SUPPORTED_TYPES)}."
        )
    if not items:
        raise InvalidInspectionTypeError(
            f"type must not be empty. Supported types: {', '.join(SUPPORTED_TYPES)}."
        )
    chosen = []
    for item in items:
        if not isinstance(item, str):
            raise InvalidInspectionTypeError(
                f"Every inspection type must be a string, got {item!r} ({type(item).__name__})."
            )
        key = item.strip().lower()
        if key == "all":
            raise InvalidInspectionTypeError('"all" must be used on its own: type="all".')
        if key not in SUPPORTED_TYPES:
            hint = difflib.get_close_matches(key, SUPPORTED_TYPES, n=1)
            suggestion = f" Did you mean {hint[0]!r}?" if hint else ""
            raise InvalidInspectionTypeError(
                f"Unsupported inspection type {item!r}.{suggestion} "
                f"Supported types: {', '.join(SUPPORTED_TYPES)}."
            )
        if key not in chosen:
            chosen.append(key)
    return tuple(chosen)
