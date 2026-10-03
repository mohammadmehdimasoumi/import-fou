import json

import pytest

from fou import (
    InvalidInspectionTypeError,
    InvalidSaveFormatError,
    InvalidSavePathError,
    Result,
    inspect,
)

EXPECTED_TREE = """\
Project: MyProject

├── config.py
│   -> 1 line
│
├── main.py
│   -> 12 lines
│
├── models/
│   ├── __init__.py
│   │   -> 0 lines
│   │
│   ├── product.py
│   │   -> 7 lines
│   │
│   └── user.py
│       -> 44 lines
│
└── utils/
    └── helper.py
        -> 6 lines"""


def test_files_tree_matches_spec_layout(sample_project):
    assert str(inspect(sample_project).files()) == EXPECTED_TREE


def test_files_without_lines_is_compact(sample_project):
    text = str(inspect(sample_project).files(show_lines=False))
    assert text == (
        "Project: MyProject\n\n"
        "├── config.py\n├── main.py\n├── models/\n│   ├── __init__.py\n│   ├── product.py\n"
        "│   └── user.py\n└── utils/\n    └── helper.py"
    )


def test_methods_are_not_only_printed_they_are_returned(sample_project):
    result = inspect(sample_project).classes()
    assert isinstance(result, Result)
    assert len(result) == 2 and [e.name for e in result] == ["Product", "User"]
    assert result["classes"][0].name == "Product"
    with pytest.raises(KeyError):
        result["functions"]


def test_non_python_files_in_tree(sample_project):
    text = str(inspect(sample_project, extensions="all").files())
    assert "notes.txt\n│   -> 2 non-blank lines" in text
    assert "settings.json\n│       -> 1 non-blank line\n" in text or "settings.json" in text


def test_binary_files_are_marked(tmp_path):
    (tmp_path / "img.png").write_bytes(b"\x89PNG\x00\x01\x02")
    text = str(inspect(tmp_path, extensions=[".png"]).files())
    assert "-> binary" in text


def test_details_render_matches_spec_shape(tmp_path):
    (tmp_path / "m.py").write_text(
        "class User:\n    def __init__(self):\n        pass\n\n    def login(self):\n        a = 1\n        return a\n"
    )
    text = str(inspect(tmp_path).classes(details=True))
    assert text == (
        "Project: tmp\n\n".replace("tmp", tmp_path.name)
        + "Classes (1)\n\nm.py\n└── User  (line 1)\n    -> 6 lines\n"
        "    ├── __init__(self)  (line 2)\n    │   -> 2 lines\n"
        "    └── login(self)  (line 5)\n        -> 3 lines"
    )


def test_details_do_not_duplicate_nested_definitions(sample_project):
    text = str(inspect(sample_project).query(type=["classes", "methods"], details=True))
    classes_section = text.split("Methods (")[0]
    assert classes_section.count("login(self)") == 1  # drawn once, under its class
    assert "\nlogin(self)" not in classes_section  # ...and not again at top level


def test_variables_render_scope_lines(tmp_path):
    (tmp_path / "m.py").write_text("x = 10\n\nclass User:\n    name = 'Ali'\n\ndef test():\n    age = 20\n")
    text = str(inspect(tmp_path).variables())
    assert "x  (line 1)\n│   -> scope: module" in text
    assert "User.name  (line 4)\n│   -> scope: class" in text
    assert "test.age  (line 7)\n    -> scope: local" in text


