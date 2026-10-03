"""Four small recipes built on plain Python + Fou results.

Run from the repository root:  python examples/02_recipes.py
"""
from collections import Counter
from pathlib import Path

from fou import inspect

project = inspect(Path(__file__).parent / "shop")

# 1. Which third-party packages does the project import?
external = Counter()
for imp in project.imports(details=True):
    if not imp.attrs.get("internal"):
        external[(imp.attrs.get("module") or imp.name).split(".")[0]] += 1
print("== external packages ==")
for package, count in external.most_common():
    print(f"{package:<12} {count}")

# 2. Definitions without a docstring
missing = [
    el for el in project.query(type=["classes", "functions", "methods"], details=True)
    if not el.details.get("docstring")
]
print(f"\n== {len(missing)} definitions without a docstring ==")
for el in missing:
    print(f"{el.path}:{el.location.lineno} {el.kind:<8} {el.qualname}")

# 3. The longest functions (code lines only, no blanks/docstrings)
defs = list(project.query(type=["functions", "methods"], details=True))
defs.sort(key=lambda el: el.details["code_lines"], reverse=True)
print("\n== longest functions ==")
for el in defs[:3]:
    print(f"{el.details['code_lines']:>3} lines {el.path}:{el.location.lineno} {el.qualname}")

# 4. A Markdown API index
print("\n== API index ==")
for cls in project.classes(details=True):
    doc = cls.details["docstring"] or "No docstring"
    print(f"- `{cls.module}.{cls.qualname}` ({cls.path}:{cls.location.lineno}): {doc}")
    for child in cls.children:
        if child.kind == "method":
            print(f"  - `{child.name}`")
