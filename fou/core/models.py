"""Structured, renderer-independent data models.

These classes are the *internal representation* of a project.  Scanning fills
them, parsing enriches them, and renderers/serializers only ever read them.
Nothing in here knows about printing or JSON files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterator, List, Optional, Tuple

from .location import Location

#: Elements that own a body and therefore get line counts and nested children.
DEFINITION_KINDS = frozenset({"class", "function", "method"})
#: Elements that carry a ``scope`` label.
SCOPED_KINDS = frozenset({"variable", "constant", "import"})
#: Elements that get a fully qualified name (``module.qualname``).
QUALIFIED_KINDS = frozenset({"class", "function", "method", "variable", "constant"})


@dataclass(frozen=True)
class ErrorInfo:
    """A problem found while inspecting one path (the scan keeps going)."""

    path: str
    phase: str  # "scan" | "read" | "parse"
    type: str
    message: str
    lineno: Optional[int] = None
    col: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "phase": self.phase,
            "type": self.type,
            "message": self.message,
            "lineno": self.lineno,
            "col": self.col,
        }

    def __str__(self) -> str:
        where = f" (line {self.lineno})" if self.lineno else ""
        return f"{self.path}: {self.type}: {self.message}{where}"


@dataclass(frozen=True)
class LineStats:
    """Line classification of one file.

    For Python files ``code`` is the number of lines holding real code:
    blank lines, comment-only lines and docstring lines are *not* counted.
    For non-Python files nothing is known about comments, so ``precise`` is
    ``False`` and ``code`` simply means "non-blank lines".
    """

    total: int
    code: int
    blank: int
    comment: int
    docstring: int
    precise: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "code": self.code,
            "blank": self.blank,
            "comment": self.comment,
            "docstring": self.docstring,
            "precise": self.precise,
        }


@dataclass(eq=False, repr=False)
class Element:
    """One discovered code element (class, function, variable, import, ...).

    ``kind`` is one of ``import``, ``function``, ``method``, ``class``,
    ``variable``, ``constant`` or ``decorator``.  Relationships are preserved:
    ``parent`` / ``children`` follow lexical scoping, and a decorator is an
    element whose ``parent`` is the decorated target.

    ``attrs`` always appears in serialized output; ``details`` only when the
    caller asked for ``details=True``.
    """

    kind: str
    name: str
    qualname: str
    path: str
    location: Location
    module: Optional[str] = None
    parent: Optional["Element"] = None
    children: List["Element"] = field(default_factory=list)
    decorators: List["Element"] = field(default_factory=list)
    is_async: bool = False
    scope: Optional[str] = None
    attrs: Dict[str, Any] = field(default_factory=dict)
    details: Dict[str, Any] = field(default_factory=dict)
    id: str = ""

    def __repr__(self) -> str:
        return f"<Element {self.kind} {self.qualname!r} {self.path}:{self.location.lineno}>"

    def walk(self) -> Iterator["Element"]:
        """Yield this element and every descendant, parents before children."""
        stack = [self]
        while stack:
            element = stack.pop()
            yield element
            stack.extend(reversed(element.children))

    def ancestors(self) -> Iterator["Element"]:
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def to_dict(self, details: bool = False) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "qualname": self.qualname,
        }
        if self.module is not None and self.kind in QUALIFIED_KINDS:
            data["fqn"] = f"{self.module}.{self.qualname}"
        data["path"] = self.path
        data["module"] = self.module
        data["location"] = self.location.to_dict()
        data["parent"] = self.parent.id if self.parent is not None else None
        if self.kind in SCOPED_KINDS:
            data["scope"] = self.scope
        if self.kind in ("function", "method"):
            data["is_async"] = self.is_async
        data.update(self.attrs)
        if details:
            data.update(self.details)
            if self.kind in DEFINITION_KINDS:
                data["decorators"] = [d.attrs["expression"] for d in self.decorators]
            data["children"] = [
                {"id": c.id, "kind": c.kind, "name": c.name} for c in self.children
            ]
        return data


@dataclass(eq=False)
class FileModel:
    """A discovered file plus (lazily filled) analysis results."""

    path: str  # relative to the project root, "/" separated
    name: str
    extension: str
    size: int
    mtime_ns: int
    language: Optional[str] = None  # "python" when the file can be parsed
    module: Optional[str] = None  # dotted module name for Python files

    analyzed: bool = False
    binary: bool = False
    lines: Optional[LineStats] = None
    docstring: Optional[str] = None
    elements: List[Element] = field(default_factory=list)
    error: Optional[ErrorInfo] = None
    #: Python only: whether ``lines`` and the elements' ``code_lines`` are filled in.
    #: Line counting needs a (comparatively slow) tokenizer pass, so it only runs
    #: when a result actually shows line counts.
    lines_counted: bool = False
    #: Docstring line ranges found while parsing; reused by the lazy line count.
    doc_ranges: List[Tuple[int, int]] = field(default_factory=list)

    def walk(self) -> Iterator[Element]:
        for root in self.elements:
            yield from root.walk()

    def copy_analysis_from(self, other: "FileModel") -> None:
        self.analyzed = other.analyzed
        self.binary = other.binary
        self.lines = other.lines
        self.docstring = other.docstring
        self.elements = other.elements
        self.error = other.error
        self.lines_counted = other.lines_counted
        self.doc_ranges = other.doc_ranges

    def to_dict(self, show_lines: bool = True) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "type": "file",
            "name": self.name,
            "path": self.path,
            "extension": self.extension,
            "size_bytes": self.size,
            "language": self.language,
            "module": self.module,
        }
        if show_lines:
            data["binary"] = self.binary if self.analyzed else None
            data["lines"] = self.lines.to_dict() if self.lines is not None else None
        if self.error is not None:
            data["error"] = self.error.to_dict()
        return data


@dataclass(eq=False)
class DirNode:
    """A directory in the scanned tree (files are listed before sub-directories)."""

    name: str
    path: str  # "" for the project root
    files: List[FileModel] = field(default_factory=list)
    dirs: List["DirNode"] = field(default_factory=list)

    def iter_files(self) -> Iterator[FileModel]:
        yield from self.files
        for directory in self.dirs:
            yield from directory.iter_files()

    def count_directories(self) -> int:
        return sum(1 + d.count_directories() for d in self.dirs)

    def to_dict(self, show_lines: bool = True) -> Dict[str, Any]:
        children: List[Dict[str, Any]] = [f.to_dict(show_lines) for f in self.files]
        children.extend(d.to_dict(show_lines) for d in self.dirs)
        return {
            "type": "directory",
            "name": self.name,
            "path": self.path or ".",
            "children": children,
        }


@dataclass(eq=False)
class ProjectModel:
    """Everything the scanner learned about the project."""

    name: str
    root: Path
    tree: DirNode
    files: List[FileModel]
    errors: List[ErrorInfo] = field(default_factory=list)
    top_level_modules: FrozenSet[str] = frozenset()
