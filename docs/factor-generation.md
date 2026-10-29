# Factor input prototype

Issue: https://github.com/myon-bioinformatics/xprobe/issues/8

This first stage borrows the binary representation idea from `littlebit-approx`.
It uses exact pair coverage and a small Cartesian product, without a low-rank
model, numerical approximation, special kernels, or additional dependencies.
It is an input generator, not a predictor of failures or a test runner.

## Schema v1

`case_factor_matrix()` currently returns 29 source rows: 17 known corpus cases
and 12 boundaries. Each row has its stable source ID and an integer `bits`. Bit `i`
corresponds to `factor_names[i]`; decode with `bits & (1 << i)`. All collections
are fresh. Classification uses input properties, not the case's stated failure.

| Bit | Factor | Definition |
| --- | --- | --- |
| 0 | ascii | Text contains only ASCII code points, including empty text |
| 1 | unicode | Text has at least one non-ASCII code point |
| 2 | empty | Text has zero Python characters |
| 3 | whitespace | Nonempty text satisfies `str.isspace()` |
| 4 | newline | Text contains CR or LF |
| 5 | nul | Text contains U+0000 |
| 6 | long | Text has at least 4096 Python characters |
| 7 | negative | Named number boundary: -1 |
| 8 | zero | Named number boundary: 0 |
| 9 | positive | Named number boundary: 1 |
| 10 | large | Named number boundary: 2**63 |
| 11 | missing | Explicit None in corpus or named number boundary |
| 12 | wrong_type | Named number boundary: string "1" |

`ascii`/`unicode` describe code points; they do not assert any codec was used.
Numeric bits label the existing boundary presets: `large` does not also set
`positive`. The string "1" in the number slot sets `wrong_type`, not `ascii`.
Missing keys, byte encodings, execution order, and target-specific factors are
outside v1. Length is measured in characters, not bytes.

Only the 7 text factors × 6 number factors are eligible coverage pairs.
`uncovered_pairs` includes a pair when no source row contains both bits. There
are currently 42 such pairs: the source inputs are scalar, so none cross the
two fields. This measures feature co-occurrence in these fixtures only; it says
nothing about coverage of actual consumer behavior or the entire input space.

### Consumer compatibility contract

- The matrix schema identifier is `xprobe.factors.v1`. Its required fields are
  `schema` (string), `factor_names` (ordered list of unique strings), `rows`
  (list of `{id: string, bits: nonnegative integer}`), and `uncovered_pairs`
  (list of `{factors: [text factor, number factor], bits: nonnegative integer}`).
  Pair bits contain exactly the two named factors. All bitsets, including each
  generated case's `factor_bits`, use the returned matrix's `factor_names`.
- The 13 bit positions and meanings above are fixed for v1. Changing them,
  adding factors, or removing/changing required field types requires a new
  schema identifier. Consumers should check both report and matrix identifiers
  before interpreting bits, and may ignore additional descriptive fields.
- Row counts, candidate counts and selected counts are data, not schema
  constants. Source presets may be added/removed; IDs must not be reused for
  different inputs. A changed input needs a new ID. New numeric categories
  require an explicit classification/schema change; arbitrary caller-supplied
  presets are not a public extension API in this stage.
- Generation records have string `id`, `category` (`factor_combination`) and
  `reason`, a `value` object with `text` (string) and `number` (integer, null or
  string in the current presets), integer `factor_bits`, and two string
  `origin_ids` in text/number order. There is no inferred expectation. To call
  `run_cases()`, consumers must explicitly map `id` to `name` and provide an
  `expected` or `raises` value appropriate to their own target.
- This API does not change `generate_cases()` or the existing corpus format.
  JSON/JSONL persistence retains the extra factor metadata; `merge_cases()`
  rejects conflicting records with the same ID. Persist the whole report to
  retain the schema/selection evidence, since `cases` alone omits that evidence.

## Generation and evidence

`generate_factor_cases(seed=0, count=20)` enumerates the built-in text/number
boundary product (currently 36 pairs). Each candidate is a dictionary input
template such as:

