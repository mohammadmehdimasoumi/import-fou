# Fou – full reference

Fou is a **developer-controlled codebase inspection and navigation library**.
It is a deterministic tool, not an AI agent: you say exactly what you want to
see and Fou answers from the source code, the same way every time.

This release contains the **`inspect`** module only. It answers one question:

> *What exists inside this project, and what is its structure?*

`find`, `locate`, `run`, `relation` and other modules are future work. The
shared `fou.core` layer (locations, elements, results, errors) exists so they
can be built on the same project model.

Requires Python 3.9+. No dependencies.

## Quick start

```python
from fou import inspect

project = inspect(
    location="./my_project",
    depth="all",
    extensions=[".py"],
    exclude=[".git", "__pycache__", "venv", ".venv"],
    hidden=False,
)

print(project.files())                      # tree with code-line counts
project.files(show_lines=False)             # tree only
project.imports()
project.functions()
project.async_functions()
project.classes(details=True)
project.methods(details=True)
project.variables()
project.constants()
project.decorators()

result = project.query(type=["imports", "classes", "methods"], details=True)
result.save(format="json", path="./fou-result.json")
```

Command line:

```
fou inspect ./my_project                       # file tree
fou inspect . -t classes,methods -d            # details
fou inspect . -t all --json -o structure.json  # JSON to stdout and to a file
python -m fou inspect .                        # same thing
fou inspect . -t classes --editor vscode       # clickable output that opens VS Code at the line
```

## Results, not prints

Every method **returns** an `InspectionResult`; nothing is printed unless you
print it.

```python
result = project.classes()
len(result)              # number of classes found
for cls in result: ...   # Element objects (FileModel objects for files())
result["classes"]        # items by type
result.errors            # problems met on the way (scan continues)
str(result)              # human-readable text    (result.show() prints it)
result.to_dict()         # structured data        (result.to_json() -> str)
result.save(format="json", path="./classes.json")
```

The pipeline keeps the four concerns separate:

```
Filesystem -> scanner -> parser (ast) -> internal model -> InspectionResult
                                                           |- renderer   (terminal)
                                                           `- serializer (JSON)
```

## Clickable output

Every file and every element in the terminal output can be a **hyperlink that
opens the file at that exact line**:

```
inspection/reader.py                       <- click: opens the file
├── _normalize_newlines()  (line 19)       <- click: opens reader.py at line 19
├── _read_bytes()  (line 23)
├── read_python_source()  (line 31)
└── read_plain_text()  (line 44)
```

It uses *OSC 8* terminal hyperlinks (iTerm2, Windows Terminal, the VS Code
terminal, GNOME Terminal/VTE, kitty, WezTerm, Alacritty, foot, ... - the macOS
Terminal.app does not support them; inside tmux they need tmux 3.4+). Where a
click goes is decided by the **scheme**:

| scheme | opens | jumps to the line |
|---|---|---|
| `file` (default) | the OS default program for the file | no (a `file://` URL has no line) |
| `vscode`, `vscode-insiders`, `cursor` | that editor | yes |
| `pycharm`, `idea` | JetBrains IDE | yes |
| `sublime`, `textmate` | that editor | yes |
| any template | e.g. `"vscode://file{path}:{line}:{col}"` | whatever you build |

Template placeholders: `{path}` (absolute, percent-encoded, always starting
with `/`), `{fspath}` (same, without forcing the `/`), `{uri}` (a `file://` URI),
`{line}` and `{col}` (both 1-based).

```python
result = project.classes()
result.show()                               # links on an interactive terminal, plain in a pipe
result.show(scheme="vscode")                # click -> VS Code at the line
result.show(links="always", scheme="pycharm")
text = result.render(links=True, scheme="vscode")   # a string with the links inside
```

```
fou inspect . -t methods --editor vscode          # links are 'auto' (terminal only)
fou inspect . --links always --editor "vscode://file{path}:{line}:{col}"
export FOU_LINK_SCHEME=vscode                     # default scheme for everything
export FOU_LINKS=never                            # or "always": overrides --links auto
```

