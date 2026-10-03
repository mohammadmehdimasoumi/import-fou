"""Quick start: inspect the tutorial project in five lines.

Run from the repository root:  python examples/01_quickstart.py
"""
from pathlib import Path

from fou import inspect

project = inspect(Path(__file__).parent / "shop")   # instant: nothing is scanned yet

print(project.files())                              # file tree + code-line counts
print(project.classes(details=True))                # classes, their methods and docstrings

result = project.query(type=["classes", "constants"])
print(len(result["classes"]), "classes,", len(result["constants"]), "constants")
