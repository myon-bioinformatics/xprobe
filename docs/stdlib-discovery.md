# Convention-driven discovery beyond tests

Inject the conventions used by the project: filenames, Python names, kinds,
and directories to leave out. Nothing requires a `tests/` directory, a
`TestCase` subclass or a `test_*` prefix.

```sh
# Arbitrary files: config, workflows, data manifests, docs, images, etc.
python -S xprobe.py --discover --root ../project --include '*.yml' --include '*.json' --include-hidden --brief
# Production Python, with multiple naming rules (OR).
python -S xprobe.py --symbols ../project --exclude-dir tests --exclude-dir vendor --symbol-pattern 'load_*' --symbol-pattern 'validate_*' --brief
# Class families rather than methods; repeat --symbol-kind for OR.
python -S xprobe.py --symbols ../project --symbol-pattern '*Adapter' --symbol-pattern '*Reader' --symbol-kind class --brief
```

Public APIs:

- `discover_files(root, include=('*',), exclude_dirs=..., include_hidden=False, max_files=5000)` returns relative `files`, `errors`, `skipped`, and `truncated` without reading file contents.
- `discover_python(root, include=('*.py',), patterns=('*',), kinds=(), exclude_dirs=..., include_hidden=False, max_files=5000, max_bytes=1000000, max_symbols=1000)` adds `symbols` and `scanned` (successfully parsed files).
- `python_symbols(source, pattern='*', kinds=())` also accepts a sequence of patterns; a name matching several patterns is emitted once per definition.

Filename rules match basenames OR root-relative POSIX paths. Symbol rules match
short OR lexical dotted names. Matching is case-sensitive on every OS; `*`
spans separators/dots (fnmatch, not gitignore). Name alternatives are ORed and
kind filters intersect that result. An empty pattern sequence selects nothing.
Default directory exclusions: `.git`, `.venv`, `venv`, `node_modules`,
`__pycache__`, `build`, `dist`; API callers may replace them, while repeated CLI
`--exclude-dir` adds to them. Hidden entries require `--include-hidden`.

Directory discovery has one root per invocation. The file limit applies to
matched regular files, not every visited directory entry; byte limits apply per
source file, and the symbol limit covers the whole root. Sorted traversal is
deterministic for an unchanged tree. Exact limits are complete until one more
match is observed. Source parse/read failures do not erase successful results.
JSON and brief diagnostics retain errors, skips and truncation; exit 2 marks
incomplete/error results, 1 marks no matches and 0 marks complete matches.
Symlinks are not deliberately followed; filesystem races are not isolated.

## Cross-repository one-liners

From an xprobe checkout next to these project checkouts:

```sh
python -S xprobe.py --symbols ../search_seq_including_spaces --include sequence_readers.py --include structured_readers.py --include 'protein/*.py' --symbol-pattern 'read_*' --symbol-pattern '*validate*' --brief
python -S xprobe.py --symbols ../Ironmate --exclude-dir tests --exclude-dir vendor --symbol-pattern '*transform*' --symbol-pattern '*export*' --symbol-pattern '*render*' --brief
python -S xprobe.py --symbols ../browser-test-kit --include 'scripts/*.py' --symbol-pattern '*probe*' --symbol-pattern '*capture*' --symbol-pattern '*validate*' --brief
python -S xprobe.py --symbols ../myon-bioinformatics --include vendor_sync.py --include 'tools/*.py' --symbol-pattern 'validate*' --symbol-pattern 'verify*' --symbol-pattern 'collect*' --brief
```

These are developer inspection commands against explicit checkouts, not vendor
lock changes. Existing consumer copies do not acquire a new API until separately
updated through their normal vendor process. No workflow, deployment or product
runtime dependency is added by using these recipes.

The production recipes above were run on 2026-10-21 with these immutable source
revisions. All completed with no errors, skips or truncation:

| Repository | Revision | Parsed files | Definitions |
| --- | --- | ---: | ---: |
| search_seq_including_spaces | `725a3602327b083e60263a1eabc83a82436b84c3` | 9 | 6 |
| Ironmate | `68898410f540ee25187f278e4a81e0b8fc0ef191` | 55 | 11 |
| browser-test-kit | `75d736d26f6752ff7bc1436ae414f6578e321f43` | 31 | 7 |
| myon-bioinformatics | `2192ff22acafdd09e80ac722df91ee937aaedd5e` | 4 | 12 |

An additional browser-test-kit file-discovery trial selected 6 YAML files,
including hidden workflow files. [Machine-readable evidence](evidence/convention-discovery.json)
records every source path/hash, query option and discovered definition. Counts
describe these snapshots, not expectations about future project versions.