def test_empty_sections(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    assert "(none found)" in str(inspect(tmp_path).classes())
    assert "(no matching files)" in str(inspect(tmp_path, extensions=[".md"]).files())


def test_show_prints(sample_project, capsys):
    inspect(sample_project).files().show()
    assert capsys.readouterr().out.startswith("Project: MyProject")


# ------------------------------------------------------------------------ query
def test_query_all_and_lists(sample_project):
    p = inspect(sample_project)
    everything = p.query(type="all")
    assert everything.types[0] == "files" and len(everything.types) == 9
    subset = p.query(type=["functions", "classes"])
    assert subset.types == ("functions", "classes")


def test_query_rejects_bad_types(sample_project):
    with pytest.raises(InvalidInspectionTypeError):
        inspect(sample_project).query(type=["classes", "bogus"])


def test_query_default_is_all(sample_project):
    assert inspect(sample_project).query().types == inspect(sample_project).query(type="all").types


# ------------------------------------------------------------------------- JSON
def test_json_structure(sample_project):
    data = inspect(sample_project).query(type=["files", "classes", "methods"], details=True).to_dict()
    assert data["schema_version"] == "1.0" and data["module"] == "inspect"
    assert data["project"]["name"] == "MyProject"
    assert data["project"]["options"]["depth"] == "all"
    assert data["query"] == {"types": ["files", "classes", "methods"], "details": True, "show_lines": True}
    assert data["summary"]["counts"]["classes"] == 2
    assert data["summary"]["files"] == 6 and data["summary"]["directories"] == 2

    tree = data["tree"]
    assert tree["type"] == "directory" and tree["path"] == "."
    models = next(c for c in tree["children"] if c["name"] == "models")
    user_file = next(c for c in models["children"] if c["name"] == "user.py")
    assert user_file["path"] == "models/user.py" and user_file["lines"]["code"] == 44

    user = next(c for c in data["elements"]["classes"] if c["name"] == "User")
    assert user["fqn"] == "models.user.User" and user["parent"] is None
    login = next(m for m in data["elements"]["methods"] if m["qualname"] == "User.login")
    assert login["parent"] == user["id"]
    assert {"id": login["id"], "kind": "method", "name": "login"} in user["children"]
    assert user["location"]["lineno"] == 19 and "end_lineno" in user["location"]
    assert login["signature"] == "(self)" and login["code_lines"] == 3


def test_json_without_details_is_slim(sample_project):
    data = inspect(sample_project).classes().to_dict()
    user = next(c for c in data["elements"]["classes"] if c["name"] == "User")
    assert "children" not in user and "signature" not in user
    assert "tree" not in data


def test_json_is_not_terminal_text(sample_project):
    result = inspect(sample_project).files()
    assert "├" not in result.to_json()
    json.loads(result.to_json())


def test_variables_json_keeps_scope(sample_project):
    data = inspect(sample_project).variables().to_dict()
    assert {v["scope"] for v in data["elements"]["variables"]} == {"module", "class", "instance", "local"}


# ------------------------------------------------------------------------- save
def test_save_json_roundtrip(sample_project, tmp_path):
    out = tmp_path / "classes.json"
    saved = inspect(sample_project).classes().save(format="json", path=out)
    assert saved == out.resolve()
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert [c["name"] for c in loaded["elements"]["classes"]] == ["Product", "User"]


def test_save_after_query(sample_project, tmp_path):
    out = tmp_path / "structure.json"
    inspect(sample_project).query(type=["classes", "functions", "methods"], details=True).save(
        format="json", path=str(out)
    )
    assert set(json.loads(out.read_text())["elements"]) == {"classes", "functions", "methods"}


def test_save_files(sample_project, tmp_path):
    out = tmp_path / "files.json"
    inspect(sample_project).files().save(format="json", path=out)
    assert json.loads(out.read_text())["tree"]["name"] == "MyProject"


def test_save_overwrites_atomically_and_leaves_no_temp_files(sample_project, tmp_path):
    out = tmp_path / "r.json"
    out.write_text("old")
    inspect(sample_project).files().save(format="json", path=out)
    assert out.read_text().startswith("{")
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".fou-")] == []


@pytest.mark.parametrize("fmt", ["yaml", "", None, 3])
def test_save_bad_format(sample_project, tmp_path, fmt):
    with pytest.raises(InvalidSaveFormatError, match="Supported formats: json"):
        inspect(sample_project).files().save(format=fmt, path=tmp_path / "x.json")


def test_save_format_is_case_insensitive(sample_project, tmp_path):
    inspect(sample_project).files().save(format="JSON", path=tmp_path / "x.json")


def test_save_bad_paths(sample_project, tmp_path):
    r = inspect(sample_project).files()
    with pytest.raises(InvalidSavePathError):
        r.save(format="json")
    with pytest.raises(InvalidSavePathError):
        r.save(format="json", path="")
    with pytest.raises(InvalidSavePathError):
        r.save(format="json", path=tmp_path)  # a directory
    with pytest.raises(InvalidSavePathError, match="does not exist"):
        r.save(format="json", path=tmp_path / "missing" / "x.json")
    with pytest.raises(InvalidSavePathError):
        r.save(format="json", path=12)


# ------------------------------------------------------------------ caching
def test_project_is_scanned_and_parsed_once(sample_project, monkeypatch):
    import fou.inspection.analysis as analysis
    import fou.inspection.inspector as inspector

    scans, parses = [], []
    real_scan, real_parse = inspector.scan, analysis.parse_python
    monkeypatch.setattr(inspector, "scan", lambda o: scans.append(1) or real_scan(o))
    monkeypatch.setattr(analysis, "parse_python", lambda *a: parses.append(a[1]) or real_parse(*a))

    p = inspect(sample_project)
    p.files(); p.classes(); p.functions(); p.imports(); p.query(type="all")
    assert len(scans) == 1
    assert len(parses) == len(set(parses)) == 6


def test_files_without_lines_does_not_read_or_parse(sample_project, monkeypatch):
    import fou.inspection.inspector as inspector

    def boom(*a, **k):
        raise AssertionError("analysis must not run")

    monkeypatch.setattr(inspector, "analyze_file", boom)
    inspect(sample_project).files(show_lines=False)


def test_refresh_reanalyzes_only_changed_files(sample_project):
    p = inspect(sample_project)
    assert len(p.functions().elements) == 5
    untouched = next(f for f in p._model.files if f.path == "main.py")
    (sample_project / "config.py").write_text("DEBUG = True\n\ndef added():\n    pass\n")
    stale = p.functions()
    assert len(stale.elements) == 5  # cached until refresh()
    p.refresh()
    assert len(p.functions().elements) == 6
    assert next(f for f in p._model.files if f.path == "main.py").elements is untouched.elements
    (sample_project / "new.py").write_text("def brand_new(): pass\n")
    assert "brand_new" in [e.name for e in p.refresh().functions().elements]
