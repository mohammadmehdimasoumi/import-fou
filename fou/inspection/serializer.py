"""Machine-readable output.

The JSON is *structured data*, not a copy of the terminal text.  Elements are
a flat list per type that keeps relationships through stable ids: ``parent``
points at the enclosing element and (with ``details=True``) ``children`` lists
direct descendants.  Directories and files form a nested ``tree``.
"""

from __future__ import annotations

from typing import Any, Dict

from .._version import __version__
from ..core.models import Element
from ..core.result import SCHEMA_VERSION
from .result import InspectionResult


def result_to_dict(result: InspectionResult) -> Dict[str, Any]:
    model = result.project
    data: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "tool": "fou",
        "tool_version": __version__,
        "module": "inspect",
        "project": {
            "name": model.name,
            "root": str(model.root),
            "options": result.options.to_dict(),
        },
        "query": {
            "types": list(result.types),
            "details": result.details,
            "show_lines": result.show_lines,
        },
        "summary": {
            "files": len(model.files),
            "directories": model.tree.count_directories(),
            "counts": {name: len(result.groups[name]) for name in result.types},
            "errors": len(result.errors),
        },
    }
    if "files" in result.types:
        data["tree"] = model.tree.to_dict(result.show_lines)
    elements: Dict[str, Any] = {}
    for name in result.types:
        if name == "files":
            continue
        elements[name] = [
            item.to_dict(result.details) for item in result.groups[name] if isinstance(item, Element)
        ]
    if elements:
        data["elements"] = elements
    data["errors"] = [error.to_dict() for error in result.errors]
    return data