```python
{'text': '日本語🙂', 'number': 2**63}
```

The caller can assign `number` to an output-size limit, repeat count, or another
numeric argument. No assignment, validation of that argument, expected result,
or automatic execution is inferred here. Generated records have stable IDs
`factor-v1-{text boundary name}-{number boundary name}`, `factor_bits`, and both
`origin_ids`, plus the existing corpus fields `category`, `value`, and `reason`.
Records can be persisted with `corpus_to_json()` and `corpus_from_json()`.
They have no `expected`/`raises`; `run_cases()` still needs caller expectations.

Candidates without an uncovered pair are excluded. The remaining candidates
are shuffled by a private `random.Random(seed)` and taken without replacement.
An integer seed (excluding bool) and integer count in 0..10000 are required.
The returned report contains:

| Field | Meaning |
| --- | --- |
| schema | `xprobe.factor-generation.v1` |
| seed / limit | Supplied integer seed and count |
| candidate_total | Actual enumerated pre-filter product size, currently 36 |
| selected_count | Number of returned records, at most count and candidate_total |
| excluded_count | Candidates filtered out or omitted by the count limit |
| exclusions.already_covered | Candidates with no uncovered pair |
| exclusions.limit | Eligible candidates omitted by the limit |
| matrix | Source matrix, ordered factor names, uncovered pairs |
| cases | Selected composite inputs |

All count fields are nonnegative integers. The generator counts every enumerated
candidate once, so `candidate_total == selected_count + excluded_count` and
`excluded_count == exclusions.already_covered + exclusions.limit`, including
when either boundary set is empty or all candidates are covered. With the current presets,
seed 7/count 10 gives total 36, selected 10, excluded 26 (all limit exclusions).
Count zero still returns the full coverage evidence. Same seed and options on
the same producer revision, presets and Python version reproduce the selection,
with no global RNG changes. Selection order across producer/Python revisions is
not guaranteed by the schema identifier alone.
Stable IDs identify the input, not its position or seed; merging two selections
deduplicates identical inputs. Retain the report and producer commit alongside
cases when preserving selection evidence across future schema revisions; also
record the Python version for exact seeded replay. Stored cases are the replay
source when the original producer/runtime is unavailable.

This is bounded sampling, not a minimum covering array: it does not guarantee
that a capped selection covers every missing pair. Full selection covers all
42 eligible pairs, while producing 36 unique composite inputs. The 4096-char
text preset keeps allocation small. No additional corpus inputs, arbitrary
dimensions, Unicode × long-text mutations, or unbounded product are introduced.
Future stages can measure useful new consumer regressions, pair coverage per
budget, and selection cost before choosing low-rank or other candidate ranking.

## Opt-in exact greedy selection

`generate_factor_cases(seed=7, count=10, selection='greedy')` selects the largest
marginal gain in currently uncovered pairs using integer pair bitsets. Ties use
lexicographically ascending stable case IDs; seed is validated and recorded but
does not affect this method. Zero-gain cases fill any remaining budget, preserving
`selected_count == min(count, eligible candidates)` and prefix replay. This is a
greedy maximum-coverage heuristic, not an exact optimizer or a low-rank model.
It does not guarantee full pair coverage for arbitrary presets/budgets.

The default `selection='seeded'` retains its original report and shuffle order.
The greedy report adds optional descriptive metadata only:
`selection={method: 'greedy', tie_break: 'stable_id', approximation_excluded: 0}`.
All required v1 fields and both existing exclusion reasons remain unchanged.
Greedy ranking does not prune candidates before the budget: omitted eligible
cases are still `exclusions.limit`, and approximation exclusions are separately
recorded as zero. No rank setting is invented; low-rank approximation remains
unimplemented. Python 3.9 compatibility uses `bin(mask).count('1')` for popcount.
The CLI continues to use the existing seeded default.

See [the reproducible comparison](experiments/factor-selection.md) for measured
coverage, time, CPU, memory, consumer checks and a controlled fault comparison.
