# xprobe

<p align="center">
  <img src="docs/brand/icon.png" alt="xprobe icon" width="160" />
</p>

[Icon](docs/brand/icon.png) · [Favicon](docs/brand/favicon.png)

For native pytest outcomes (including xfail/xpass and execution phases), see
[pytest observations and exploration](docs/pytest-observations.md). The opt-in
test adapter emits JSONL readable by the existing corpus and search helpers.

Single-file, standard-library Python toolkit for text search, boundary-case probing, and failure-oriented test support. Importable, CLI-ready, and easy to vendor.

For bounded, browser-free comparison of explicit Python/Node command adapters,
see [portable I/O contracts](docs/portable-contracts.md). This optional
`contract_probe.py` CLI reuses `run_cases`; it does not change the single-file API.

The first [real native error corpus](tests/fixtures/native_error_sweep/README.md)
archives Dart/Kotlin/Swift observations and same-environment Python/Node results
with source/run identities, original diagnostics and explicit unobserved cases.

## Design

The canonical artifact is `xprobe.py`: copy it to `vendor/xprobe.py` without pip or supporting modules. Like `markdown` and `ascii_artist`, the artifact provides functions, `__all__`, and `__version__`; import performs no I/O. A thin guarded main delegates to existing APIs. The advanced CLI remains in `scripts/xprobe_cli.py`.

Python target: 3.9–3.15. Tests use external development dependencies under `tests/requirements.txt`; runtime uses the standard library only.

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

