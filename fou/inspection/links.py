"""Clickable output: terminal hyperlinks that open a file at the right line.

Modern terminals understand the *OSC 8* escape sequence, which turns any piece
of text into a link::

    ESC ] 8 ; ; URL ESC \\  visible text  ESC ] 8 ; ; ESC \\

Fou wraps every file name and every element of a rendered result in such a
link.  Which program opens it, and whether it jumps to the line, is decided by
the URL, so the URL is built from a *scheme* (a small template):

=================  ====================================================
``file``           ``file:///abs/path.py`` - opens the file, no line
``vscode``         ``vscode://file/abs/path.py:LINE:COL``
``vscode-insiders``, ``cursor``  same shape as ``vscode``
``pycharm``, ``idea``            ``pycharm://open?file=...&line=LINE&column=COL``
``sublime``        ``subl://open?url=file://...&line=LINE&column=COL``
``textmate``       ``txmt://open?url=file://...&line=LINE&column=COL``
=================  ====================================================

Any other scheme is a custom template using ``{path}`` (absolute, ``/``-rooted
and percent-encoded), ``{fspath}`` (the same without forcing a leading ``/``),
``{uri}`` (a ``file://`` URI), ``{line}`` (1-based) and ``{col}`` (1-based).

Links are *never* part of ``str(result)`` or of the JSON: they are only added
when explicitly requested (``result.render(links=True)``) or when
``result.show()`` / the CLI detect an interactive terminal.
"""

from __future__ import annotations

import difflib
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote

from ..core.errors import InvalidOptionError

#: Built-in schemes.  ``file`` opens the file only; editor schemes jump to the line.
SCHEMES: Dict[str, str] = {
    "file": "{uri}",
    "vscode": "vscode://file{path}:{line}:{col}",
    "vscode-insiders": "vscode-insiders://file{path}:{line}:{col}",
    "cursor": "cursor://file{path}:{line}:{col}",
    "pycharm": "pycharm://open?file={fspath}&line={line}&column={col}",
    "idea": "idea://open?file={fspath}&line={line}&column={col}",
    "sublime": "subl://open?url={uri}&line={line}&column={col}",
    "textmate": "txmt://open?url={uri}&line={line}&column={col}",
}
DEFAULT_SCHEME = "file"

#: Environment variable that sets the default scheme (e.g. ``FOU_LINK_SCHEME=vscode``).
ENV_SCHEME = "FOU_LINK_SCHEME"
#: Environment variable that overrides ``links="auto"`` (``always`` / ``never``).
ENV_LINKS = "FOU_LINKS"

_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_KNOWN_PLACEHOLDERS = frozenset({"path", "fspath", "uri", "line", "col"})
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_LINK_MODES = ("auto", "always", "never")


def resolve_template(scheme: Optional[str] = None) -> str:
    """Return the URL template for ``scheme`` (a name, a custom template, or ``None``).

    ``None`` falls back to ``$FOU_LINK_SCHEME`` and then to ``file``.
    """
    if scheme is None:
        scheme = os.environ.get(ENV_SCHEME, "").strip() or DEFAULT_SCHEME
    if not isinstance(scheme, str) or not scheme.strip():
        raise InvalidOptionError(
            f"Link scheme must be a name or a template string, got {scheme!r}."
        )
    scheme = scheme.strip()
    if scheme.lower() in SCHEMES:
        return SCHEMES[scheme.lower()]
    if "{" in scheme:
        unknown = sorted(set(_PLACEHOLDER.findall(scheme)) - _KNOWN_PLACEHOLDERS)
        if unknown:
            raise InvalidOptionError(
                f"Unknown placeholder(s) in link template {scheme!r}: "
                f"{', '.join('{' + u + '}' for u in unknown)}. "
                f"Use {', '.join('{' + k + '}' for k in sorted(_KNOWN_PLACEHOLDERS))}."
            )
        return scheme
    hint = difflib.get_close_matches(scheme.lower(), SCHEMES, n=1)
    suggestion = f" Did you mean {hint[0]!r}?" if hint else ""
    raise InvalidOptionError(
        f"Unknown link scheme {scheme!r}.{suggestion} "
        f"Built-in schemes: {', '.join(SCHEMES)}; or pass a template such as "
        f"'vscode://file{{path}}:{{line}}:{{col}}'."
    )


class LinkBuilder:
    """Builds the URL that opens ``rel_path`` (relative to ``root``) at a given line."""

    def __init__(self, root: str, scheme: Optional[str] = None) -> None:
        self.root = root
        self.template = resolve_template(scheme)
        self._parts: Dict[str, Tuple[str, str, str]] = {}

    def _path_parts(self, rel_path: str) -> Tuple[str, str, str]:
        parts = self._parts.get(rel_path)
        if parts is None:
            absolute = os.path.join(self.root, *rel_path.split("/"))
            encoded = quote(absolute.replace(os.sep, "/"), safe="/:")
            parts = (
                "/" + encoded.lstrip("/"),  # {path}
                encoded,  # {fspath}
                Path(absolute).as_uri(),  # {uri}
            )
            self._parts[rel_path] = parts
        return parts

    def url(self, rel_path: str, lineno: int = 1, col: int = 0) -> str:
        """``col`` is 0-based (like :class:`~fou.core.location.Location`); URLs use 1-based."""
        path, fspath, uri = self._path_parts(rel_path)
        values = {
            "path": path,
            "fspath": fspath,
            "uri": uri,
            "line": str(max(lineno, 1)),
            "col": str(max(col, 0) + 1),
        }
        return _PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), self.template)


def hyperlink(text: str, url: str) -> str:
    """Wrap ``text`` in an OSC 8 hyperlink (control characters are stripped from ``url``)."""
    url = _CONTROL_CHARS.sub("", url)
    return f"\x1b]8;;{url}\x1b\\{text}\x1b]8;;\x1b\\"


def wants_links(mode: Any, stream: Any) -> bool:
    """Decide whether to emit hyperlinks.

    ``True`` / ``"always"`` -> yes; ``False`` / ``"never"`` -> no; ``"auto"`` ->
    yes only when ``stream`` is an interactive terminal (and ``TERM`` is not
    ``dumb``), unless ``$FOU_LINKS`` is ``always`` or ``never``.
    """
    if isinstance(mode, bool):
        return mode
    if not isinstance(mode, str) or mode.strip().lower() not in _LINK_MODES:
        raise InvalidOptionError(
            f"links must be True, False or one of {', '.join(map(repr, _LINK_MODES))}; got {mode!r}."
        )
    mode = mode.strip().lower()
    if mode == "always":
        return True
    if mode == "never":
        return False
    forced = os.environ.get(ENV_LINKS, "").strip().lower()
    if forced == "always":
        return True
    if forced == "never":
        return False
    try:
        interactive = bool(stream.isatty())
    except (AttributeError, ValueError):
        interactive = False
    return interactive and os.environ.get("TERM") != "dumb"
