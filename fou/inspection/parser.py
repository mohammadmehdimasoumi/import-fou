"""Python source analysis built on the standard-library :mod:`ast` module.

A single :class:`ast.NodeVisitor` walks each module exactly once and builds a
tree of :class:`~fou.core.models.Element` objects that preserves lexical
relationships (class -> method, function -> decorator, ...).

Recognition rules (documented because Python has no real constants):

* **function**  - a ``def`` that is *not* directly inside a class body.
* **method**    - a ``def`` / ``async def`` directly inside a class body.
* **constant**  - a module- or class-level name that is ``UPPER_CASE``
  (``^_*[A-Z][A-Z0-9_]*$``) or annotated with ``Final``.  ``TypeVar``-style
  factories are excluded.  Constants never also appear as variables.
* **variable**  - every other binding, with a ``scope`` of ``module``,
  ``class``, ``instance`` (``self.x = ...`` inside a method) or ``local``.

Not recorded: function parameters, comprehension variables, ``except ... as``
names, ``match`` captures, lambda internals, ``del`` targets.
"""

from __future__ import annotations

import ast
import re
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ..core.location import Location
from ..core.models import DEFINITION_KINDS, Element

_CONSTANT_NAME = re.compile(r"^_*[A-Z][A-Z0-9_]*$")
_FINAL_STRING = re.compile(r"^\s*(?:typing\.|typing_extensions\.)?Final\b")
_TYPEVAR_FACTORIES = frozenset({"TypeVar", "ParamSpec", "TypeVarTuple"})
_IMPLICIT_STATIC = frozenset({"__new__"})
_IMPLICIT_CLASS = frozenset({"__init_subclass__", "__class_getitem__"})
_MAX_TEXT = 120

#: Statement fields that hold nested statements, in the same order as
#: ``ast.Try._fields`` (``handlers`` before ``orelse``/``finalbody``) so that the
#: element order, and therefore the ``#2`` id suffixes, match source order.
#: When no ``:=`` appears in the source, expressions are irrelevant, so the
#: visitor only follows these fields.
_BODY_FIELDS = ("body", "handlers", "orelse", "finalbody", "cases")
#: Statements that can never contain a definition or a binding we record.
_LEAF_STATEMENTS = frozenset(
    {ast.Expr, ast.Return, ast.Pass, ast.Break, ast.Continue, ast.Raise, ast.Assert, ast.Delete}
)


@dataclass
class ParsedModule:
    """Raw output of :func:`parse_python` (before line counts are attached)."""

    elements: List[Element]
    docstring: Optional[str]
    docstring_ranges: List[Tuple[int, int]] = field(default_factory=list)


