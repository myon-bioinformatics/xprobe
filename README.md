# xprobe

For native pytest outcomes (including xfail/xpass and execution phases), see
[pytest observations and exploration](docs/pytest-observations.md). The opt-in
test adapter emits JSONL readable by the existing corpus and search helpers.

Single-file, standard-library Python toolkit for text search, boundary-case probing, and failure-oriented test support. Importable, CLI-ready, and easy to vendor.

## Design

The canonical artifact is `xprobe.py`: copy it to `vendor/xprobe.py` without pip or supporting modules. It provides functions, `__all__`, and `__version__`; import performs no I/O. Direct execution provides a read-only overview. The advanced CLI remains in `scripts/xprobe_cli.py`.

## Start without options (0.3)

```sh
python xprobe.py
python -S /path/to/xprobe.py
```

This is a daily-use standalone tool, not a test-environment bootstrapper.
The current working directory is the scope, not the directory containing the
script. The default summarizes configuration categories (no values/key names)
and literal source clues with file/line locations and practical next checks.
TODO/FIXME, unimplemented code, shell execution, dynamic eval/exec and bare
except are review clues, not defects: comments/strings can also match.
It never launches pytest, builds, Git, a browser, network requests or repairs.
Copying this one file elsewhere retains the direct entry point.

The overview is shallow: immediate text/configuration files at the root,
`.github/workflows`, `src`, `lib`, `tool`, and `scripts`. It is not
a complete recursive inventory. No reports, environment variables or project
code execution are needed. Python alone is sufficient; no pip install.
Per-location entries are bounded at 200, per-file reads at 1 MB; symlinks are
skipped (filesystem races are not isolated). Limits are configurable with
`--root`, `--max-entries` and `--max-bytes`. Names of report/error files can
identify projects; review before sharing.

For broader literal search, use `python xprobe.py --search TEXT --root PATH`.
This explicit mode returns raw matching lines, like grep; review sensitive
contents before sharing. It does not execute any discovered command.

Optional `python xprobe.py --evidence` also reads immediate XML/JSONL files in
`reports` and `test-results`. These files are neither required nor generated
automatically. Default operation never reads them, including malformed reports.
JUnit contributes failure identities, not completion proof. Native pytest
counts describe phases, not final test totals. Missing finish, dropped events,
mixed run identities, malformed reports and limits are visible; none imply
success. Completed evidence can still contain failed tests. Exit 0 means the
overview was observed, not tests passed; exit 2 means invalid/incomplete
observation. Optional report absence is not a setup problem. No report is
different from a report with zero failures.

Suggested checks are rules based on observed outcomes, not inferred causes,
command-frequency telemetry, reconstructed inputs or a security verdict.
Existing search APIs/CLI remain available unchanged.

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

## Configuration discovery and regression corpus (0.2)

The original xgrep/xfail goal goes beyond ad-hoc grep: locate configuration clues using built-in vocabulary, then retain explained failures for repeatable tests and AI troubleshooting. The single artifact now provides:

| API | Behavior |
| --- | --- |
| `inspect_text(text)` | Built-in header words, secret-like key phrases, config terms and URL schemes; source/line/column and key classification only. |
| `scan_config(root, ...)` | Include globs, excluded directory names/relative paths, hidden .env support, byte/finding bounds and explicit errors/skips/incompleteness. |
| `inspect_environment(mapping)` | Recognized variable names and empty/present status, with all values omitted. Caller explicitly supplies the mapping. |
| `known_bad_cases(category=None)` | Stable, explained regressions for Git SHA, NUL, Markdown, paths, URLs, SQL and JSON. |
| `generate_cases(seed=0, count=20, category=None)` | Seeded sampling of that corpus with unique IDs and origin IDs; does not alter global RNG state. |
| `merge_cases(*corpora)` | Validate/deduplicate recorded inputs; reject conflicting IDs and non-finite/non-round-tripping JSON values. |
| `corpus_to_json` / `corpus_from_json` | Stable JSON or JSONL persistence; pure serialization, no automatic file writes or execution. |
| `cases_from_junit(text)` | Import pytest-compatible JUnit failure/error identities, omitting logs, messages and parameter labels. |

```python
import xprobe

report = xprobe.scan_config(".")
fixtures = xprobe.merge_cases(xprobe.known_bad_cases(), [{
    "id": "my-regression-1", "category": "regression", "value": "original input",
    "reason": "Describe the observed failure and the regression being prevented",
}])
encoded = xprobe.corpus_to_json(fixtures, jsonl=True)
assert xprobe.corpus_from_json(encoded, jsonl=True) == fixtures
```

```sh
python scripts/xprobe_cli.py --scan-config --root . --include '*.yaml'
python scripts/xprobe_cli.py --env-report
python scripts/xprobe_cli.py --corpus --category git --seed 7 --count 20 --format jsonl
python -m pytest --junitxml=pytest-results.xml
python scripts/xprobe_cli.py --junit pytest-results.xml
```

Discovery output deliberately omits **all values and surrounding lines**, including URLs, query strings and credentials. Classification is heuristic evidence, not a complete parser or a credential verdict. Source paths/key names themselves can identify projects; choose inputs before sharing. The legacy explicit `search_text` / `search_files` APIs return raw text and are unsuitable for sharing sensitive inputs without caller review.

Discovery defaults exclude .git, .venv, venv, node_modules, __pycache__, build and dist. Filters replace the defaults when supplied. A bounded candidate-line scan can stop before finding enough classified keys: `truncated` and `truncation_reason=candidate_limit` explicitly mark incomplete discovery; `finding_limit` marks a finding bound. Skipped/read-error files do not prove absence of configuration. This is line-based UTF-8 heuristic discovery, without a hostile-filesystem sandbox or multiline config parsing.

Corpus inputs are **not** universal rejection expectations. `run_cases` still requires the caller's explicit expected value or exception. JUnit identifies failed tests but normally cannot reconstruct their original inputs: record the input explicitly in a separate case. Corpus persistence can contain sensitive user-supplied input; unlike discovery, corpus serialization is faithful. Generated cases sample existing regression classes; they do not implement a fuzzing engine. JUnit parsing is byte/case bounded, rejects DTD/entity declarations and does not evaluate code.

For cross-repository use, `cases_from_junit` accepts explicit `repository`,
`commit_sha` (full SHA from canonical metadata) and `report_id`. These scope case
IDs so matching test names from different repositories/jobs do not collide.
Missing SHA stays null. See [cross-repository collection](docs/cross-repository-tests.md).
Both new repositories' CI now preserve JUnit reports even when tests fail;
xprobe also emits the shared importer's compact failure JSON.
