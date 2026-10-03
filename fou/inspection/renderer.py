"""Human-readable terminal output.

Renders the structured result; it never touches the filesystem or the AST.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from ..core.models import DEFINITION_KINDS, DirNode, Element, ErrorInfo, FileModel
from .links import LinkBuilder, hyperlink
from .result import InspectionResult

_TITLES = {
    "files": "Files",
    "imports": "Imports",
    "functions": "Functions",
    "async_functions": "Async functions",
    "classes": "Classes",
    "methods": "Methods",
    "variables": "Variables",
    "constants": "Constants",
    "decorators": "Decorators",
}

_DOC_PREVIEW = 80


@dataclass
class _Node:
    label: str
    info: List[str] = field(default_factory=list)
    children: List["_Node"] = field(default_factory=list)
    url: Optional[str] = None  # when set, the label is drawn as a terminal hyperlink


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _render_nodes(nodes: List[_Node], prefix: str, separate: bool) -> List[str]:
    lines: List[str] = []
    for index, node in enumerate(nodes):
        last = index == len(nodes) - 1
        child_prefix = prefix + ("    " if last else "│   ")
        label = hyperlink(node.label, node.url) if node.url else node.label
        lines.append(prefix + ("└── " if last else "├── ") + label)
        for info in node.info:
            lines.append(child_prefix + info)
        lines.extend(_render_nodes(node.children, child_prefix, separate))
        if separate and not last:
            lines.append(prefix + "│")
    return lines


# ----------------------------------------------------------------------- files
def _lines_label(file: FileModel) -> Optional[str]:
    if file.binary:
        return "-> binary"
    stats = file.lines
    if stats is None:
        return None
    if file.language == "python":
        suffix = "" if stats.precise else " (approx.)"
        return f"-> {_plural(stats.code, 'line')}{suffix}"
    return f"-> {_plural(stats.code, 'non-blank line')}"


def _directory_nodes(
    directory: DirNode, show_lines: bool, links: Optional[LinkBuilder] = None
) -> List[_Node]:
    nodes: List[_Node] = []
    for file in directory.files:
        info: List[str] = []
        if show_lines:
            label = _lines_label(file)
            if label:
                info.append(label)
        url = links.url(file.path) if links is not None else None
        nodes.append(_Node(file.name, info, url=url))
    for child in directory.dirs:
        nodes.append(_Node(child.name + "/", [], _directory_nodes(child, show_lines, links)))
    return nodes


def _render_files(result: InspectionResult, links: Optional[LinkBuilder]) -> List[str]:
    nodes = _directory_nodes(result.project.tree, result.show_lines, links)
    if not nodes:
        return ["(no matching files)"]
    return _render_nodes(nodes, "", separate=result.show_lines)


# -------------------------------------------------------------------- elements
def _name_part(element: Element, nested: bool) -> str:
    return element.name if nested else element.qualname


def _label(element: Element, details: bool, nested: bool) -> str:
    kind = element.kind
    name = _name_part(element, nested)
    if kind in ("function", "method"):
        prefix = "async " if element.is_async else ""
        if details:
            return f"{prefix}{name}{element.details.get('signature', '()')}"
        return f"{prefix}{name}()"
    if kind == "class":
        if details:
            heads = list(element.details.get("bases", [])) + list(element.details.get("keywords", []))
            if heads:
                return f"{name}({', '.join(heads)})"
        return name
    if kind == "import":
        return element.attrs["statement"]
    if kind == "decorator":
        return "@" + element.attrs["expression"]
    return name


def _first_line(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    line = text.strip().splitlines()[0].strip()
    if len(line) > _DOC_PREVIEW:
        line = line[: _DOC_PREVIEW - 1] + "…"
    return line or None


def _info(element: Element, details: bool) -> List[str]:
    kind = element.kind
    info: List[str] = []
    if kind in DEFINITION_KINDS:
        if details:
            info.append(f"-> {_plural(element.details.get('code_lines', 0), 'line')}")
            if element.decorators:
                info.append(
                    "-> decorators: "
                    + ", ".join("@" + d.attrs["expression"] for d in element.decorators)
                )
            method_type = element.details.get("method_type")
            if method_type and method_type != "instance":
                info.append(f"-> {method_type} method")
            summary = _first_line(element.details.get("docstring"))
            if summary:
                info.append(f"-> doc: {summary}")
    elif kind in ("variable", "constant"):
        info.append(f"-> scope: {element.scope}")
        if details:
            annotation = element.details.get("annotation")
            if annotation:
                info.append(f"-> type: {annotation}")
            value = element.details.get("value")
            if value is not None:
                info.append(f"-> value: {value}")
            count = element.details.get("assignment_count", 1)
            if count > 1:
                info.append(f"-> assigned {count} times")
            defined_in = element.details.get("defined_in")
            if defined_in:
                info.append(f"-> defined in: {defined_in}")
    elif kind == "import":
        if details:
            info.append("-> internal" if element.attrs.get("internal") else "-> external")
            if element.details.get("conditional"):
                guarded = " (TYPE_CHECKING)" if element.details.get("type_checking") else ""
                info.append(f"-> conditional{guarded}")
            if element.scope != "module":
                info.append(f"-> scope: {element.scope}")
    elif kind == "decorator":
        info.append(f"-> on: {element.attrs['target_kind']} {element.attrs['target_qualname']}")
    return info


def _element_node(
    element: Element, details: bool, nested: bool, links: Optional[LinkBuilder] = None
) -> _Node:
    location = element.location
    node = _Node(
        label=f"{_label(element, details, nested)}  (line {location.lineno})",
        info=_info(element, details),
        url=links.url(element.path, location.lineno, location.col) if links is not None else None,
    )
    if details and element.kind in DEFINITION_KINDS:
        for child in element.children:
            if child.kind in DEFINITION_KINDS:
                node.children.append(_element_node(child, True, True, links))
    return node


def _is_nested(element: Element, selected: Set[int]) -> bool:
    """With details, a definition is drawn under the selected definition that owns it."""
    if element.kind not in DEFINITION_KINDS:
        return False
    return any(id(ancestor) in selected for ancestor in element.ancestors())


def _render_elements(
    result: InspectionResult, type_name: str, links: Optional[LinkBuilder]
) -> List[str]:
    items = [item for item in result.groups[type_name] if isinstance(item, Element)]
    if not items:
        return ["(none found)"]
    details = result.details
    selected = {id(item) for item in items}
    by_path: Dict[str, List[Element]] = {}
    for element in items:
        if details and _is_nested(element, selected):
            continue
        by_path.setdefault(element.path, []).append(element)
    lines: List[str] = []
    for path, elements in by_path.items():
        if lines:
            lines.append("")
        lines.append(hyperlink(path, links.url(path)) if links is not None else path)
        nodes = [_element_node(e, details, False, links) for e in elements]
        lines.extend(_render_nodes(nodes, "", separate=False))
    return lines


# ------------------------------------------------------------------- top level
def _error_line(error: ErrorInfo) -> str:
    return f"  ! {error}"


def render_result(result: InspectionResult, links: Optional[LinkBuilder] = None) -> str:
    """Render ``result`` as text; with ``links`` every file and element is a hyperlink."""
    lines: List[str] = [f"Project: {result.project.name}", ""]
    only_files = result.types == ("files",)
    for type_name in result.types:
        if not only_files:
            lines.append(f"{_TITLES[type_name]} ({len(result.groups[type_name])})")
            lines.append("")
        if type_name == "files":
            body = _render_files(result, links)
        else:
            body = _render_elements(result, type_name, links)
        lines.extend(body)
        lines.append("")
    if result.errors:
        lines.append(f"Errors ({len(result.errors)}):")
        lines.extend(_error_line(error) for error in result.errors)
        lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)