# --------------------------------------------------------------------- helpers
def _unparse(node: Optional[ast.AST], limit: Optional[int] = None) -> Optional[str]:
    if node is None:
        return None
    try:
        text = ast.unparse(node)
    except Exception:  # pragma: no cover - extremely defensive
        return None
    if "\n" in text:
        text = " ".join(text.split())
    if limit is not None and len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def _dotted_name(node: Optional[ast.AST]) -> Optional[str]:
    parts: List[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _is_final(annotation: ast.AST) -> bool:
    node = annotation
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return bool(_FINAL_STRING.match(node.value))
    if isinstance(node, ast.Subscript):
        node = node.value
    name = _dotted_name(node)
    return name is not None and name.split(".")[-1] == "Final"


def _is_typevar_call(value: Optional[ast.AST]) -> bool:
    if isinstance(value, ast.Call):
        name = _dotted_name(value.func)
        return name is not None and name.split(".")[-1] in _TYPEVAR_FACTORIES
    return False


def _is_type_checking(test: ast.AST) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _param(arg: ast.arg, kind: str, default: Optional[ast.AST]) -> Dict[str, Any]:
    return {
        "name": arg.arg,
        "kind": kind,
        "annotation": _unparse(arg.annotation),
        "default": _unparse(default, _MAX_TEXT),
    }


def _describe_arguments(args: ast.arguments) -> List[Dict[str, Any]]:
    positional = list(args.posonlyargs) + list(args.args)
    defaults: List[Optional[ast.AST]] = [None] * (len(positional) - len(args.defaults))
    defaults.extend(args.defaults)
    params: List[Dict[str, Any]] = []
    for index, (arg, default) in enumerate(zip(positional, defaults)):
        kind = "positional_only" if index < len(args.posonlyargs) else "positional_or_keyword"
        params.append(_param(arg, kind, default))
    if args.vararg is not None:
        params.append(_param(args.vararg, "var_positional", None))
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        params.append(_param(arg, "keyword_only", default))
    if args.kwarg is not None:
        params.append(_param(args.kwarg, "var_keyword", None))
    return params


def _signature_text(params: Sequence[Dict[str, Any]], returns: Optional[str]) -> str:
    has_var_positional = any(p["kind"] == "var_positional" for p in params)
    parts: List[str] = []
    keyword_marker_added = False
    for index, param in enumerate(params):
        kind = param["kind"]
        text = param["name"]
        if kind == "var_positional":
            text = "*" + text
        elif kind == "var_keyword":
            text = "**" + text
        if param["annotation"]:
            text += f": {param['annotation']}"
        if param["default"] is not None:
            text += (" = " if param["annotation"] else "=") + param["default"]
        if kind == "keyword_only" and not has_var_positional and not keyword_marker_added:
            parts.append("*")
            keyword_marker_added = True
        parts.append(text)
        if kind == "positional_only":
            following = params[index + 1]["kind"] if index + 1 < len(params) else None
            if following != "positional_only":
                parts.append("/")
    signature = "(" + ", ".join(parts) + ")"
    if returns:
        signature += f" -> {returns}"
    return signature


def _method_type(name: str, decorator_names: Sequence[str]) -> str:
    last = {n.split(".")[-1] for n in decorator_names}
    if "staticmethod" in last:
        return "static"
    if "classmethod" in last:
        return "class"
    if name in _IMPLICIT_STATIC:
        return "static"
    if name in _IMPLICIT_CLASS:
        return "class"
    if last & {"property", "cached_property", "setter", "getter", "deleter"}:
        return "property"
    return "instance"


# ----------------------------------------------------------------------- scope
class _Scope:
    __slots__ = (
        "kind",
        "element",
        "parent",
        "bindings",
        "instance_bindings",
        "globals",
        "nonlocals",
        "self_name",
        "self_kind",
    )

    def __init__(
        self, kind: str, element: Optional[Element] = None, parent: Optional["_Scope"] = None
    ) -> None:
        self.kind = kind  # "module" | "class" | "function"
        self.element = element
        self.parent = parent
        self.bindings: Dict[str, Element] = {}
        self.instance_bindings: Dict[str, Element] = {}
        self.globals: Set[str] = set()
        self.nonlocals: Set[str] = set()
        self.self_name: Optional[str] = None
        self.self_kind: Optional[str] = None  # "instance" | "class"


_SCOPE_LABEL = {"module": "module", "class": "class", "function": "local"}


class _Collector(ast.NodeVisitor):
    def __init__(self, path: str, module: Optional[str], lines: List[str], walrus: bool) -> None:
        self.path = path
        self.module = module
        # Expression subtrees only matter for ``:=`` targets, so they are skipped
        # entirely (a large speed-up) unless the source mentions ``:=``.
        self._walk_expressions = walrus
        self.roots: List[Element] = []
        self.docstring_ranges: List[Tuple[int, int]] = []
        self._lines = lines
        self._module_scope = _Scope("module")
        self._scope = self._module_scope
        self._conditional = 0
        self._type_checking = 0
        self._handlers: Dict[type, Any] = {}

    # ------------------------------------------------------------- entry point
    def collect(self, tree: ast.Module) -> Optional[str]:
        docstring = self._docstring(tree)
        for statement in tree.body:
            self.visit(statement)
        return docstring

    def visit(self, node: ast.AST) -> Any:
        cls = node.__class__
        if not self._walk_expressions:
            if cls in _LEAF_STATEMENTS or isinstance(node, ast.expr):
                return None
        handler = self._handlers.get(cls)
        if handler is None:  # resolve ``visit_<Name>`` once per node class, not per node
            handler = getattr(self, "visit_" + cls.__name__, self.generic_visit)
            self._handlers[cls] = handler
        return handler(node)

    def generic_visit(self, node: ast.AST) -> None:
        if self._walk_expressions:
            super().generic_visit(node)
            return
        for name in _BODY_FIELDS:
            children = getattr(node, name, None)
            if children:
                for child in children:
                    self.visit(child)

    # ----------------------------------------------------------------- helpers
    def _char_col(self, lineno: int, offset: int) -> int:
        if not (1 <= lineno <= len(self._lines)):
            return offset
        line = self._lines[lineno - 1]
        if line.isascii():
            return offset
        return len(line.encode("utf-8")[:offset].decode("utf-8", "ignore"))

    def _location(self, node: Any) -> Location:
        lineno = node.lineno
        end_lineno = getattr(node, "end_lineno", None) or lineno
        col = self._char_col(lineno, node.col_offset)
        end_offset = getattr(node, "end_col_offset", None)
        end_col = self._char_col(end_lineno, end_offset) if end_offset is not None else col
        return Location(self.path, lineno, col, end_lineno, end_col)

    def _segment(self, node: Any) -> Optional[str]:
        """The node's source text exactly as written (``ast.unparse`` normalizes quotes)."""
        try:
            loc = self._location(node)
            first, last = loc.lineno - 1, loc.end_lineno - 1
            if first == last:
                text = self._lines[first][loc.col : loc.end_col]
            else:
                parts = [self._lines[first][loc.col :]]
                parts.extend(self._lines[first + 1 : last])
                parts.append(self._lines[last][: loc.end_col])
                text = " ".join(" ".join(parts).split())
        except (IndexError, AttributeError):
            return None
        return text or None

    def _new_element(
        self,
        kind: str,
        name: str,
        node: Any,
        owner: Optional[Element],
        scope: Optional[str] = None,
        qualname: Optional[str] = None,
    ) -> Element:
        if qualname is None:
            qualname = f"{owner.qualname}.{name}" if owner is not None else name
        element = Element(
            kind=kind,
            name=name,
            qualname=qualname,
            path=self.path,
            location=self._location(node),
            module=self.module,
            parent=owner,
            scope=scope,
        )
        if owner is None:
            self.roots.append(element)
        else:
            owner.children.append(element)
        return element

    def _docstring(self, node: Any) -> Optional[str]:
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            first = body[0]
            self.docstring_ranges.append((first.lineno, first.end_lineno or first.lineno))
            return ast.get_docstring(node, clean=True)
        return None

    @staticmethod
    def _start_lineno(node: Any) -> int:
        return min([node.lineno] + [d.lineno for d in node.decorator_list])

    def _run_scope(self, scope: _Scope, body: Sequence[ast.stmt]) -> None:
        saved = (self._scope, self._conditional, self._type_checking)
        self._scope, self._conditional, self._type_checking = scope, 0, 0
        try:
            for statement in body:
                self.visit(statement)
        finally:
            self._scope, self._conditional, self._type_checking = saved

    def _add_decorators(self, node: Any, target: Element) -> List[str]:
        names: List[str] = []
        for dec in node.decorator_list:
            callee = dec.func if isinstance(dec, ast.Call) else dec
            dotted = _dotted_name(callee)
            expression = self._segment(dec) or _unparse(dec) or "?"
            element = Element(
                kind="decorator",
                name=dotted or expression,
                qualname=f"{target.qualname}@{dotted or expression}",
                path=self.path,
                location=self._location(dec),
                module=self.module,
                parent=target,
            )
            arguments = None
            if isinstance(dec, ast.Call):
                pieces = [_unparse(a) or "?" for a in dec.args]
                pieces += [
                    f"{kw.arg}={_unparse(kw.value) or '?'}" if kw.arg else f"**{_unparse(kw.value)}"
                    for kw in dec.keywords
                ]
                arguments = ", ".join(pieces)
            element.attrs = {
                "expression": expression,
                "is_call": isinstance(dec, ast.Call),
                "target_kind": target.kind,
                "target_qualname": target.qualname,
            }
            element.details = {"arguments": arguments}
            target.decorators.append(element)
            if dotted:
                names.append(dotted)
        return names

    # --------------------------------------------------------- definitions
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node, False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node, True)

    def _visit_function(self, node: Any, is_async: bool) -> None:
        outer = self._scope
        kind = "method" if outer.kind == "class" else "function"
        element = self._new_element(kind, node.name, node, outer.element)
        element.is_async = is_async
        decorator_names = self._add_decorators(node, element)

        params = _describe_arguments(node.args)
        returns = _unparse(node.returns)
        details = element.details
        details["signature"] = _signature_text(params, returns)
        details["parameters"] = params
        details["returns"] = returns
        details["docstring"] = self._docstring(node)
        last_names = {n.split(".")[-1] for n in decorator_names}
        details["is_abstract"] = "abstractmethod" in last_names
        details["is_overload"] = "overload" in last_names
        method_type: Optional[str] = None
        if kind == "method":
            method_type = _method_type(node.name, decorator_names)
            details["method_type"] = method_type
        details["start_lineno"] = self._start_lineno(node)

        scope = _Scope("function", element, outer)
        if kind == "method" and method_type != "static":
            positional = list(node.args.posonlyargs) + list(node.args.args)
            if positional:
                scope.self_name = positional[0].arg
                scope.self_kind = "class" if method_type == "class" else "instance"
        self._run_scope(scope, node.body)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        outer = self._scope
        element = self._new_element("class", node.name, node, outer.element)
        self._add_decorators(node, element)
        details = element.details
        details["bases"] = [_unparse(b) or "?" for b in node.bases]
        details["keywords"] = [
            f"{kw.arg}={_unparse(kw.value) or '?'}" if kw.arg else f"**{_unparse(kw.value)}"
            for kw in node.keywords
        ]
        details["docstring"] = self._docstring(node)
        details["start_lineno"] = self._start_lineno(node)
        self._run_scope(_Scope("class", element, outer), node.body)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return  # lambdas have their own scope and are not recorded

    # -------------------------------------------------------------- imports
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            statement = f"import {alias.name}" + (f" as {alias.asname}" if alias.asname else "")
            self._add_import(
                node,
                alias,
                target=alias.name,
                module=alias.name,
                imported=None,
                level=0,
                bound=alias.asname or alias.name.split(".")[0],
                statement=statement,
                is_from=False,
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        level = node.level or 0
        base = "." * level + module
        for alias in node.names:
            statement = f"from {base} import {alias.name}" + (
                f" as {alias.asname}" if alias.asname else ""
            )
            target = base + ("." if module else "") + alias.name
            self._add_import(
                node,
                alias,
                target=target,
                module=module,
                imported=alias.name,
                level=level,
                bound=alias.asname or alias.name,
                statement=statement,
                is_from=True,
            )

    def _add_import(
        self,
        node: Any,
        alias: Any,
        *,
        target: str,
        module: str,
        imported: Optional[str],
        level: int,
        bound: str,
        statement: str,
        is_from: bool,
    ) -> None:
        owner = self._scope.element
        qualname = f"{owner.qualname}.{bound}" if owner is not None else bound
        located = alias if hasattr(alias, "lineno") else node
        element = self._new_element(
            "import",
            target,
            located,
            owner,
            scope=_SCOPE_LABEL[self._scope.kind],
            qualname=qualname,
        )
        element.attrs = {
            "statement": statement,
            "module": module,
            "imported": imported,
            "alias": alias.asname,
            "level": level,
        }
        element.details = {
            "bound_name": bound,
            "is_from": is_from,
            "is_star": imported == "*",
            "conditional": self._conditional > 0,
            "type_checking": self._type_checking > 0,
        }

    # ------------------------------------------------------------- bindings
    def visit_Global(self, node: ast.Global) -> None:
        self._scope.globals.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self._scope.nonlocals.update(node.names)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._bind_target(target, target, value=node.value)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._bind_target(node.target, node.target, value=node.value, annotation=node.annotation)
        if node.value is not None:
            self.visit(node.value)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._bind_target(node.target, node.target, augmented=True)
        self.visit(node.value)

    def visit_For(self, node: ast.For) -> None:
        self._bind_target(node.target, node.target)
        self.generic_visit(node)

    visit_AsyncFor = visit_For

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if item.optional_vars is not None:
                self._bind_target(item.optional_vars, item.optional_vars)
        self.generic_visit(node)

    visit_AsyncWith = visit_With

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self._bind_target(node.target, node.target, value=node.value)
        self.generic_visit(node)

    def _bind_target(
        self,
        target: ast.AST,
        located: Any,
        value: Optional[ast.AST] = None,
        annotation: Optional[ast.AST] = None,
        augmented: bool = False,
    ) -> None:
        if isinstance(target, ast.Name):
            self._bind_name(target.id, target, value, annotation, augmented)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                self._bind_target(item, item, None, None, augmented)
        elif isinstance(target, ast.Starred):
            self._bind_target(target.value, target.value, None, None, augmented)
        elif isinstance(target, ast.Attribute):
            self._bind_attribute(target, value, annotation, augmented)

    def _bind_name(
        self,
        name: str,
        located: Any,
        value: Optional[ast.AST],
        annotation: Optional[ast.AST],
        augmented: bool,
    ) -> None:
        scope = self._scope
        extra: Optional[Dict[str, Any]] = None
        if scope.kind != "module" and name in scope.globals:
            scope = self._module_scope
            extra = {"via_global": True}
        elif scope.kind != "module" and name in scope.nonlocals:
            return  # rebinds a variable of an enclosing function
        self._record(
            scope.bindings,
            scope.element,
            _SCOPE_LABEL[scope.kind],
            name,
            located,
            value,
            annotation,
            augmented,
            allow_constant=scope.kind in ("module", "class"),
            extra=extra,
        )

    def _bind_attribute(
        self,
        target: ast.Attribute,
        value: Optional[ast.AST],
        annotation: Optional[ast.AST],
        augmented: bool,
    ) -> None:
        scope = self._scope
        base = target.value
        if scope.kind != "function" or scope.self_name is None:
            return
        if not isinstance(base, ast.Name) or base.id != scope.self_name:
            return
        class_scope = scope.parent
        if class_scope is None or class_scope.kind != "class" or scope.element is None:
            return
        if scope.self_kind == "class":
            store, label, allow_constant = class_scope.bindings, "class", True
        else:
            store, label, allow_constant = class_scope.instance_bindings, "instance", False
        self._record(
            store,
            class_scope.element,
            label,
            target.attr,
            target,
            value,
            annotation,
            augmented,
            allow_constant=allow_constant,
            extra={"defined_in": scope.element.qualname},
        )

    def _record(
        self,
        store: Dict[str, Element],
        owner: Optional[Element],
        label: str,
        name: str,
        located: Any,
        value: Optional[ast.AST],
        annotation: Optional[ast.AST],
        augmented: bool,
        allow_constant: bool,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        existing = store.get(name)
        if existing is not None:
            info = existing.details
            info["assignment_count"] += 1
            if annotation is not None and info.get("annotation") is None:
                info["annotation"] = _unparse(annotation)
            if value is not None and info.get("annotation_only"):
                info["annotation_only"] = False
                info["value"] = _unparse(value, _MAX_TEXT)
            return
        if augmented:
            return  # ``x += 1`` of a name this scope never bound
        final = annotation is not None and _is_final(annotation)
        is_constant = allow_constant and (
            final or (bool(_CONSTANT_NAME.match(name)) and not _is_typevar_call(value))
        )
        element = self._new_element(
            "constant" if is_constant else "variable", name, located, owner, scope=label
        )
        element.details = {
            "value": _unparse(value, _MAX_TEXT),
            "annotation": _unparse(annotation),
            "annotation_only": value is None and annotation is not None,
            "assignment_count": 1,
        }
        if final:
            element.details["final"] = True
        if extra:
            element.details.update(extra)
        store[name] = element

    # ------------------------------------------------------- control flow
    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        guarded = _is_type_checking(node.test)
        self._conditional += 1
        if guarded:
            self._type_checking += 1
        for statement in node.body:
            self.visit(statement)
        if guarded:
            self._type_checking -= 1
        for statement in node.orelse:
            self.visit(statement)
        self._conditional -= 1

    def visit_Try(self, node: ast.Try) -> None:
        self._conditional += 1
        self.generic_visit(node)
        self._conditional -= 1

    visit_TryStar = visit_Try


# ----------------------------------------------------------------- public API
def parse_python(text: str, path: str, module: Optional[str]) -> ParsedModule:
    """Parse ``text`` and collect its elements.

    Raises ``SyntaxError`` (and friends) for invalid source; the caller turns
    that into an :class:`~fou.core.models.ErrorInfo` so one broken file never
    aborts a project scan.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tree = ast.parse(text, filename=path)
    collector = _Collector(path, module, text.split("\n"), ":=" in text)
    docstring = collector.collect(tree)
    return ParsedModule(
        elements=collector.roots,
        docstring=docstring,
        docstring_ranges=collector.docstring_ranges,
    )


def finalize(parsed: ParsedModule, path: str, prefix: Optional[Sequence[int]] = None) -> None:
    """Assign stable ids and ``total_lines``; with ``prefix`` also ``code_lines``.

    ``id`` is ``"<path>::<qualname>"``; a repeated qualname in the same file
    (conditional definitions, overloads, ...) gets a ``#2``, ``#3``, ... suffix.
    ``prefix`` is the code-line prefix sum from :func:`count_python_lines`;
    without it ``code_lines`` is attached later by :func:`apply_code_lines`.
    """
    seen: Dict[str, int] = {}
    for root in parsed.elements:
        for element in root.walk():
            base = f"{path}::{element.qualname}"
            count = seen.get(base, 0) + 1
            seen[base] = count
            element.id = base if count == 1 else f"{base}#{count}"
            for index, decorator in enumerate(element.decorators):
                decorator.id = f"{element.id}@{index}"
            if element.kind in DEFINITION_KINDS:
                start = max(element.details["start_lineno"], 1)
                element.details["total_lines"] = element.location.end_lineno - start + 1
    if prefix is not None:
        apply_code_lines(parsed.elements, prefix)


def apply_code_lines(elements: Sequence[Element], prefix: Sequence[int]) -> None:
    """Attach ``code_lines`` to every definition using the code-line prefix sums."""
    total = len(prefix) - 1
    for root in elements:
        for element in root.walk():
            if element.kind in DEFINITION_KINDS:
                start = max(element.details["start_lineno"], 1)
                end = min(element.location.end_lineno, total)
                element.details["code_lines"] = prefix[end] - prefix[start - 1] if end >= start else 0
