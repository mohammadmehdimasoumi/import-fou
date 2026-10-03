import pytest

from fou import inspect


@pytest.fixture
def project(sample_project):
    return inspect(sample_project)


def names(result):
    return [e.qualname for e in result.elements]


def by_qualname(result, qualname):
    return next(e for e in result.elements if e.qualname == qualname)


def test_functions_exclude_methods_and_async(project):
    assert names(project.functions()) == ["main", "home", "helper", "helper.inner", "run"]


def test_async_functions_are_distinguishable(project):
    result = project.async_functions()
    assert names(result) == ["fetch_data"]
    assert result.elements[0].is_async is True
    # an async method is a method (is_async=True), not an async function
    methods = project.methods()
    refresh = by_qualname(methods, "User.refresh")
    assert refresh.kind == "method" and refresh.is_async is True


def test_classes_and_methods_relationship(project):
    user = by_qualname(project.classes(details=True), "User")
    method_names = [c.name for c in user.children if c.kind == "method"]
    assert method_names == ["__init__", "login", "refresh", "make", "build", "title", "title"]
    login = by_qualname(project.methods(), "User.login")
    assert login.parent is user


def test_class_details(project):
    user = by_qualname(project.classes(details=True), "User")
    assert user.details["bases"] == ["Base"]
    assert user.details["keywords"] == ["metaclass=Meta"]
    assert user.details["docstring"] == "A user."
    assert [d.attrs["expression"] for d in user.decorators] == ["dataclass"]


def test_method_types(project):
    ms = project.methods()
    assert by_qualname(ms, "User.make").details["method_type"] == "static"
    assert by_qualname(ms, "User.build").details["method_type"] == "class"
    assert by_qualname(ms, "User.login").details["method_type"] == "instance"
    titles = [e for e in ms.elements if e.qualname == "User.title"]
    assert [t.details["method_type"] for t in titles] == ["property", "property"]


def test_duplicate_qualnames_get_unique_ids(project):
    ids = [e.id for e in project.methods().elements if e.qualname == "User.title"]
    assert ids == ["models/user.py::User.title", "models/user.py::User.title#2"]
    all_ids = [e.id for e in project.query(type="all").elements]
    assert len(all_ids) == len(set(all_ids))


def test_signature_details(project):
    helper = by_qualname(project.functions(details=True), "helper")
    assert helper.details["signature"] == "(a, b=2, /, c=3, *args, d, e=5, **kwargs)"
    fetch = project.async_functions(details=True).elements[0]
    assert fetch.details["signature"] == "(url, *, timeout: float = 5.0) -> bytes"
    kinds = [p["kind"] for p in helper.details["parameters"]]
    assert kinds == [
        "positional_only", "positional_only", "positional_or_keyword",
        "var_positional", "keyword_only", "keyword_only", "var_keyword",
    ]


def test_line_counts_in_details(project):
    main = by_qualname(project.functions(details=True), "main")
    # def line, token line, return line (docstring is not code)
    assert main.details["code_lines"] == 3
    assert main.details["total_lines"] == 4
    home = by_qualname(project.functions(details=True), "home")
    assert home.details["start_lineno"] == home.location.lineno - 2  # two decorators
    assert home.details["code_lines"] == 4  # 2 decorators + def + pass


def test_imports(project):
    imports = project.imports(details=True).elements
    by_target = {(e.path, e.name): e for e in imports}
    os_import = by_target[("main.py", "os")]
    assert os_import.attrs["statement"] == "import os"
    assert os_import.attrs["internal"] is False
    assert by_target[("main.py", "pathlib.Path")].attrs["module"] == "pathlib"
    assert by_target[("main.py", "database.Database")].attrs["imported"] == "Database"
    relative = by_target[("models/user.py", ".product.Product")]
    assert relative.attrs["level"] == 1 and relative.attrs["internal"] is True
    assert by_target[("models/user.py", "models.product")].attrs["internal"] is True
    aliased = by_target[("models/user.py", "ujson")]
    assert aliased.attrs["alias"] == "json" and aliased.details["conditional"] is True
    guarded = by_target[("models/user.py", "database.Session")]
    assert guarded.details["type_checking"] is True


