# Changelog

## 0.1.0

First public release. Ships the `inspect` module:

- nine inspection types (files, imports, functions, async_functions, classes,
  methods, variables, constants, decorators)
- `details=True` mode with signatures, docstrings, decorators and code-line counts
- tokenize-based code-line counting
- clickable terminal output (OSC 8) with editor schemes
- stable JSON output (`schema_version` 1.0) and atomic `save()`
- `fou` command line and `python -m fou`
- zero dependencies, typed package (`py.typed`)
