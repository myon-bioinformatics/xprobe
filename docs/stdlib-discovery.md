# Reusing the discovery primitives behind unittest

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

## Validation

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