def test_star_and_relative_only_imports(tmp_path):
    (tmp_path / "a.py").write_text("from os import *\nfrom . import x\nfrom .. import y as z\n")
    els = inspect(tmp_path).imports(details=True).elements
    assert [e.name for e in els] == ["os.*", ".x", "..y"]
    assert els[0].details["is_star"] is True
    assert els[1].attrs["statement"] == "from . import x"
    assert els[2].attrs["alias"] == "z" and els[2].attrs["level"] == 2


def test_variable_scopes(project):
    result = project.variables(details=True)
    scopes = {(e.qualname, e.scope) for e in result.elements if e.path == "models/user.py"}
    assert ("User.name", "class") in scopes and ("User.name", "instance") in scopes
    assert ("User.age", "instance") in scopes
    assert ("User.registry", "class") in scopes  # cls.registry in a classmethod
    assert ("User.login.token", "local") in scopes
    assert ("helper.total", "local") in scopes
    mod = {e.qualname: e.scope for e in result.elements if e.path == "main.py"}
    assert mod == {"counter": "module", "main.token": "local", "fetch_data.data": "local"}


def test_instance_attribute_assignments_are_merged(project):
    ages = [e for e in project.variables(details=True).elements if e.qualname == "User.age"]
    assert len(ages) == 1
    assert ages[0].details["assignment_count"] == 2
    assert ages[0].details["annotation"] == "int"
    assert ages[0].details["defined_in"] == "User.__init__"


def test_same_name_class_and_instance_variable_are_distinct(project):
    names_scopes = [
        (e.qualname, e.scope) for e in project.variables().elements if e.qualname == "User.name"
    ]
    assert ("User.name", "class") in names_scopes and ("User.name", "instance") in names_scopes


def test_augmented_assignment_and_loop_variables(project):
    totals = [e for e in project.variables(details=True).elements if e.qualname == "helper.total"]
    assert len(totals) == 1 and totals[0].details["assignment_count"] == 2
    assert any(e.qualname == "helper.i" for e in project.variables().elements)


def test_global_declaration_binds_module_variable(project):
    state = [e for e in project.constants(details=True).elements if e.name == "STATE"]
    assert len(state) == 1
    assert state[0].scope == "module" and state[0].qualname == "STATE"
    assert state[0].details["via_global"] is True


def test_walrus_target_is_a_local_variable(project):
    n = [e for e in project.variables().elements if e.qualname == "run.n"]
    assert len(n) == 1 and n[0].scope == "local"


def test_constants_rules(project):
    consts = {(e.qualname, e.scope) for e in project.constants().elements}
    assert ("VERSION", "module") in consts
    assert ("DEBUG", "module") in consts
    assert ("MAX_AGE", "module") in consts  # also Final-annotated
    assert ("User.LIMIT", "class") in consts
    variables = {e.qualname for e in project.variables().elements}
    assert not variables & {q for q, _ in consts}  # never both


def test_final_annotation_makes_a_constant(tmp_path):
    (tmp_path / "a.py").write_text(
        "from typing import Final\nlimit: Final[int] = 3\nT = TypeVar('T')\nn = 1\n"
    )
    p = inspect(tmp_path)
    assert [e.name for e in p.constants().elements] == ["limit"]
    assert sorted(e.name for e in p.variables().elements) == ["T", "n"]


def test_decorators_are_attached_to_targets(project):
    result = project.decorators(details=True)
    home = [d for d in result.elements if d.attrs["target_qualname"] == "home"]
    assert [d.attrs["expression"] for d in home] == ['app.route("/")', "cache(timeout=60)"]
    assert home[0].name == "app.route" and home[0].parent.qualname == "home"
    assert home[1].details["arguments"] == "timeout=60"
    assert home[0].id == "models/product.py::home@0"
    kinds = {d.attrs["target_kind"] for d in result.elements}
    assert {"class", "function", "method"} <= kinds


