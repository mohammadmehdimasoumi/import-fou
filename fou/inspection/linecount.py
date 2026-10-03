"""Counting *code* lines.

Python lines are classified with :mod:`tokenize` (so ``#`` inside strings is
never mistaken for a comment) and with the docstring ranges found by the AST
parser.

Rules for Python files:

* **code**      - a line holding at least one real token.  Every physical line
  of a multi-line expression or a non-docstring multi-line string counts.
* **docstring** - lines occupied by a module/class/function docstring.  They
  are *not* counted as code.
* **comment**   - a line whose only content is a comment.
* **blank**     - an empty or whitespace-only line.
"""

from __future__ import annotations

import io
import tokenize
from typing import List, Sequence, Set, Tuple

from ..core.models import LineStats

_IGNORED_TOKENS = frozenset(
    {
        tokenize.NEWLINE,
        tokenize.NL,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENDMARKER,
        tokenize.ENCODING,
        tokenize.COMMENT,
    }
)


def split_lines(text: str) -> List[str]:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def count_plain_lines(text: str) -> LineStats:
    """Line counts for files whose language Fou does not understand."""
    lines = split_lines(text)
    blank = sum(1 for line in lines if not line.strip())
    return LineStats(
        total=len(lines),
        code=len(lines) - blank,
        blank=blank,
        comment=0,
        docstring=0,
        precise=False,
    )


def count_python_lines(
    text: str, docstring_ranges: Sequence[Tuple[int, int]]
) -> Tuple[LineStats, List[int]]:
    """Return ``(stats, prefix)``.

    ``prefix[i]`` is the number of code lines among lines ``1..i`` so that the
    code lines of any range ``a..b`` are ``prefix[b] - prefix[a - 1]``.
    """
    lines = split_lines(text)
    total = len(lines)
    doc_rows: Set[int] = set()
    for start, end in docstring_ranges:
        doc_rows.update(range(max(start, 1), min(end, total) + 1))

    code = [False] * (total + 2)
    comment = [False] * (total + 2)
    precise = True
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            kind = token.type
            row, end_row = token.start[0], token.end[0]
            if kind == tokenize.COMMENT:
                if row <= total:
                    comment[row] = True
                continue
            if kind in _IGNORED_TOKENS:
                continue
            if kind == tokenize.STRING and row in doc_rows and end_row in doc_rows:
                continue  # part of a docstring
            for line_no in range(row, min(end_row, total) + 1):
                code[line_no] = True
    except (tokenize.TokenError, SyntaxError):
        precise = False
        code = [False] * (total + 2)
        for index, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and index not in doc_rows:
                code[index] = True
            comment[index] = stripped.startswith("#")

    code_count = blank_count = comment_count = doc_count = 0
    prefix = [0] * (total + 1)
    for index in range(1, total + 1):
        if code[index]:
            code_count += 1
        elif index in doc_rows:
            doc_count += 1
        elif comment[index]:
            comment_count += 1
        elif not lines[index - 1].strip():
            blank_count += 1
        else:  # unclassifiable remainder: be conservative and call it code
            code[index] = True
            code_count += 1
        prefix[index] = code_count

    stats = LineStats(
        total=total,
        code=code_count,
        blank=blank_count,
        comment=comment_count,
        docstring=doc_count,
        precise=precise,
    )
    return stats, prefix
