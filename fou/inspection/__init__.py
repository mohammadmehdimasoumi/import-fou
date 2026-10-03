"""The ``inspect`` module: *what exists inside this project, and what is its structure?*"""

from .inspector import Project, inspect
from .options import DEFAULT_EXCLUDE, DEFAULT_EXTENSIONS, SUPPORTED_TYPES
from .result import InspectionResult

__all__ = [
    "DEFAULT_EXCLUDE",
    "DEFAULT_EXTENSIONS",
    "InspectionResult",
    "Project",
    "SUPPORTED_TYPES",
    "inspect",
]