Final extension validation on Python 3.12.14 / Node 24.19.0: **505 pytest cases
passed**, **99.06%** combined statement/branch coverage (90% required), using
the CI event adapter. The 30 focused discovery cases cover production naming,
file rules, errors, exclusions, hidden paths, exact limits and nonexecution.
All four production recipes were also run through the standalone `python -S`
CLI and matched the API counts. Compilation, diff checks and Python 3.9 grammar
parsing passed; grammar parsing is not a Python 3.9 runtime run.

## Where the idea came from

`unittest discover` combines filesystem traversal, name matching, imports and
test loading. Its reusable name-matching pieces are ordinary stdlib APIs:

| Piece | Public API | Use in xprobe |
| --- | --- | --- |
| Match filename wildcards | `fnmatch.fnmatch` | Existing `search_files` uses `fnmatchcase` for consistent case sensitivity across operating systems |
| Filter qualified test names | `fnmatch.fnmatchcase` | New `python_symbols` filters short or lexical dotted definition names |
| List live members | `dir`, `getattr`, `callable` | Useful for already loaded trusted objects; not used to inspect source files |
| Parse definitions without imports | `ast.parse`, `ast.iter_child_nodes` | New static definition inventory; a separate choice from unittest's runtime loading |

This uses public standard-library functions, with no copied unittest internals
or new dependency. `TestLoader.discover` itself imports target modules, can call
`load_tests` hooks and constructs test instances; it is not a general-purpose
read-only source scanner. The new API inventories definitions, not runnable tests.
Inherited tests, fixtures, parametrized expansions, aliases and dynamic members
are outside its scope. Conditional definitions are included even when their
branch would not execute. Grammar support follows the running Python version.

## One-liners

```sh
# File contents -> names; no target import or test execution.
python xprobe.py --symbols tests/test_xprobe.py --symbol-pattern '*Tests.test_*' --brief
python xprobe.py --symbols xprobe.py --symbol-pattern '*search*' --brief
python -c "from pathlib import Path; from xprobe import python_symbols; print(python_symbols(Path('xprobe.py').read_bytes(), pattern='*search*'))"
```

`python_symbols(source, pattern='*')` takes a string or source bytes (including
Python encoding cookies and UTF-8 BOMs). It returns `name`, `qualname`, `kind`
(`class`, `function`, `async_function`) and 1-based `line`, sorted by qualified
name then line. A pattern matches either the short name or lexical dotted name;
`*` also spans dots. Nested function names use lexical scopes (`outer.inner`),
without Python runtime `<locals>` segments. Repeated definitions remain separate.
It does not return source snippets, signatures or literal values.

The single-file CLI reads at most `--max-bytes + 1` bytes (default 1,000,001),
rejects nonregular inputs/symlinks, and caps output at `--max-matches` (default
1000). Exit statuses: 0 = found, 1 = no definitions matching, 2 = input error or
truncated output. JSON retains `truncated`; `--brief` prints a truncation notice.
Diagnostics print the exception type, not source text. Parsing is not a resource
sandbox; the byte bound limits input size, not all parser memory/CPU usage.

## Initial single-file validation

The controlled trial compares `test_*` names from a source class with public
`unittest.TestLoader.getTestCaseNames` on an equivalent trusted in-memory class.
No test methods run. Separate fixtures contain top-level writes, exceptions,
missing imports and decorators: all remain unevaluated. Regressions cover nested
classes/functions, async definitions, conditional definitions, comments/string
false positives, case sensitivity, duplicate definitions, encodings, CLI limits,
invalid inputs and standalone `python -S` use. Run the suite once with pytest;
the unittest API above is an oracle inside a pytest test, not a second test run.

On 2026-10-21, the trial on xprobe main `d586668535ce68572dfaaa91a96ded533945a2dc`
plus this change found 5 definitions for `*search*` in `xprobe.py`. The
`*Tests.test_*` pattern found 16 definitions in `tests/test_xprobe.py`, including
3 nested helpers because `*` spans dots. This illustrates why a source inventory
must not be presented as a runnable-test count. Added regressions: 13 passing
pytest cases on Python 3.12.14; standalone execution uses `python -S`.
The full pytest suite, using the CI event adapter and branch-coverage gate,
passed all 488 cases with 99.30% combined statement/branch coverage (90% required).
`git diff --check`, compilation and a Python 3.9 grammar check also passed;
the grammar check is not an actual Python 3.9 runtime test.

References:

- [CPython 3.13 unittest loader](https://github.com/python/cpython/blob/3.13/Lib/unittest/loader.py): `_match_path`, `getTestCaseNames`, `loadTestsFromModule`.
- [unittest discovery](https://docs.python.org/3/library/unittest.html#test-discovery).
- [fnmatchcase](https://docs.python.org/3/library/fnmatch.html#fnmatch.fnmatchcase).
- [ast](https://docs.python.org/3/library/ast.html).
