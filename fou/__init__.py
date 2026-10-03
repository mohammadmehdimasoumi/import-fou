"""Fou - a developer-controlled codebase inspection and navigation library.

Fou is a deterministic developer tool, not an AI agent: you tell it exactly
what to inspect and it answers from the source code.

    from fou import inspect

    project = inspect(location="./my_project")
    print(project.files())
    project.query(type=["classes", "methods"], details=True).save(
        format="json", path="./structure.json"
    )
"""

from ._version import __version__
from .core.errors import (
    FouError,
    InvalidDepthError,
    InvalidExcludeError,
    InvalidExtensionsError,
    InvalidInspectionTypeError,
    InvalidOptionError,
    InvalidSaveFormatError,
    InvalidSavePathError,
    LocationError,
    SaveError,
)
from .core.result import Result
from .inspection import (
    DEFAULT_EXCLUDE,
    SUPPORTED_TYPES,
    InspectionResult,
    Project,
    inspect,
)

__all__ = [
    "DEFAULT_EXCLUDE",
    "FouError",
    "InspectionResult",
    "InvalidDepthError",
    "InvalidExcludeError",
    "InvalidExtensionsError",
    "InvalidInspectionTypeError",
    "InvalidOptionError",
    "InvalidSaveFormatError",
    "InvalidSavePathError",
    "LocationError",
    "Project",
    "Result",
    "SUPPORTED_TYPES",
    "SaveError",
    "__version__",
    "inspect",
]
