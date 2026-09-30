# xprobe

Single-file, standard-library Python toolkit for text search, boundary-case probing, and failure-oriented test support. Importable, CLI-ready, and easy to vendor.

## Design

The canonical artifact is `xprobe.py`: copy it to `vendor/xprobe.py` without pip or supporting modules. Like `markdown` and `ascii_artist`, the artifact provides functions, `__all__`, and `__version__`; it has no main/CLI and performs no I/O on import. The optional CLI lives in `scripts/xprobe_cli.py`.

Python target: 3.10–3.14. Tests use external development dependencies under `tests/requirements.txt`; runtime uses the standard library only.

## Public API

| Function | Contract |
| --- | --- |
| `search_text(text, pattern, ...)` | Literal by default; optional regex/case folding; line/column coordinates start at 1, end column exclusive. Returns non-overlapping, line-local matches. |
| `search_files(root, pattern, ...)` | Sorted file/directory traversal with matches, skipped files, errors and a truncation flag. UTF-8 by default. |
| `boundary_cases(kind="text")` | Fresh named text or number inputs, including empty/NUL/Unicode or negative/zero/type boundaries. |
| `run_cases(function, cases)` | Execute caller-supplied `function(value)` against explicit expected values or exception types. Aggregate pass/fail and raw observed results. |

```python
import xprobe

matches = xprobe.search_text("日本語 TODO\n", "TODO")
report = xprobe.search_files(".", "TODO", max_matches=100)
assert xprobe.run_cases(int, [
    {"name": "valid", "value": "42", "expected": 42},
    {"name": "invalid", "value": "x", "raises": ValueError},
])["passed"]

# Presets supply inputs; callers decide the expected behavior of their target.
inputs = xprobe.boundary_cases("text")
```

## Supported / unsupported

- File search excludes hidden entries by default, skips symlinks/special files, binary/NUL, oversized and undecodable files. Explicit root files are searched regardless of their name. Skips and read errors are distinct from an empty match set.
- Positive byte/match limits are required. File truncation is reported only if another match exists after the limit. `search_text` returns a capped list; it has no truncation metadata.
- Regex uses Python `re`, without a timeout. Patterns and directory trees should be trusted. Filesystem races are not isolated; this is not a hardened sandbox for hostile changing trees.
- No `.gitignore` interpretation, multiline regex, overlap search, AST/semantic analysis, automatic target discovery, fuzzing engine or subprocess execution.
- `run_cases` validates all case specifications before calling the target. It runs in the current process: targets can have side effects or hang. There is no rollback, isolation or timeout. `KeyboardInterrupt` and `SystemExit` propagate. Empty case lists pass vacuously; they do not prove coverage.
- Expected-value comparisons use Python equality. Results may contain arbitrary Python values and are not necessarily JSON serializable.

## CLI

```sh
python scripts/xprobe_cli.py TODO . --max-matches 100
python scripts/xprobe_cli.py 'TODO|FIXME' . --regex
```

The CLI searches only; it never imports or executes discovered project code. Output is JSON with escaped control characters. Exit codes: 0 = matches, 1 = no matches, 2 = invalid input or read errors. Skips/truncation are visible in JSON even when exit code is 0/1.

## Tests

```sh
python -m pip install -r tests/requirements.txt
python -m pytest --cov=xprobe --cov-branch --cov-report=term-missing --cov-fail-under=90
```

Tests cover literal/regex/Unicode/CRLF coordinates, byte/match boundaries, hidden/binary/encoding behavior, read errors, symlinks, explicit probe expectations, malformed cases, CLI exit codes and copy-one-file import from another directory. CI runs Python 3.10–3.14 on Linux and Python 3.12 on Windows/macOS.
