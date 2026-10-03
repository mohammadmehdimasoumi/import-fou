import os

import pytest

from fou import inspect


def paths(project, **kw):
    return [f.path for f in project.files(show_lines=False).files]


def test_default_scan_python_only_and_excludes_junk(sample_project):
    got = paths(inspect(sample_project))
    assert got == [
        "config.py",
        "main.py",
        "models/__init__.py",
        "models/product.py",
        "models/user.py",
        "utils/helper.py",
    ]


def test_files_before_directories_and_sorted(sample_project):
    tree = inspect(sample_project).files(show_lines=False).project.tree
    assert [f.name for f in tree.files] == ["config.py", "main.py"]
    assert [d.name for d in tree.dirs] == ["models", "utils"]


def test_depth_zero_means_root_files_only(sample_project):
    assert paths(inspect(sample_project, depth=0)) == ["config.py", "main.py"]


def test_depth_one_enters_one_level(sample_project):
    got = paths(inspect(sample_project, depth=1))
    assert "models/user.py" in got and "utils/helper.py" in got


def test_depth_limit_on_deep_tree(tmp_path):
    (tmp_path / "a/b/c").mkdir(parents=True)
    (tmp_path / "a/b/c/deep.py").write_text("x = 1")
    (tmp_path / "a/top.py").write_text("x = 1")
    assert paths(inspect(tmp_path, depth=1)) == ["a/top.py"]
    assert paths(inspect(tmp_path, depth=3)) == ["a/top.py", "a/b/c/deep.py"]
    assert paths(inspect(tmp_path)) == ["a/top.py", "a/b/c/deep.py"]


def test_extensions_multiple_and_all(sample_project):
    got = paths(inspect(sample_project, extensions=[".py", ".json"]))
    assert "data/settings.json" in got and "notes.txt" not in got
    everything = paths(inspect(sample_project, extensions="all"))
    assert "notes.txt" in everything and "data/settings.json" in everything
    assert "venv/lib.py" not in everything  # default excludes still apply


def test_hidden(sample_project):
    assert ".hidden/secret.py" not in paths(inspect(sample_project))
    assert ".hidden/secret.py" in paths(inspect(sample_project, hidden=True))


def test_exclude_replaces_defaults(sample_project):
    got = paths(inspect(sample_project, exclude=[]))
    assert "venv/lib.py" in got and "node_modules/pkg/index.py" in got


def test_exclude_names_globs_and_paths(sample_project):
    got = paths(inspect(sample_project, exclude=["models", "*.py"]))
    assert got == []
    got = paths(inspect(sample_project, exclude=["utils/helper.py", "venv"]))
    assert "utils/helper.py" not in got and "models/user.py" in got
    got = paths(inspect(sample_project, exclude=["main.py/"]))  # dir-only pattern
    assert "main.py" in got


def test_excluded_directories_are_pruned_not_scanned(sample_project, monkeypatch):
    scanned = []
    real = os.scandir

    def spy(path):
        scanned.append(os.path.basename(str(path)))
        return real(path)

    monkeypatch.setattr(os, "scandir", spy)
    inspect(sample_project, exclude=["node_modules", "venv"]).files(show_lines=False)
    assert "node_modules" not in scanned and "venv" not in scanned


def test_hidden_and_exclude_do_not_conflict(sample_project):
    got = paths(inspect(sample_project, hidden=True, exclude=[".hidden"]))
    assert ".hidden/secret.py" not in got


def test_empty_directories_are_hidden(tmp_path):
    (tmp_path / "empty").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/readme.md").write_text("x")
    (tmp_path / "a.py").write_text("x = 1")
    tree = inspect(tmp_path).files(show_lines=False).project.tree
    assert tree.dirs == []


def test_symlinks_are_not_followed(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "real/a.py").write_text("x = 1")
    try:
        os.symlink(tmp_path / "real", tmp_path / "loop")
        os.symlink(tmp_path / "real/a.py", tmp_path / "link.py")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    assert paths(inspect(tmp_path)) == ["real/a.py"]


def test_module_names(sample_project):
    files = {f.path: f.module for f in inspect(sample_project).files(show_lines=False).files}
    assert files["models/user.py"] == "models.user"
    assert files["models/__init__.py"] == "models"
    assert files["main.py"] == "main"
    assert files["utils/helper.py"] == "helper"  # utils/ has no __init__.py


def test_deterministic_order(sample_project):
    a = inspect(sample_project).query(type="all", details=True).to_json()
    b = inspect(sample_project).query(type="all", details=True).to_json()
    assert a == b


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="needs POSIX non-root")
def test_unreadable_directory_is_reported_not_fatal(sample_project):
    locked = sample_project / "utils"
    locked.chmod(0)
    try:
        result = inspect(sample_project).files(show_lines=False)
    finally:
        locked.chmod(0o755)
    assert any(e.phase == "scan" and e.path == "utils" for e in result.errors)
    assert "models/user.py" in [f.path for f in result.files]
