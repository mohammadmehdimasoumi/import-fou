import io
import re

import pytest

from fou import inspect
from fou.cli import main
from fou.core.errors import InvalidOptionError
from fou.inspection.links import LinkBuilder, hyperlink, resolve_template, wants_links

OSC_OPEN = re.compile(r"\x1b\]8;;([^\x1b]*)\x1b\\")
OSC_ANY = re.compile(r"\x1b\]8;;[^\x1b]*\x1b\\")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("FOU_LINK_SCHEME", raising=False)
    monkeypatch.delenv("FOU_LINKS", raising=False)


def strip_links(text):
    return OSC_ANY.sub("", text)


# ------------------------------------------------------------------ URLs
def test_builtin_scheme_urls(tmp_path):
    root = str(tmp_path)
    assert LinkBuilder(root, "vscode").url("a/b.py", 12, 4) == f"vscode://file{root}/a/b.py:12:5"
    assert LinkBuilder(root, "cursor").url("a.py", 3) == f"cursor://file{root}/a.py:3:1"
    assert (
        LinkBuilder(root, "pycharm").url("a/b.py", 12, 4)
        == f"pycharm://open?file={root}/a/b.py&line=12&column=5"
    )
    assert LinkBuilder(root, "file").url("a/b.py", 99) == (tmp_path / "a" / "b.py").as_uri()
    assert LinkBuilder(root, "VSCode").url("x.py").startswith("vscode://")  # case-insensitive


def test_special_characters_are_percent_encoded(tmp_path):
    root = tmp_path / "my proj"
    builder = LinkBuilder(str(root), "vscode")
    url = builder.url("pkg/a&b #1.py", 2)
    assert "my%20proj" in url and "a%26b%20%231.py" in url
    assert " " not in url and "&" not in url
    assert builder.url("é.py").endswith("%C3%A9.py:1:1")


def test_custom_template_and_validation(tmp_path):
    builder = LinkBuilder(str(tmp_path), "myeditor://open/{fspath}?l={line}&c={col}")
    assert builder.url("a.py", 7, 0) == f"myeditor://open/{tmp_path}/a.py?l=7&c=1"
    with pytest.raises(InvalidOptionError, match="Unknown placeholder"):
        resolve_template("x://{nope}")
    with pytest.raises(InvalidOptionError, match="Did you mean 'vscode'"):
        resolve_template("vscod")
    for bad in ["", "   ", 5]:
        with pytest.raises(InvalidOptionError):
            resolve_template(bad)


def test_scheme_default_comes_from_environment(monkeypatch, tmp_path):
    assert LinkBuilder(str(tmp_path)).url("a.py").startswith("file://")
    monkeypatch.setenv("FOU_LINK_SCHEME", "vscode")
    assert LinkBuilder(str(tmp_path)).url("a.py").startswith("vscode://")
    assert LinkBuilder(str(tmp_path), "pycharm").url("a.py").startswith("pycharm://")  # explicit wins


def test_hyperlink_escape_sequence_and_sanitising():
    assert hyperlink("txt", "x://y") == "\x1b]8;;x://y\x1b\\txt\x1b]8;;\x1b\\"
    assert "\x1b]" not in hyperlink("t", "x://a\x1b]8;;evil\x07").split("\x1b\\")[0][4:]
    assert OSC_OPEN.search(hyperlink("t", "x://a\x07b")).group(1) == "x://ab"


# --------------------------------------------------------------- when to link
def test_wants_links_modes(monkeypatch):
    class Tty(io.StringIO):
        def isatty(self):
            return True

    assert wants_links(True, io.StringIO()) is True and wants_links(False, Tty()) is False
    assert wants_links("always", io.StringIO()) is True and wants_links("never", Tty()) is False
    assert wants_links("auto", Tty()) is True and wants_links("auto", io.StringIO()) is False
    monkeypatch.setenv("TERM", "dumb")
    assert wants_links("auto", Tty()) is False
    monkeypatch.setenv("FOU_LINKS", "always")
    assert wants_links("auto", io.StringIO()) is True
    monkeypatch.setenv("FOU_LINKS", "never")
    assert wants_links("auto", Tty()) is False
    with pytest.raises(InvalidOptionError):
        wants_links("sometimes", Tty())
    with pytest.raises(InvalidOptionError):
        wants_links(1, Tty())