* `links` is `"auto"` (default for `show()` and the CLI: only when the output is
  a terminal and `TERM` is not `dumb`), `"always"`/`True` or `"never"`/`False`.
* `str(result)`, `result.render()` and the JSON **never** contain links unless
  you ask: pipes, files and tests stay clean. Stripping the escape sequences from
  a linked rendering gives exactly the plain rendering.
* An unknown scheme or template placeholder raises `InvalidOptionError`, also
  when links end up disabled, so a typo fails the same way everywhere.
* Directories are not linked (there is no line to jump to).

## Arguments and conventions

### `location`
Relative or absolute path, normalised internally. A missing, non-directory or
inaccessible path raises `LocationError` (never a raw `FileNotFoundError`).

### `depth`
`"all"` (default) or a non-negative integer = number of directory levels
**below the root** that are scanned.

| depth | scanned |
|---|---|
| `0` | files directly in the root only |
| `1` | + one level of sub-directories |
| `2` | + two levels, and so on |

Invalid values (`-1`, `1.5`, `True`, `"2"`) raise `InvalidDepthError`.

### `extensions`
Default `[".py"]`. A list (`[".py", ".json"]`, leading dot optional,
case-insensitive) or `"all"`. **Discovery and analysis are different things:**
only `.py` files are analysed for imports/functions/classes/...; other files
appear in `files()` and nothing else. For non-Python text files the line count
means *non-blank lines*; binary files show `-> binary`.

### `exclude`
Shell-style globs, applied **during traversal** (excluded directories are never
entered).

* no `/` in the pattern: matched against each file/directory *name* (`venv`, `*.egg-info`)
* with `/`: matched against the path relative to the root (`docs/build`)
* trailing `/`: directories only (`build/`)
* `exclude=None` (default) uses `fou.DEFAULT_EXCLUDE` (`.git`, `__pycache__`, `venv`, `.venv`, `node_modules`, `build`, `dist`, ...)
* `exclude=[]` excludes nothing; a list **replaces** the defaults (`[*fou.DEFAULT_EXCLUDE, "docs"]` extends them)

### `hidden`
`False` (default) skips names starting with `.`. `hidden=True` includes them;
`exclude` still applies on top, so the two never conflict. Symbolic links are
never followed. Directories with nothing to show are omitted from the tree.

### Ordering
Files first, then directories, each sorted case-insensitively - so output is
identical between runs and machines.

## What is recognised (Python)

| type | meaning |
|---|---|
| `files` | the project tree |
| `imports` | one entry per imported name: `import a.b as c`, `from x import y`, relative and `*` imports; `internal` tells whether it points into the project; details tell if it is conditional / `TYPE_CHECKING`-only |
| `functions` | `def` not directly in a class body (nested functions included) |
| `async_functions` | `async def` not directly in a class body |
| `methods` | any `def` / `async def` directly in a class body (`is_async` tells them apart; `method_type` is `instance`, `class`, `static` or `property`) |
| `classes` | `class` statements, nested ones included |
| `variables` | bindings with a **scope**: `module`, `class`, `instance` (`self.x = ...` in a method), `local` |
| `constants` | module- or class-level names matching `^_*[A-Z][A-Z0-9_]*$`, or annotated `Final`. `TypeVar`-style factories are excluded. Python has no real constants, so this is a naming/annotation convention. A constant never also appears under `variables` |
| `decorators` | each decorator, linked to the class/function/method it decorates; the expression is shown as written in the source |

Variable details: repeated assignments to the same name in the same scope are
merged into one entry (`assignment_count`); `global x` inside a function binds
the *module* variable. **Not recorded:** function parameters, comprehension
variables, `except ... as` names, `match` captures, lambda internals.

### Code-line counting
`-> 94 lines` means **94 lines of actual code**. Using `tokenize`:
blank lines, comment-only lines and docstring lines are *not* counted; every
physical line of a multi-line expression or a non-docstring string literal is.
The counts (`total`, `code`, `blank`, `comment`, `docstring`) are all available
in the JSON. A decorated definition's span starts at its first decorator.

