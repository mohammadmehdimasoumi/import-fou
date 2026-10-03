"""Per-file analysis: read, parse, count lines, fill the :class:`FileModel`.

Nothing here raises for a bad *file*: problems are stored in ``file.error`` so
one malformed file never destroys the whole project scan.

Analysis has two stages for Python files because they differ a lot in cost:

1. :func:`analyze_file` reads and parses the file and collects its elements.
2. :func:`count_file_lines` classifies every physical line with
   :mod:`tokenize`, which is as expensive as parsing itself.  It is only needed
   by results that *show* line counts (``files()`` with ``show_lines`` and
   ``details=True`` on definitions), so ``classes()``, ``imports()`` and friends
   skip it.  When both stages are needed at once, ``analyze_file(...,
   count_lines=True)`` does them with a single read.
"""

from __future__ import annotations

import os
from dataclasses import replace

from ..core.models import ErrorInfo, FileModel
from .linecount import count_plain_lines, count_python_lines
from .parser import apply_code_lines, finalize, parse_python
from .reader import ReadFailure, read_plain_text, read_python_source


def _abs_path(file: FileModel, root: str) -> str:
    return os.path.join(root, *file.path.split("/"))


def analyze_file(file: FileModel, root: str, *, count_lines: bool = True) -> None:
    """Analyze ``file`` (located under ``root``) and mark it ``analyzed``.

    ``count_lines=False`` leaves a Python file's line counts for a later
    :func:`count_file_lines` call.  Non-Python files are always counted.
    """
    abs_path = _abs_path(file, root)
    try:
        if file.language == "python":
            _analyze_python(file, abs_path, count_lines)
        else:
            _analyze_plain(file, abs_path)
    finally:
        file.analyzed = True


def count_file_lines(file: FileModel, root: str) -> None:
    """Stage two: fill ``file.lines`` and the elements' ``code_lines`` (idempotent)."""
    if file.lines_counted or file.language != "python":
        return
    file.lines_counted = True  # even on failure: never retry on every query
    if not file.analyzed or (file.error is not None and file.error.phase == "read"):
        return
    try:
        text = read_python_source(_abs_path(file, root))
    except ReadFailure as failure:  # the file vanished or became unreadable meanwhile
        file.error = ErrorInfo(file.path, "read", failure.error_type, failure.message)
        return
    _apply_line_counts(file, text)


def _apply_line_counts(file: FileModel, text: str) -> None:
    broken = file.error is not None  # a parse error: no docstring ranges, approximate count
    stats, prefix = count_python_lines(text, [] if broken else file.doc_ranges)
    file.lines = replace(stats, precise=False) if broken else stats
    if not broken:
        apply_code_lines(file.elements, prefix)
    file.lines_counted = True


def _analyze_plain(file: FileModel, abs_path: str) -> None:
    try:
        text = read_plain_text(abs_path)
    except ReadFailure as failure:
        file.error = ErrorInfo(file.path, "read", failure.error_type, failure.message)
        return
    if text is None:
        file.binary = True
        return
    file.lines = count_plain_lines(text)
    file.lines_counted = True


def _analyze_python(file: FileModel, abs_path: str, count_lines: bool) -> None:
    try:
        text = read_python_source(abs_path)
    except ReadFailure as failure:
        file.error = ErrorInfo(file.path, "read", failure.error_type, failure.message)
        return
    try:
        parsed = parse_python(text, file.path, file.module)
    except Exception as exc:  # SyntaxError, ValueError, RecursionError, ...
        file.error = ErrorInfo(
            path=file.path,
            phase="parse",
            type=type(exc).__name__,
            message=str(getattr(exc, "msg", None) or exc),
            lineno=getattr(exc, "lineno", None),
            col=getattr(exc, "offset", None),
        )
        if count_lines:
            _apply_line_counts(file, text)
        return
    finalize(parsed, file.path)
    file.docstring = parsed.docstring
    file.elements = parsed.elements
    file.doc_ranges = parsed.docstring_ranges
    if count_lines:
        _apply_line_counts(file, text)
