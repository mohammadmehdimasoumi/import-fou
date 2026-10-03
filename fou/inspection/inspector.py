"""The public entry point: :func:`inspect` and the :class:`Project` it returns.

Pipeline::

    Filesystem -> scanner -> ProjectModel -> (lazy) analysis -> InspectionResult
                                                                  |- renderer   (humans)
                                                                  `- serializer (machines)

Scanning happens once, on first use.  Each file is analyzed at most once and
cached, so ``project.files()``, ``project.classes()``, ``project.imports()``...
never traverse or re-parse the project again.  Call :meth:`Project.refresh`
after files change on disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.models import Element, ErrorInfo, FileModel, ProjectModel
from .analysis import analyze_file, count_file_lines
from .options import SUPPORTED_TYPES, InspectOptions, build_options, normalize_types
from .result import InspectionResult, Item
from .scanner import scan


#: Types whose ``details`` hold line counts (a tokenizer pass is needed for them).
_LINE_COUNT_TYPES = frozenset({"functions", "async_functions", "classes", "methods"})


def _type_of(element: Element) -> Optional[str]:
    kind = element.kind
    if kind == "function":
        return "async_functions" if element.is_async else "functions"
    return {
        "import": "imports",
        "method": "methods",
        "class": "classes",
        "variable": "variables",
        "constant": "constants",
    }.get(kind)


class Project:
    """An inspected project.  Create one with :func:`inspect`."""

    def __init__(self, options: InspectOptions) -> None:
        self._options = options
        self._model: Optional[ProjectModel] = None
        # type name -> elements, in project order; built once per scan so that
        # classes(), functions(), ... never walk the whole element tree again.
        self._index: Optional[Dict[str, List[Item]]] = None

    # ------------------------------------------------------------ properties
    @property
    def options(self) -> InspectOptions:
        return self._options

    @property
    def root(self) -> Path:
        return Path(self._options.location)

    @property
    def name(self) -> str:
        return self.root.name or str(self.root)

    def __repr__(self) -> str:
        return f"<Project {self.name!r} at {self._options.location!r}>"

    # ----------------------------------------------------------- scan / cache
    def _ensure_model(self) -> ProjectModel:
        if self._model is None:
            self._model = scan(self._options)
            self._index = None
        return self._model

    def refresh(self) -> "Project":
        """Re-scan the filesystem, re-analyzing only files that changed.

        A file is considered unchanged when its size and modification time are
        identical to the previous scan.
        """
        previous: Dict[str, FileModel] = (
            {f.path: f for f in self._model.files} if self._model is not None else {}
        )
        fresh = scan(self._options)
        for file in fresh.files:
            old = previous.get(file.path)
            if (
                old is not None
                and old.analyzed
                and old.size == file.size
                and old.mtime_ns == file.mtime_ns
                and old.module == file.module
            ):
                file.copy_analysis_from(old)
        self._model = fresh
        self._index = None
        return self

    # ----------------------------------------------------- inspection methods
    def files(self, show_lines: bool = True) -> InspectionResult:
        """The project tree; with ``show_lines`` each file shows its code-line count."""
        return self._run(("files",), details=False, show_lines=show_lines)

    def imports(self, details: bool = False) -> InspectionResult:
        return self._run(("imports",), details, True)

    def functions(self, details: bool = False) -> InspectionResult:
        return self._run(("functions",), details, True)

    def async_functions(self, details: bool = False) -> InspectionResult:
        return self._run(("async_functions",), details, True)

    def classes(self, details: bool = False) -> InspectionResult:
        return self._run(("classes",), details, True)

    def methods(self, details: bool = False) -> InspectionResult:
        return self._run(("methods",), details, True)

    def variables(self, details: bool = False) -> InspectionResult:
        return self._run(("variables",), details, True)

    def constants(self, details: bool = False) -> InspectionResult:
        return self._run(("constants",), details, True)

    def decorators(self, details: bool = False) -> InspectionResult:
        return self._run(("decorators",), details, True)

    def query(
        self,
        type: Any = "all",  # noqa: A002 - public parameter name chosen by the spec
        details: bool = False,
        show_lines: bool = True,
    ) -> InspectionResult:
        """Inspect several categories at once.

        ``type`` is ``"all"`` or a list such as ``["classes", "functions"]``.
        """
        requested = type
        return self._run(normalize_types(requested), details, show_lines)

    # --------------------------------------------------------------- internals
    def _run(self, types: Tuple[str, ...], details: bool, show_lines: bool) -> InspectionResult:
        if not isinstance(details, bool):
            raise TypeError(f"details must be True or False, got {details!r}.")
        if not isinstance(show_lines, bool):
            raise TypeError(f"show_lines must be True or False, got {show_lines!r}.")
        model = self._ensure_model()
        need_elements = any(name != "files" for name in types)
        need_file_lines = "files" in types and show_lines
        need_def_lines = details and any(name in _LINE_COUNT_TYPES for name in types)
        need_lines = need_file_lines or need_def_lines
        if need_elements or need_file_lines:
            root = str(model.root)
            for file in model.files:
                if file.language != "python" and not need_file_lines:
                    continue  # non-Python files only matter for the line counts of files()
                if not file.analyzed:
                    analyze_file(file, root, count_lines=need_lines)
                elif need_lines:
                    count_file_lines(file, root)

        errors: List[ErrorInfo] = list(model.errors)
        errors.extend(f.error for f in model.files if f.analyzed and f.error is not None)

        groups: Dict[str, List[Item]] = {}
        index = self._element_index(model) if need_elements else {}
        for name in types:
            groups[name] = list(model.files) if name == "files" else list(index[name])

        return InspectionResult(
            project=model,
            options=self._options,
            types=types,
            details=details,
            show_lines=show_lines,
            groups=groups,
            errors=errors,
        )

    def _element_index(self, model: ProjectModel) -> Dict[str, List[Item]]:
        """Group every element by inspection type (all Python files must be analyzed)."""
        if self._index is None:
            index: Dict[str, List[Item]] = {name: [] for name in SUPPORTED_TYPES if name != "files"}
            for file in model.files:
                for element in file.walk():
                    name = _type_of(element)
                    if name is not None:
                        index[name].append(element)
                        if element.kind == "import":
                            element.attrs["internal"] = self._is_internal(element, model)
                    if element.decorators:
                        index["decorators"].extend(element.decorators)
            self._index = index
        return self._index

    @staticmethod
    def _is_internal(element: Element, model: ProjectModel) -> bool:
        if element.attrs.get("level", 0) > 0:
            return True
        module = element.attrs.get("module") or ""
        return module.split(".")[0] in model.top_level_modules


def inspect(
    location: Any,
    *,
    depth: Any = "all",
    extensions: Any = None,
    exclude: Any = None,
    hidden: bool = False,
) -> Project:
    """Create a :class:`Project` for the directory at ``location``.

    Arguments are validated immediately (a bad ``location``/``depth``/... raises
    a dedicated :class:`~fou.core.errors.FouError`), but the filesystem is only
    scanned when the first inspection method is called.

    * ``depth``      - ``"all"`` (default) or the number of directory levels
      below the root to scan (``0`` = only files directly in the root).
    * ``extensions`` - ``None`` (= ``[".py"]``), a list such as ``[".py", ".json"]``
      or ``"all"``.  Only ``.py`` files are analyzed for code structure.
    * ``exclude``    - ``None`` (= sensible defaults, see ``DEFAULT_EXCLUDE``) or a
      list of glob patterns matched during traversal; ``[]`` excludes nothing.
    * ``hidden``     - include dot-files / dot-directories (default ``False``).
    """
    return Project(build_options(location, depth, extensions, exclude, hidden))