## JSON output

`result.save(format="json", path=...)` writes structured data (not terminal
text); `format` is validated, the parent directory must exist, the write is
atomic. Layout (`schema_version` `"1.0"`):

```
{ schema_version, tool, tool_version, module, project{name, root, options}, query{types, details, show_lines},
  summary{files, directories, counts, errors},
  tree{...nested directories/files with lines...},          # when "files" was requested
  elements{ <type>: [ {id, kind, name, qualname, fqn, path, module,
                       location{lineno,col,end_lineno,end_col}, parent, scope, ...} ] },
  errors[ {path, phase, type, message, lineno, col} ] }
```

* Relationships are kept through stable `id`s (`"models/user.py::User.login"`; a repeated qualname gets `#2`, `#3`...): `parent` is the enclosing element, and with `details=True` `children` lists direct descendants and decorators are attached to their target.
* Paths are relative to the root with `/` separators. `col` values are 0-based **character** offsets.
* `details=True` adds signature/parameters/return type/docstring/bases/line counts/etc. It never changes *which* elements are returned.
* Line counts are computed lazily (see *Performance*): `code_lines` is only present on elements once a result was requested with `details=True` for functions, methods or classes (or `files()` with `show_lines`).

## Errors

| situation | behaviour |
|---|---|
| bad `location` | `LocationError` |
| bad `depth` / `extensions` / `exclude` / `type` | `InvalidDepthError` / `InvalidExtensionsError` / `InvalidExcludeError` / `InvalidInspectionTypeError` (all `FouError` and `ValueError`) |
| bad save `format` / `path` | `InvalidSaveFormatError` / `InvalidSavePathError` (`SaveError`) |
| unreadable directory, undecodable or syntactically invalid file | **not raised**: recorded in `result.errors`, the rest of the project is still inspected |

## Performance

* The filesystem is scanned once; each file is read and parsed at most once; all
  methods share that cache. Elements are indexed by type once per scan, so after
  the first query `classes()`, `functions()`, `imports()`, ... return immediately
  instead of walking the whole tree again.
* **Line counting is lazy.** Counting code lines needs a `tokenize` pass that costs
  as much as parsing. It only runs when a result actually shows line counts:
  `files()` (unless `show_lines=False`) and `details=True` on functions,
  methods, classes or async functions. `classes()`, `imports()`,
  `variables(details=True)`, ... skip it, and a file is never counted twice.
* `files(show_lines=False)` reads no file contents at all.
* After editing files call `project.refresh()`: files whose size and mtime are
  unchanged keep their analysis (parse result *and* line counts).

Measured on the Python standard library (515 files, ~48k elements, one core,
Python 3.12; best of 3): a cold `classes()` takes ~2.3 s (of which ~1.0 s is
`ast.parse` itself), every later query ~0 s, and counting lines for everything
adds ~1.4 s once. A full cold `query(type="all", details=True)` takes ~4 s.
`result.save()` of that 45 MB JSON adds ~1.4 s (the standard `json` module's
indented writer is pure Python).

## Known limitations

* Static analysis only: `setattr`, `exec`, dynamically created classes and names generated by decorators are invisible.
* Source must parse with the Python version running Fou (newer syntax on an older interpreter is reported as a parse error for that file).
* A file with a syntax error yields no elements (only an error and an approximate line count).
* Only `.py` files are analysed; `.pyi` and notebooks are not.
* `module` names come from `__init__.py` files; namespace packages without them are named by file only.

## Layout and development

```
fou/core/        Location, Element/FileModel/DirNode/ProjectModel, Result base class, errors
fou/inspection/  options, scanner, reader, linecount, parser, analysis, inspector,
                 result, renderer, serializer, links
fou/_version.py  the version (single source; pyproject.toml reads it)
fou/cli.py       command line
tests/           pytest suite
```

```
pip install -e ".[dev]"
pytest
```

New modules (`find`, `relation`, ...) should consume `ProjectModel`/`Element`,
return a `fou.core.Result` subclass (which provides `save()`), and reuse
`Location`.
