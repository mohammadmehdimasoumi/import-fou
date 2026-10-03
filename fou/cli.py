"""Command-line interface:  ``fou inspect ./project --type classes --details``."""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from ._version import __version__
from .core.errors import FouError
from .inspection import SUPPORTED_TYPES, inspect


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fou", description="Fou - developer-controlled codebase inspection."
    )
    parser.add_argument("--version", action="version", version=f"fou {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    ins = sub.add_parser("inspect", help="Show the structure of a project.")
    ins.add_argument("location", nargs="?", default=".", help="Project directory (default: .)")
    ins.add_argument("--depth", default="all", help='"all" (default) or a non-negative integer.')
    ins.add_argument(
        "-e", "--ext", action="append", dest="extensions", metavar="EXT",
        help='Extension to inspect, repeatable (e.g. -e .py -e .json) or "all". Default: .py',
    )
    ins.add_argument(
        "-x", "--exclude", action="append", metavar="PATTERN",
        help="Glob to exclude, repeatable. Replaces the default exclude list.",
    )
    ins.add_argument("--hidden", action="store_true", help="Include hidden files and directories.")
    ins.add_argument(
        "-t", "--type", action="append", dest="types", metavar="TYPE",
        help=f'Inspection type(s), repeatable or comma-separated, or "all". '
             f'Default: files. Choices: {", ".join(SUPPORTED_TYPES)}.',
    )
    ins.add_argument("-d", "--details", action="store_true", help="Show additional detail.")
    ins.add_argument("--no-lines", action="store_true", help="Hide line counts in the file tree.")
    ins.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    ins.add_argument(
        "--links", choices=("auto", "always", "never"), default="auto",
        help="Make files and elements clickable terminal hyperlinks. 'auto' (default) "
             "only on an interactive terminal; env FOU_LINKS=always|never overrides auto.",
    )
    ins.add_argument(
        "--editor", metavar="SCHEME",
        help="Where a click goes: file (default), vscode, vscode-insiders, cursor, pycharm, "
             "idea, sublime, textmate, or a template like 'vscode://file{path}:{line}:{col}'. "
             "Default also from env FOU_LINK_SCHEME.",
    )
    ins.add_argument("-o", "--output", metavar="PATH", help="Also save the result as JSON.")
    return parser


def _parse_depth(raw: str):
    try:
        return int(raw)
    except ValueError:
        return raw  # let validation produce the error for non-"all" strings


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        project = inspect(
            args.location,
            depth=_parse_depth(args.depth),
            extensions=args.extensions,
            exclude=args.exclude,
            hidden=args.hidden,
        )
        types: List[str] = []
        for chunk in args.types or ["files"]:
            types.extend(part for part in chunk.split(",") if part.strip())
        requested = "all" if types == ["all"] else types
        result = project.query(type=requested, details=args.details, show_lines=not args.no_lines)
        if args.json:
            print(result.to_json())
        else:
            result.show(links=args.links, scheme=args.editor)
        if args.output:
            saved = result.save(format="json", path=args.output)
            print(f"Saved: {saved}", file=sys.stderr)
    except FouError as exc:
        print(f"fou: error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
