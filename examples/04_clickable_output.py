"""Clickable terminal output (OSC 8): click a class, land on its line in VS Code.

Run in a terminal that supports OSC 8 (iTerm2, Windows Terminal, VS Code terminal,
GNOME Terminal, kitty, WezTerm ...):

    python examples/04_clickable_output.py
"""
from pathlib import Path

from fou import inspect

project = inspect(Path(__file__).parent / "shop")
project.classes().show(links="always", scheme="vscode")   # try scheme="pycharm" too
