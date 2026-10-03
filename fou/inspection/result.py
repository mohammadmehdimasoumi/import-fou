"""The :class:`InspectionResult` returned by every inspection method."""

from __future__ import annotations

import sys
from typing import IO, Any, Dict, Iterator, List, Optional, Tuple, Union

from ..core.models import Element, ErrorInfo, FileModel, ProjectModel
from ..core.result import Result
from .options import InspectOptions

Item = Union[FileModel, Element]


class InspectionResult(Result):
    """Structured outcome of ``project.files()``, ``project.classes()``, ``project.query()``...

    * ``result.types``    - the requested inspection types
    * ``result[type]``    - the list of items found for one type
    * ``result.errors``   - problems met while inspecting (the scan continues)
    * ``str(result)``     - human-readable text;  ``result.to_dict()`` / ``.save()`` - JSON
    """

    def __init__(
        self,
        *,
        project: ProjectModel,
        options: InspectOptions,
        types: Tuple[str, ...],
        details: bool,
        show_lines: bool,
        groups: Dict[str, List[Item]],
        errors: List[ErrorInfo],
    ) -> None:
        self.project = project
        self.options = options
        self.types = types
        self.details = details
        self.show_lines = show_lines
        self.groups = groups
        self.errors = errors

    # ----------------------------------------------------------- collections
    def __getitem__(self, type_name: str) -> List[Item]:
        try:
            return self.groups[type_name]
        except KeyError:
            raise KeyError(
                f"{type_name!r} was not requested; this result holds: {', '.join(self.types)}"
            ) from None

    def __iter__(self) -> Iterator[Item]:
        for type_name in self.types:
            yield from self.groups[type_name]

    def __len__(self) -> int:
        return sum(len(items) for items in self.groups.values())

    @property
    def files(self) -> List[FileModel]:
        return [item for item in self.groups.get("files", []) if isinstance(item, FileModel)]

    @property
    def elements(self) -> List[Element]:
        return [item for item in self if isinstance(item, Element)]

    # ------------------------------------------------------------- behaviour
    def to_dict(self) -> Dict[str, Any]:
        from .serializer import result_to_dict

        return result_to_dict(self)

    def _link_builder(self, links: Any, scheme: Optional[str], stream: Any) -> Any:
        """A ``LinkBuilder`` when links are wanted, else ``None``.

        ``scheme`` is validated even when links end up disabled, so a typo
        fails the same way on a terminal and in a pipe.
        """
        from .links import LinkBuilder, resolve_template, wants_links

        if scheme is not None:
            resolve_template(scheme)
        if not wants_links(links, stream):
            return None
        return LinkBuilder(str(self.project.root), scheme)

    def render(self, *, links: Any = False, scheme: Optional[str] = None) -> str:
        """Human-readable text.

        ``links`` adds clickable terminal hyperlinks to every file and element:
        ``True`` / ``False`` (the default), or ``"auto"`` to decide from
        ``sys.stdout``.  ``scheme`` picks where a click goes - see
        :mod:`fou.inspection.links` (``"vscode"``, ``"pycharm"``, a custom
        template, ...).  Plain ``str(result)`` never contains links.
        """
        from .renderer import render_result

        return render_result(self, self._link_builder(links, scheme, sys.stdout))

    def show(  # type: ignore[override]
        self,
        file: Optional[IO[str]] = None,
        *,
        links: Any = "auto",
        scheme: Optional[str] = None,
    ) -> None:
        """Print the result; links are added automatically on an interactive terminal."""
        from .renderer import render_result

        stream = file if file is not None else sys.stdout
        print(render_result(self, self._link_builder(links, scheme, stream)), file=file)

    def __repr__(self) -> str:
        return (
            f"<InspectionResult types={list(self.types)} items={len(self)} "
            f"errors={len(self.errors)}>"
        )
