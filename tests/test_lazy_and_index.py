import fou
from fou import inspect
from fou._version import __version__
from fou.cli import main


def count_calls(monkeypatch):
    import fou.inspection.analysis as analysis

    calls = []
    real = analysis.count_python_lines
    monkeypatch.setattr(analysis, "count_python_lines", lambda *a: calls.append(1) or real(*a))
    return calls


# ------------------------------------------------------------ lazy line counts
def test_queries_without_line_output_skip_the_tokenizer(sample_project, monkeypatch):
    calls = count_calls(monkeypatch)
    p = inspect(sample_project)
    p.classes(); p.functions(details=False); p.imports(details=True)
    p.variables(details=True); p.constants(details=True); p.decorators(details=True)
    p.query(type=["classes", "imports"])
    p.files(show_lines=False)
    assert calls == []


def test_each_file_is_counted_at_most_once(sample_project, monkeypatch):
    calls = count_calls(monkeypatch)
    p = inspect(sample_project)
    p.classes()
    assert calls == []
    p.classes(details=True)
    python_files = sum(1 for f in p._model.files if f.language == "python")
    assert len(calls) == python_files
    p.files(); p.query(type="all", details=True); p.methods(details=True)
    assert len(calls) == python_files
    p.refresh()  # nothing changed on disk -> nothing is counted again
    p.files(); p.functions(details=True)
    assert len(calls) == python_files


def test_lazy_and_eager_results_are_identical(sample_project):
    eager = inspect(sample_project).query(type="all", details=True).to_dict()
    lazy_project = inspect(sample_project)
    lazy_project.classes()
    lazy_project.imports()
    lazy_project.methods(details=True)
    lazy = lazy_project.query(type="all", details=True).to_dict()
    files_first = inspect(sample_project)
    files_first.files()
    assert files_first.query(type="all", details=True).to_dict() == eager
    assert lazy == eager


def test_syntax_error_file_is_still_approximate_after_lazy_stage(tmp_path):
    (tmp_path / "bad.py").write_text("def broken(:\n    pass\n\n# c\nx = 1\n")
    (tmp_path / "ok.py").write_text("def f():\n    return 1\n")
    p = inspect(tmp_path)
    assert [e.name for e in p.functions().elements] == ["f"]
    result = p.files()
    lines = {f.name: f.lines for f in result.files}
    assert lines["bad.py"].precise is False and lines["bad.py"].code == 3
    assert lines["ok.py"].precise is True and lines["ok.py"].code == 2
    assert [e.path for e in result.errors] == ["bad.py"]


def test_file_changed_between_stages_does_not_crash(tmp_path):
    (tmp_path / "a.py").write_text("def f():\n    return 1\n")
    p = inspect(tmp_path)
    p.functions()
    (tmp_path / "a.py").unlink()
    result = p.functions(details=True)  # the lazy stage cannot read it any more
    assert [e.phase for e in result.errors] == ["read"]


# ------------------------------------------------------------------ type index
def test_element_index_is_built_once_and_reset_by_refresh(sample_project):
    p = inspect(sample_project)
    assert p._index is None
    p.classes()
    index = p._index
    assert index is not None
    p.functions(); p.imports(); p.query(type="all")
    assert p._index is index
    p.refresh()
    assert p._index is None
    p.classes()
    assert p._index is not index


def test_results_do_not_share_mutable_lists(sample_project):
    p = inspect(sample_project)
    expected = len(p.classes().elements)
    assert expected > 0
    first = p.classes()
    first.groups["classes"].clear()
    assert len(p.classes().elements) == expected


def test_internal_flag_follows_refresh(tmp_path):
    (tmp_path / "a.py").write_text("import newmod\n")
    p = inspect(tmp_path)
    assert p.imports().elements[0].attrs["internal"] is False
    (tmp_path / "newmod.py").write_text("X = 1\n")
    p.refresh()
    assert p.imports().elements[0].attrs["internal"] is True


# ------------------------------------------------- element order (regression)
def test_definitions_keep_source_order_across_try_branches(tmp_path):
    (tmp_path / "m.py").write_text(
        "try:\n    class A: pass\n"
        "except ImportError:\n    class A: pass\n"
        "else:\n    class A: pass\n"
        "finally:\n    class A: pass\n"
    )
    result = inspect(tmp_path).classes()
    assert [e.id for e in result.elements] == ["m.py::A", "m.py::A#2", "m.py::A#3", "m.py::A#4"]
    lines = [e.location.lineno for e in result.elements]
    assert lines == sorted(lines)


def test_walrus_mode_and_plain_mode_agree(tmp_path):
    body = "def f():\n    a = 1\n    return a\n\nclass C:\n    X = 1\n    def m(self):\n        self.y = 2\n"
    (tmp_path / "plain.py").write_text(body)
    (tmp_path / "walrus.py").write_text(body + "\nif (n := 3) > 1:\n    pass\n")
    r = inspect(tmp_path).query(type=["functions", "classes", "methods", "variables", "constants"])
    by_file = {}
    for e in r.elements:
        by_file.setdefault(e.path, []).append((e.kind, e.qualname, e.scope))
    # the only difference is the walrus-bound module variable ``n``
    assert ("variable", "n", "module") in by_file["walrus.py"]
    without_n = [x for x in by_file["walrus.py"] if x[1] != "n"]
    assert without_n == by_file["plain.py"]


# --------------------------------------------------------------------- version
def test_version_is_single_sourced(sample_project, capsys, tmp_path):
    assert fou.__version__ == __version__ == "0.1.0"
    assert main(["--version"] if False else ["inspect", str(sample_project), "-t", "files", "--json"]) == 0
    import json

    assert json.loads(capsys.readouterr().out)["tool_version"] == "0.1.0"
    pyproject = (__import__("pathlib").Path(__file__).parent.parent / "pyproject.toml").read_text()
    assert "fou._version.__version__" in pyproject