# ----------------------------------------------------------------- rendering
def test_plain_output_never_contains_escapes(sample_project):
    result = inspect(sample_project).query(type="all", details=True)
    assert "\x1b" not in str(result) and "\x1b" not in result.render()
    assert "\x1b" not in result.to_json()


def test_linked_output_is_plain_output_plus_escapes(sample_project):
    p = inspect(sample_project)
    for result in (
        p.files(),
        p.files(show_lines=False),
        p.query(type="all", details=True),
        p.classes(),
        p.methods(details=True),
    ):
        assert strip_links(result.render(links=True, scheme="vscode")) == str(result)


def test_every_element_and_file_header_is_a_link(sample_project):
    p = inspect(sample_project)
    result = p.query(type=["classes", "methods", "functions"])
    text = result.render(links=True, scheme="vscode")
    urls = OSC_OPEN.findall(text)
    non_empty = [u for u in urls if u]
    # each type section repeats a header for every file that has items of that type
    headers = sum(len({e.path for e in items}) for items in result.groups.values())
    assert headers > 0
    assert len(non_empty) == len(result.elements) + headers
    root = str(sample_project.resolve())
    assert f"vscode://file{root}/models/user.py:1:1" in non_empty  # file header: line 1
    login = next(e for e in result.elements if e.qualname == "User.login")
    assert f"vscode://file{root}/models/user.py:{login.location.lineno}:{login.location.col + 1}" in non_empty


def test_the_clicked_line_is_the_line_shown(sample_project):
    text = inspect(sample_project).functions().render(links=True, scheme="vscode")
    for line in text.split("\n"):
        urls = [u for u in OSC_OPEN.findall(line) if u]
        shown = re.search(r"\(line (\d+)\)", strip_links(line))
        if shown and urls:
            assert urls[0].split(":")[-2] == shown.group(1)


def test_file_tree_links_files_not_directories(sample_project):
    text = inspect(sample_project).files().render(links=True)
    urls = [u for u in OSC_OPEN.findall(text) if u]
    assert urls and all(u.startswith("file://") for u in urls)
    assert any(u.endswith("/models/user.py") for u in urls)
    assert not any(u.endswith("/models") or u.endswith("/utils") for u in urls)


def test_nested_details_children_are_linked(sample_project):
    result = inspect(sample_project).classes(details=True)
    text = result.render(links=True, scheme="vscode")
    assert strip_links(text) == str(result)
    assert any(":" in u for u in OSC_OPEN.findall(text) if u)


def test_show_adds_links_only_when_wanted(sample_project):
    result = inspect(sample_project).functions()
    plain, forced, off = io.StringIO(), io.StringIO(), io.StringIO()
    result.show(file=plain)  # auto + StringIO is not a terminal
    result.show(file=forced, links="always", scheme="vscode")
    result.show(file=off, links="never")
    assert "\x1b" not in plain.getvalue() and "\x1b" not in off.getvalue()
    assert "vscode://file" in forced.getvalue()
    assert strip_links(forced.getvalue()) == plain.getvalue()


def test_scheme_is_validated_even_when_links_are_off(sample_project):
    result = inspect(sample_project).classes()
    with pytest.raises(InvalidOptionError):
        result.render(links=False, scheme="nope")
    with pytest.raises(InvalidOptionError):
        result.show(file=io.StringIO(), links="never", scheme="nope")


# ----------------------------------------------------------------------- CLI
def test_cli_links_flags(sample_project, capsys):
    assert main(["inspect", str(sample_project), "-t", "classes"]) == 0
    assert "\x1b" not in capsys.readouterr().out  # captured stdout is not a terminal
    assert main(["inspect", str(sample_project), "-t", "classes", "--links", "always", "--editor", "vscode"]) == 0
    out = capsys.readouterr().out
    assert "vscode://file" in out and "\x1b]8;;" in out
    assert main(["inspect", str(sample_project), "--links", "always"]) == 0
    assert "file://" in capsys.readouterr().out
    assert main(["inspect", str(sample_project), "--json", "--links", "always"]) == 0
    assert "\x1b" not in capsys.readouterr().out


def test_cli_bad_editor_is_a_clean_error(sample_project, capsys):
    assert main(["inspect", str(sample_project), "--editor", "emacs-ish"]) == 2
    err = capsys.readouterr().err
    assert "fou: error:" in err and "Unknown link scheme" in err
