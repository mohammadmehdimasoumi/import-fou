"""Export a result to JSON and read it back.

Run from the repository root:  python examples/03_json_export.py
"""
import json
import tempfile
from pathlib import Path

from fou import inspect

project = inspect(Path(__file__).parent / "shop")
result = project.query(type=["classes", "methods"], details=True)

with tempfile.TemporaryDirectory() as tmp:
    saved = result.save(format="json", path=Path(tmp) / "structure.json")   # atomic write
    data = json.loads(Path(saved).read_text())

print("schema_version:", data["schema_version"])
print("summary       :", data["summary"]["counts"])
for cls in data["elements"]["classes"]:
    print(cls["fqn"], "line", cls["location"]["lineno"], "-", cls["code_lines"], "code lines")