def test_nested_function_and_scope_chain(project):
    inner = by_qualname(project.functions(), "helper.inner")
    assert inner.parent.qualname == "helper" and inner.kind == "function"


def test_locations_are_precise(project):
    user = by_qualname(project.classes(), "User")
    assert user.location.path == "models/user.py"
    assert user.location.lineno == 19  # the ``class`` line, not the decorator
    assert user.details == {} or "start_lineno" in user.details
    assert by_qualname(project.classes(details=True), "User").details["start_lineno"] == 18


def test_non_ascii_columns_are_character_offsets(tmp_path):
    (tmp_path / "a.py").write_text('é = 1; ü = 2\n', encoding="utf-8")
    cols = {e.name: e.location.col for e in inspect(tmp_path).variables().elements}
    assert cols == {"é": 0, "ü": 7}


def test_non_python_files_have_no_python_structures(sample_project):
    p = inspect(sample_project, extensions=[".py", ".json", ".txt"])
    paths = {e.path for e in p.query(type="all").elements}
    assert not paths & {"data/settings.json", "notes.txt"}


def test_syntax_error_does_not_destroy_the_scan(tmp_path):
    (tmp_path / "good.py").write_text("def ok():\n    pass\n")
    (tmp_path / "bad.py").write_text("def broken(:\n    pass\n")
    result = inspect(tmp_path).query(type=["functions", "files"])
    assert names(result) == ["ok"]
    [error] = result.errors
    assert (error.path, error.phase, error.type) == ("bad.py", "parse", "SyntaxError")
    assert error.lineno == 1
    assert "Errors (1)" in str(result) and "bad.py" in str(result)
    assert result.to_dict()["errors"][0]["type"] == "SyntaxError"


def test_bad_encoding_is_reported(tmp_path):
    (tmp_path / "bin.py").write_bytes(b"x = '\xff\xfe'\n")
    (tmp_path / "ok.py").write_text("y = 1\n")
    result = inspect(tmp_path).variables()
    assert [e.name for e in result.elements] == ["y"]
    assert result.errors[0].phase == "read"


def test_coding_cookie_and_bom_are_honoured(tmp_path):
    (tmp_path / "latin.py").write_bytes("# -*- coding: latin-1 -*-\nname = 'caf\xe9'\n".encode("latin-1"))
    (tmp_path / "bom.py").write_bytes(b"\xef\xbb\xbfz = 1\n")
    result = inspect(tmp_path).variables()
    assert sorted(e.name for e in result.elements) == ["name", "z"]
    assert result.errors == []


def test_crlf_line_endings(tmp_path):
    (tmp_path / "a.py").write_bytes(b"def f():\r\n    return 1\r\n\r\nx = 2\r\n")
    p = inspect(tmp_path)
    f = p.functions(details=True).elements[0]
    assert f.details["code_lines"] == 2
    assert p.files().files[0].lines.total == 4


def test_empty_and_comment_only_files(tmp_path):
    (tmp_path / "empty.py").write_text("")
    (tmp_path / "c.py").write_text("# only a comment\n")
    result = inspect(tmp_path).query(type="all")
    assert len(result.elements) == 0 and result.errors == []
    lines = {f.name: f.lines.code for f in result.files}
    assert lines == {"c.py": 0, "empty.py": 0}


def test_python_310_plus_syntax(tmp_path):
    import sys

    if sys.version_info < (3, 10):
        pytest.skip("match statement needs 3.10")
    (tmp_path / "a.py").write_text(
        "def f(x):\n    match x:\n        case 1:\n            y = 1\n        case _:\n            y = 2\n    return y\n"
    )
    y = [e for e in inspect(tmp_path).variables(details=True).elements if e.name == "y"]
    assert len(y) == 1 and y[0].details["assignment_count"] == 2