The CLI searches only; it never imports or executes discovered project code. Output is JSON with escaped control characters. Exit codes: 0 = matches or a complete mode result (a finished JUnit import is 0 even when the imported tests failed), 1 = no matches, 2 = argparse usage, a no-report failure, or a finished search/scan whose report lists read errors, 3 = truncated JUnit report. Usage and no-report failures (invalid input, unreadable JUnit, bad regex) write one JSON object on stderr and leave stdout empty, so agents can tell them from a partial import. A finished search or scan with read errors still prints its report JSON on stdout and exits 2. Exit 3 writes the partial JUnit report on stdout (`truncated` true) and a stderr JSON object whose `code` is `truncated`. Search skips and truncation stay in the JSON and do not change 0 or 1. A JUnit file over `--max-bytes` is exit 2 with no report, not exit 3. `--help` documents every flag and these codes. `node xprobe.cjs` does **not** run this advanced CLI; it launches `xprobe.py` only (see [From Node](#from-node-xprobecjs-node-24)), so JUnit importer flags such as `--junit` / `--repository` / `--report-id` are unrecognized there and exit 2.

## Tests

```sh
python -m pip install -r tests/requirements.txt
python -m pytest --cov=xprobe --cov-branch --cov-report=term-missing --cov-fail-under=90
```

Tests cover literal/regex/Unicode/CRLF coordinates, byte/match boundaries, hidden/binary/encoding behavior, read errors, symlinks, explicit probe expectations, malformed cases, CLI exit codes and copy-one-file import from another directory. CI runs Python 3.9–3.15 on Linux and Python 3.12 on Windows/macOS.

## Configuration discovery and regression corpus (0.2)

The original xgrep/xfail goal goes beyond ad-hoc grep: locate configuration clues using built-in vocabulary, then retain explained failures for repeatable tests and AI troubleshooting. The single artifact now provides:

| API | Behavior |
| --- | --- |
| `inspect_text(text)` | Built-in header words, secret-like key phrases, config terms and URL schemes; source/line/column and key classification only. |
| `scan_config(root, ...)` | Include globs, excluded directory names/relative paths, hidden .env support, byte/finding bounds and explicit errors/skips/incompleteness. |
| `inspect_environment(mapping)` | Recognized variable names and empty/present status, with all values omitted. Caller explicitly supplies the mapping. |
| `known_bad_cases(category=None)` | Stable, explained regressions for Git SHA, NUL, Markdown, paths, URLs, SQL and JSON. |
| `generate_cases(seed=0, count=20, category=None)` | Seeded sampling of that corpus with unique IDs and origin IDs; does not alter global RNG state. |
| `case_factor_matrix()` | Built-in cases and boundaries described by schema-v1 integer bitsets, plus uncovered text/number factor pairs. |
| `generate_factor_cases(seed=0, count=20)` | New composite text/number inputs, without replacement, with reproducible selection and counts. No expected outcomes or execution. |
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

## Factor input prototype (Issue #8)

`generate_cases()` retains its original sampling contract. The independent
`generate_factor_cases()` creates inputs from the built-in boundary product
(currently six text × six number presets). Candidate counts follow the enumerated
product. See [factor schema and scope](docs/factor-generation.md).

```python
report = xprobe.generate_factor_cases(seed=7, count=10)
inputs = report['cases']  # value contains {'text': ..., 'number': ...}
encoded = xprobe.corpus_to_json(inputs)
```

The caller maps these fields to its own API and supplies its own expectations.
The generator never executes inputs. Counts and the source coverage matrix are
returned even when `count=0`. Binary low-rank approximation is deferred.

## Direct standalone use (0.3)

```sh
python xprobe.py
python xprobe.py --search TODO --root .
python xprobe.py --corpus
```

Python alone is sufficient, including `python -S /path/to/xprobe.py`.
No pip, virtual environment, pytest or JUnit setup is required. The current
working directory is the default scope.

The main is only an entry/formatting layer: default calls existing
`scan_config(".")`, --search calls `search_files`, and --corpus calls
`known_bad_cases` + `corpus_to_json`. Discovery does not repair files, run tests,
or interpret reports. Explicit reading modes below can repair a text view.
Existing API scope, exclusions, limits and safety caveats apply.

Default discovery shows existing redacted key/location evidence and explicit
errors/skips/truncation. No findings is a normal result, not proof of safety.
--search deliberately prints raw matching lines; review before sharing.
Exit 0 means observation completed, 1 means explicit search found no matches,
and 2 means invalid or partial observation. Output goes to stdout only.
JUnit/native pytest remain existing optional helpers, not the main purpose.

## Explaining an outcome (0.4)

`explain_outcome(records, target)` ranks simple conditions on record fields that
separate a yes/no outcome: `field == value`, `field <= t` / `field > t` at midpoints
of observed numbers, and `[A] and [B]` / `[A] or [B]`, held as integer bitsets
(the same representation as `case_factor_matrix`). Results are ordered by MCC,
then fewer predicates; formulas selecting the same rows appear once, and each
lists up to `max_ids` counterexample ids (default 20; `fp_ids`: predicted yes
but no, `fn_ids`: missed). Each result also includes `fp_ids_total` /
`fn_ids_total`, `fp_ids_omitted` / `fn_ids_omitted`, and
`fp_ids_truncated` / `fn_ids_truncated`. Totals count records even when IDs
repeat. These are additive fields in `xprobe.explain.v1`; existing fields and
ranking are unchanged. The CLI appends `(+N more)` to incomplete ID lists.
Nested dicts flatten to dotted names; a missing field never matches.

```python
report = xprobe.explain_outcome(press_records, ('hit.self', False), id_field='label')
report['results'][0]  # {'expr': 'box.height > 81', 'mcc': 0.8, 'tp': 4, 'fp': 0, 'fn': 1, 'fn_ids': ['r8'], ...}
```

```sh
python xprobe.py --explain presses.jsonl --target hit.self=false --id label
python xprobe.py --explain cases.json --target-differs expected_tool_family,chosen_family --id id
```

One line per formula, so a long record list costs a few lines of context. This
describes the sample it is given (no validation on new records) and uses no
low-rank factors. Exit codes: 0 = at least one formula, 1 = none, 2 = input error.

## Normalized search and named patterns (0.4)

Ad-hoc regex tricks that sibling repositories each re-implemented are built in.
`normalize` searches a normalized view of every line but reports the **original**
line/column and text (`normalized` holds the view):

| step | effect | typical use |
| --- | --- | --- |
| `ansi` | drop terminal escape sequences | colored CI logs |
| `nfkc` | NFKC per base + combining marks (full/half width, `ｶﾞ`→`ガ`) | Japanese text, scraped HTML |
| `casefold` | full case folding (`ß`→`ss`) | case-insensitive across scripts |
| `spaces` | drop whitespace inside a line | sequences or tokens split by spaces |
| `vs16` | drop U+FE0E/U+FE0F/ZWJ | emoji identifiers |
| `mojibake` | repair recognized, byte-reversible Japanese mojibake spans | garbled text and legacy CSV exports |

Literal patterns are normalized with the same steps; regexes are written for the view.
`preset=` (or `--preset`) uses a named regex instead of a pattern; `pattern_presets()`
lists them: `git-sha`, `sha256`, `iso-timestamp`, `url`, `python-frame`,
`python-exception` (also after pytest's `E   `), `node-error`, `npm-error`,
`compiler-error`, `credential`, `ci-path`, `hex-address`, `ansi`.

```sh
python xprobe.py --root logs --preset python-exception --normalize ansi --brief
python xprobe.py --root data --search 'ACGT' --normalize spaces,casefold --brief
python xprobe.py --presets
```

`--brief` prints one `path:line:column: 'match'` line per match instead of JSON.

## Read legacy text without choosing an encoding

```sh
python -S xprobe.py --read-text excel-export.csv
python -S xprobe.py --read-text saved-page.html --text-report
python -S xprobe.py --read-text - < old-log.txt
python -S xprobe.py --search 'こんにちは' --normalize mojibake --root exports --brief
python -S xprobe.py --mojibake --root exports
```

`--restore-mojibake FILE` remains an alias for `--read-text FILE`. The reading
mode automatically tries common encodings and repairs recognized mojibake.
It prints a UTF-8 reading view without changing the input file. The default
read limit is 1,000,000 bytes, adjustable with `--max-bytes` and also enforced
for stdin. A partial reading still exits 0 so a viewer can show the useful
content; warnings go to stderr. `--text-report` returns the text and diagnostics
as JSON instead. Missing/oversized files and recognized binary/container input
exit 2. The separate `--mojibake` scanner retains exit 1 for detected findings.

```python
from pathlib import Path
import xprobe

report = xprobe.readable_text(Path("excel-export.csv").read_bytes())
print(report["text"])
report["encoding"]       # e.g. "cp932"
report["source"]         # "bom", "declared", "heuristic" or "fallback"
report["status"]         # "partial" if byte decoding or recognized repair is incomplete
report["decoding_status"] # "decoded" or "partial" at the byte-decoding stage
report["restoration_status"] # "unchanged", "candidates_applied" or "partial"
report["source_hex"]     # exact original bytes, including BOM and invalid bytes
report["decoded_text"]   # decoded view before any mojibake repair
report["findings"]       # original spans, candidate replacements and round-trip evidence
```

`decode_text(bytes)` provides just the decoding stage. Both APIs are pure,
standard-library functions: callers can pass downloaded HTML bytes or CSV
bytes directly, without selecting a codec or installing a detector.

| Evidence | Reading strategy |
| --- | --- |
| UTF-8 / UTF-16 / UTF-32 BOM | Use the indicated encoding and remove the signature |
| HTML meta / XML declaration in the first 4 KiB | Try the supported hint; try finite alternatives when it conflicts with a more readable decoding |
| ISO-2022-JP escape signature | Try ISO-2022-JP, with a UTF-8 fallback for a conflicting hint |
| Valid UTF-8 | Preserve the decoded Unicode text, including other languages and emoji |
| Otherwise | Compare UTF-8, CP932 and EUC-JP using explicit Japanese-character heuristics |
| Invalid bytes in the selected reading | Show literal `\xHH` escapes and mark the result `partial` |

Candidate scores are disclosed in `candidates`; they are not probabilities.
Short or mixed-encoding inputs can remain ambiguous. The declaration sniff is
a bounded hint reader, not a complete browser encoding algorithm. BOM-less
UTF-16/32 is not guessed. ZIP/OLE containers, including `.xlsx`/`.xls`, require
their format parser; this feature covers text and CSV exports, not workbook
layout, formulas, browser rendering or URL fetching.

`mojibake_text(str)` and `restore_mojibake(str)` operate on already decoded
strings. They recognize common UTF-8-as-CP932/CP1252 and CP932-as-CP1252 patterns.
An incremental decoder accepts only whole source-character / target-byte
boundaries and checks the reverse byte conversion. A failed unit is retained
while other units can still be repaired. For example, a garbled greeting
followed by normal Japanese or French keeps that normal suffix. U+FFFD stays
U+FFFD with `status="unrecoverable"`; missing original information is not invented.
The same non-overlapping candidate selection feeds restoration and search.

Reversibility does not prove the author's intended language. `status="repaired"`
on a finding denotes a reversible candidate. `decoding_status` describes byte
decoding; `restoration_status` reports incomplete recognized runs separately.
Residual markers in a partly repaired run are retained as `unresolved_candidate`
findings. Unknown mojibake can remain; `unchanged` does not prove clean input.
`source_hex` retains the exact original bytes for reconstruction: the display's literal
`\xHH` escapes can also occur naturally in the source. `decoded_text` and each
finding's original `text` retain the pre-repair view and source coordinates.
Decoding candidates expose `roundtrip`; noncanonical codec byte mappings are
reported explicitly and the original bytes remain in `source_hex`.

`mojibake_scan()` includes per-file `decodings` diagnostics. `search_files()`
automatically enables decoding when `normalize="mojibake"` and no encoding
is supplied; `encoding="auto"` also enables it explicitly. An explicit codec
keeps strict decoding, and searches without the mojibake step keep their UTF-8
default. Search coordinates refer to the original decoded text, not byte offsets.

The implementation uses a fixed candidate set and incremental state instead
of unbounded brute-force transforms or model calls. The regression cases check
known transformations, neighboring clean text, partial byte input and search
coordinates; all runtime code remains in the vendorable `xprobe.py`.

## Loading TOML and YAML without pip (0.4)

`load_toml(text)` uses `tomllib` on Python 3.11+ and otherwise Node with
`smol-toml`; dates and times come back as `datetime` objects either way.
Signed 64-bit integers stay exact on both backends: the Node reader uses BigInt
as needed and transfers it with an explicit type tag and decimal string for
restoration to Python `int`, including inside arrays and tables.
`load_yaml(text)` uses Node with `js-yaml`: `schema="failsafe"` (default) returns
only strings, lists and dicts like PyYAML's `BaseLoader` (so `on:` stays `"on"`),
`schema="core"` types scalars by YAML 1.2 (`yes` stays a string). The packages
resolve through `NODE_PATH` or the current directory (`npm i --no-save js-yaml smol-toml`);
without them a `RuntimeError` says what is missing. Text goes through stdin to a fixed
script; nothing in the input is evaluated.

`xprobe.py` remains one file. YAML, and TOML on Python 3.10 and older, need Node 24+.
When `vendor/node_launch.py` is already beside the script, that sibling launcher is used;
a copy of `xprobe.py` alone uses an inlined stdlib launcher and does not need the helper.
Search and the other commands do not spawn Node. `python xprobe.py --load` exits 2 and
writes the Node 24+ message to stderr when Node or the reader package is missing.

```sh
python xprobe.py --load yaml .github/workflows/ci.yml    # JSON on stdout
python xprobe.py --load toml pyproject.toml
```

`tests/test_load_config.py` mirrors both against `tomllib` and PyYAML on this
repository's own workflows.

## CI helpers: annotations, portability, several roots (0.4)

`junit_annotations(text)` turns failed JUnit testcases into GitHub workflow
commands (`::error file=…,line=…,title=…::first message line`). Check-run
annotations are readable through the API even when job logs and artifacts are
not, so printing them from a step puts failing test names where an agent or a
reviewer looks first. The file comes from the `file` attribute or the
`classname`; at most 50 lines, then a count of the rest.

```yaml
- if: failure()
  run: python xprobe.py --annotate-junit reports/junit.xml
```

`portability_findings(root)` reads Python sources with `ast` (nothing is
imported) and reports imports of stdlib modules newer than the minimum
interpreter (`tomllib` on 3.10), imports of modules removed by 3.12/3.13
(`distutils`, `cgi`, …) and files that do not parse. Imports under
`try/except ImportError` or `if sys.version_info …` count as guarded. The
minimum comes from `requires-python` in `pyproject.toml`, else 3.10.
`--windows-locale` adds hints that matter on Windows runners, where the locale
encoding is cp1252: `read_text()`/`write_text()`/text `open()`/`subprocess`
`text=True` without `encoding=`, and bytes cp1252 cannot decode. The hints do
not change the exit code (1 only for import or parse findings).

```sh
python xprobe.py --portability                      # this checkout
python xprobe.py --portability --min-python 3.10 --root ../a --root ../b
python xprobe.py --search tomllib --root ../a --root ../b --brief
```

`--root` repeats for `--search` and `--preset` too; with more than one root,
paths are prefixed with their root.

## Emoji: sequences, reverse lookup and inventory (0.4)

```sh
python xprobe.py --emoji-find house            # name -> emoji (stdlib unicodedata)
python xprobe.py --emoji-find "flag jp"
python xprobe.py --emoji-explain "TEXT"        # split into sequences: code points and names
python xprobe.py --emoji --root ../a --root ../b --brief   # which emoji are used where
```

`emoji_sequences(text)` finds whole emoji sequences (ZWJ, skin-tone modifiers,
flags, keycaps, subdivision tag flags) using the Extended_Pictographic table and the
UTS #51 sequence shape, with offsets, `kind`, and an `identity` without U+FE0F (the
same rule as browser-test-kit's `route_trail.py`, so `❤️` and `❤` are one emoji).
Text-default symbols such as the copyright sign only count with U+FE0F.
`emoji_name()` and `emoji_find()` use this interpreter's `unicodedata`, which names
single code points only: a ZWJ sequence reads as its parts (`WOMAN + PERSONAL
COMPUTER`), and very new emoji are unnamed on older Pythons (`unicodedata.unidata_version`
is reported). `--emoji-names FILE` (or `names=load_emoji_names(FILE)`) takes CLDR names from QueRyu's accumulated `emoji_names.json` first, naming skin-tone/hair variants from their base (`woman technologist: medium skin tone`), so names work offline without unicode.org. `emoji_inventory(roots)` counts identities across roots with the
spellings used (`forms`, to catch a heading written both with and without U+FE0F),
file counts and first locations.

`tests/test_xprobe_emoji.py` mirrors the table against Node's
`\p{Extended_Pictographic}` for every code point and the sequences against
`\p{RGI_Emoji}` (RegExp `v` flag, Node 20+) on `tests/fixtures/emoji_corpus.txt`;
both skip without Node. Extended_Pictographic is not stable across Unicode versions (Unicode 17 narrowed it); the table is Unicode 16.0's, so it must equal Node's on 16.0 and be a superset on newer versions.

## Hidden text: invisible and deceptive characters (0.4)

```sh
python xprobe.py --hidden-rules                         # rule, severity, what it matches
python xprobe.py --hidden-text --root ../a --brief      # 1 if anything at/above --min-severity (default medium)
python xprobe.py --hidden-text --min-severity high --kinds tag_text,bidi_control --root .
python xprobe.py --strip-hidden untrusted.txt > clean.txt   # '-' reads stdin
```

`hidden_text(text)` matches rules for characters that change what a reader,
reviewer or model receives without showing on screen: prompt-injection text
hidden in Unicode tag characters (`tag_text`, with the hidden ASCII in
`decoded`), bytes smuggled as a run of variation selectors (`variation_payload`,
decoded one byte per selector), Trojan Source bidi controls (`bidi_control`, with
"not closed before end of line" when an override or isolate is left open),
IDN punycode homoglyphs, mixed-script domain labels and confusable URL delimiters
(`homograph_url`, with `decoded` host labels), zero-width characters, stray variation
selectors, other invisible format characters and Hangul fillers, Latin/Cyrillic/Greek
homoglyph words (`mixed_script`, with the minority code points in `odd`), and low-severity
direction marks, soft hyphens and private-use code points. Valid emoji ZWJ
sequences, VS15/VS16 after a base, subdivision flags, ideographic variation
sequences, a leading BOM and ZWJ/ZWNJ inside joining scripts (Persian, Indic)
are left alone, using the same emoji grammar as `emoji_sequences`.

`homograph_url` inspects the URL authority, not Unicode in paths, queries or
fragments. `decoded` is the host with ACE labels decoded and IDNA dot aliases
normalized; `start`/`end` cover the matched URL (excluding trailing prose
punctuation). Latin/Cyrillic and other homoglyph-script mixtures **within a
label** are high-severity candidates. Merely using different scripts in separate
labels, Japanese script mixtures, or Punycode is not evidence of spoofing.
Whole-script candidates require every letter in a label to belong to a small
ASCII-confusable Cyrillic/Greek subset; this is a conservative heuristic, not a
complete UTS #39 skeleton, ownership check, or maliciousness verdict. Valid IDNA
dot aliases (`。`, `．`, `｡`) retain a **medium** spelling advisory and are omitted
at `min_severity="high"`; delimiter lookalikes in the authority remain high.
The rule metadata reports its maximum severity. Standard-library IDNA decoding
uses IDNA 2003; malformed or unsupported ACE labels are left undecoded. The
scanner is not a browser URL validator and does not percent-decode hosts.
`strip_hidden()` keeps reported URLs intact while still removing independently
reported hidden characters.

References: [Unicode UTS #39](https://www.unicode.org/reports/tr39/),
[Python IDNA codec](https://docs.python.org/3/library/codecs.html#encodings-idna).

A finding is a rule match, not a verdict on intent: real pages use U+200B as a
line-break hint, and RTL text needs direction marks, which is why those rules sit
at medium/low. `strip_hidden(text)` removes what the selected rules match (homoglyph
words are reported, not rewritten); keep the `hidden_text` report alongside, since
stripping alone hides that anything was there. `hidden_text_scan(roots)` adds
`path`/`line`/`column`; output is ASCII-escaped, so a scan never replays the
characters it reports.

### From Node (`xprobe.cjs`, Node 24+)

```sh
node xprobe.cjs --hidden-text --root untrusted.txt   # same JSON and exit codes as xprobe.py
node xprobe.cjs --strip-hidden - < untrusted.txt
```

`xprobe.cjs` is a thin launcher: it runs `xprobe.py` through the vendored shared launcher
`vendor/py_launch.cjs` (pinned in `vendor.lock.json`). Arguments, stdin/stdout/stderr and
the exit code are passed through unchanged; Python runs with `-S`. Set `XPROBE_PYTHON` to
pick the interpreter. Launcher failures (no Python 3.9+, spawn error, signal) exit 2.
It needs Python 3.9+ and has no in-process JavaScript API; `require("./xprobe.cjs")` only
exposes `PY_SCRIPT` and `PY_LAUNCH` (typed in `xprobe.d.cts`).

The former native JavaScript twin of the hidden-text rules (`hiddenText`, `stripHidden`,
`hiddenTextRules`, and `node xprobe.cjs --hidden-text FILE|-`) was retired so that every
repository uses the same Python-backed launcher. `tests/test_xprobe_node_entry.py` checks
parity with `xprobe.py`, and `node --test tests/xprobe_cli.test.cjs` is the Node-side smoke test.


## Convention-driven file and Python discovery

`discover_files(root, include=("*.yml", "*.json"))` lists files by injected naming
rules. `discover_python(root, patterns=("load_*", "validate_*"))` finds Python
definitions across a directory. `python_symbols(source, pattern="*")` handles
in-memory source. These use stdlib `fnmatchcase` and `ast`; no test naming rule
is built in and targets are not imported. Multiple patterns are ORed.

```sh
python xprobe.py --symbols xprobe.py --symbol-pattern '*search*' --brief
python xprobe.py --symbols . --exclude-dir tests --exclude-dir vendor --symbol-pattern 'load_*' --symbol-pattern 'validate_*' --brief
python xprobe.py --discover --root . --include '*.yml' --include '*.toml' --include-hidden --brief
```

Definition results include paths, lexical dotted names and line numbers. Use
`--symbol-kind class` (or `function`/`async_function`) to narrow by kind.
See [cross-repository recipes, trial results and limits](docs/stdlib-discovery.md).

## Runtime and development Python policy

The standard-library runtime supports Python 3.9+; this change preserves the
existing runtime floor. The separate `runtime-compatibility` CI lane executes
behavior tests with `python -S`, without installing pytest or any third-party
package. Development/test environments use Python 3.11+ and a committed uv lock:

```sh
uv sync --locked --python 3.11
uv run --locked python -m pytest
python -S -m unittest discover -s tests -p test_xprobe.py -v
```

`pyproject.toml` is the canonical development dependency definition; legacy
requirements files remain for downstream callers. Runtime metadata does not
raise the source/vendoring floor to the development floor. CI pins checkout v7.0.1,
setup-node v7.1.0, setup-python v7.1.0, setup-uv v10.3.2, and upload-artifact v7
by full commit SHA (or major tag for upload-artifact), and uses uv 0.13.3.
``load_toml`` / ``load_yaml`` Node fallbacks require Node 24+. The canonical
``xprobe.py`` spawns that Node with the standard library and does not require
``vendor/node_launch.py`` when the file is copied alone. Setup actions using
Node 24 require runner 2.327.1 or newer (GitHub-hosted runners are used).
