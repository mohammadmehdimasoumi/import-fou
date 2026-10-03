"""Filesystem traversal.

The scanner prunes excluded and too-deep directories *before* descending into
them, never follows symbolic links, sorts every directory listing (so output
is deterministic) and keeps going when a directory cannot be read.
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Dict, List, Tuple

from ..core.models import DirNode, ErrorInfo, FileModel, ProjectModel
from .options import InspectOptions

_Pattern = Tuple[str, bool, bool]  # (glob, directories_only, match_full_path)


def compile_patterns(patterns: Tuple[str, ...]) -> List[_Pattern]:
    compiled: List[_Pattern] = []
    for raw in patterns:
        pattern = raw
        directories_only = pattern.endswith("/")
        pattern = pattern.rstrip("/")
        anchored = pattern.startswith("/")
        pattern = pattern.strip("/")
        compiled.append((pattern, directories_only, anchored or "/" in pattern))
    return compiled


def _sort_key(entry: "os.DirEntry[str]") -> Tuple[str, str]:
    return (entry.name.casefold(), entry.name)


class _Scanner:
    def __init__(self, options: InspectOptions) -> None:
        self._options = options
        self._root = options.location
        self._patterns = compile_patterns(options.exclude)
        self._extensions = options.extensions
        self._max_depth = options.depth
        self._errors: List[ErrorInfo] = []

    def run(self) -> ProjectModel:
        root = Path(self._root)
        name = root.name or str(root)
        tree = self._scan_dir(self._root, "", 0, name)
        files = list(tree.iter_files())
        self._assign_modules(files, name)
        top_level = frozenset(f.module.split(".")[0] for f in files if f.module)
        return ProjectModel(
            name=name,
            root=root,
            tree=tree,
            files=files,
            errors=self._errors,
            top_level_modules=top_level,
        )

    # ----------------------------------------------------------------- helpers
    def _is_excluded(self, name: str, rel_path: str, is_dir: bool) -> bool:
        for pattern, directories_only, full_path in self._patterns:
            if directories_only and not is_dir:
                continue
            if fnmatch.fnmatchcase(rel_path if full_path else name, pattern):
                return True
        return False

    def _matches_extension(self, name: str) -> bool:
        if self._extensions is None:
            return True
        lowered = name.lower()
        return any(lowered.endswith(ext) and len(lowered) > len(ext) for ext in self._extensions)

    def _error(self, rel_path: str, exc: OSError) -> None:
        self._errors.append(
            ErrorInfo(
                path=rel_path or ".",
                phase="scan",
                type=type(exc).__name__,
                message=exc.strerror or str(exc),
            )
        )

    def _scan_dir(self, abs_dir: str, rel_dir: str, level: int, name: str) -> DirNode:
        node = DirNode(name=name, path=rel_dir)
        try:
            with os.scandir(abs_dir) as iterator:
                entries = sorted(iterator, key=_sort_key)
        except OSError as exc:
            self._error(rel_dir, exc)
            return node

        for entry in entries:
            entry_name = entry.name
            if not self._options.hidden and entry_name.startswith("."):
                continue
            rel_path = f"{rel_dir}/{entry_name}" if rel_dir else entry_name
            try:
                if entry.is_symlink():
                    continue
                is_dir = entry.is_dir(follow_symlinks=False)
                is_file = (not is_dir) and entry.is_file(follow_symlinks=False)
            except OSError as exc:
                self._error(rel_path, exc)
                continue
            if not (is_dir or is_file):
                continue
            if self._is_excluded(entry_name, rel_path, is_dir):
                continue
            if is_dir:
                if self._max_depth is None or level < self._max_depth:
                    child = self._scan_dir(entry.path, rel_path, level + 1, entry_name)
                    if child.files or child.dirs:  # hide directories with nothing to show
                        node.dirs.append(child)
            elif self._matches_extension(entry_name):
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    self._error(rel_path, exc)
                    continue
                lowered = entry_name.lower()
                node.files.append(
                    FileModel(
                        path=rel_path,
                        name=entry_name,
                        extension=os.path.splitext(lowered)[1],
                        size=info.st_size,
                        mtime_ns=info.st_mtime_ns,
                        language="python" if lowered.endswith(".py") else None,
                    )
                )
        return node

    def _assign_modules(self, files: List[FileModel], root_name: str) -> None:
        cache: Dict[str, bool] = {}

        def is_package(directory: str) -> bool:
            if directory not in cache:
                cache[directory] = os.path.isfile(os.path.join(directory, "__init__.py"))
            return cache[directory]

        for file in files:
            if file.language != "python":
                continue
            parts = file.path.split("/")
            directories = parts[:-1]
            stem = parts[-1][:-3]
            package: List[str] = []
            depth = len(directories)
            while True:
                directory = os.path.join(self._root, *directories[:depth]) if depth else self._root
                if not is_package(directory):
                    break
                package.insert(0, directories[depth - 1] if depth else root_name)
                if depth == 0:
                    break
                depth -= 1
            module_parts = package + ([] if stem == "__init__" else [stem])
            file.module = ".".join(module_parts) if module_parts else None


def scan(options: InspectOptions) -> ProjectModel:
    """Scan the project described by ``options`` (no file contents are read)."""
    return _Scanner(options).run()
