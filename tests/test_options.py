import pytest

from fou import (
    FouError,
    InvalidDepthError,
    InvalidExcludeError,
    InvalidExtensionsError,
    InvalidInspectionTypeError,
    LocationError,
    inspect,
)
from fou.inspection.options import (
    DEFAULT_EXCLUDE,
    SUPPORTED_TYPES,
    normalize_depth,
    normalize_exclude,
    normalize_extensions,
    normalize_types,
)


def test_missing_location_raises_dedicated_error(tmp_path):
    with pytest.raises(LocationError, match="does not exist"):
        inspect(location=tmp_path / "nope")


def test_file_location_is_rejected(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1")
    with pytest.raises(LocationError, match="not a directory"):
        inspect(location=f)


@pytest.mark.parametrize("bad", ["", "   ", None, 5, b"x"])
def test_bad_location_types(bad):
    with pytest.raises(LocationError):
        inspect(location=bad)


def test_errors_share_a_base_class(tmp_path):
    with pytest.raises(FouError):
        inspect(location=tmp_path / "nope")
    with pytest.raises(ValueError):  # option errors are also ValueErrors
        normalize_depth(-1)


def test_relative_and_absolute_paths_are_normalized(sample_project, monkeypatch):
    monkeypatch.chdir(sample_project.parent)
    relative = inspect(location="./MyProject")
    absolute = inspect(location=str(sample_project))
    assert relative.options.location == absolute.options.location
    assert relative.name == "MyProject"


@pytest.mark.parametrize("value,expected", [("all", None), ("ALL", None), (0, 0), (3, 3)])
def test_depth_valid(value, expected):
    assert normalize_depth(value) == expected


@pytest.mark.parametrize("bad", [-1, 1.5, True, False, "2", "deep", None, [1]])
def test_depth_invalid(bad):
    with pytest.raises(InvalidDepthError):
        normalize_depth(bad)


def test_extensions():
    assert normalize_extensions(None) == (".py",)
    assert normalize_extensions("all") is None
    assert normalize_extensions(["all"]) is None
    assert normalize_extensions(["py", ".JSON", ".py"]) == (".py", ".json")
    assert normalize_extensions(".yaml") == (".yaml",)


@pytest.mark.parametrize("bad", [[], 5, [1], ["."], [""], ["a/b"], ["*.py"], ["all", ".py"]])
def test_extensions_invalid(bad):
    with pytest.raises(InvalidExtensionsError):
        normalize_extensions(bad)


def test_exclude_semantics():
    assert normalize_exclude(None) == DEFAULT_EXCLUDE
    assert normalize_exclude([]) == ()
    assert normalize_exclude(["./build", "build", "docs\\api/"]) == ("build", "docs/api/")


@pytest.mark.parametrize("bad", [5, [1], [""], ["/"], ["."]])
def test_exclude_invalid(bad):
    with pytest.raises(InvalidExcludeError):
        normalize_exclude(bad)


def test_types():
    assert normalize_types("all") == SUPPORTED_TYPES
    assert normalize_types(["methods", "classes", "methods"]) == ("methods", "classes")
    assert normalize_types("Classes") == ("classes",)


@pytest.mark.parametrize("bad", [[], 5, ["nope"], [1], ["all", "classes"]])
def test_types_invalid(bad):
    with pytest.raises(InvalidInspectionTypeError):
        normalize_types(bad)


def test_types_typo_suggestion():
    with pytest.raises(InvalidInspectionTypeError, match="Did you mean 'classes'"):
        normalize_types(["clases"])


def test_hidden_must_be_bool(sample_project):
    with pytest.raises(FouError):
        inspect(sample_project, hidden="yes")
