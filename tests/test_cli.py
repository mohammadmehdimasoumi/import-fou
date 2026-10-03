import json

from fou.cli import main


def test_cli_prints_tree(sample_project, capsys):
    assert main(["inspect", str(sample_project)]) == 0
    assert capsys.readouterr().out.startswith("Project: MyProject")


def test_cli_types_details_json_output(sample_project, capsys, tmp_path):
    out = tmp_path / "o.json"
    code = main(["inspect", str(sample_project), "-t", "classes,methods", "-d", "--json", "-o", str(out)])
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["query"]["types"] == ["classes", "methods"]
    assert json.loads(out.read_text())["query"]["details"] is True


def test_cli_options(sample_project, capsys):
    main(["inspect", str(sample_project), "--depth", "0", "--no-lines"])
    text = capsys.readouterr().out
    assert "main.py" in text and "models" not in text and "->" not in text
    main(["inspect", str(sample_project), "-e", ".txt", "-e", ".json"])
    assert "notes.txt" in capsys.readouterr().out


def test_cli_reports_errors_without_traceback(tmp_path, capsys):
    assert main(["inspect", str(tmp_path / "nope")]) == 2
    assert "fou: error:" in capsys.readouterr().err
    assert main(["inspect", str(tmp_path), "--depth", "-1"]) == 2
    assert main(["inspect", str(tmp_path), "-t", "bogus"]) == 2
