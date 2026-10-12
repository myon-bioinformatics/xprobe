# Factor input prototype

Issue: https://github.com/myon-bioinformatics/xprobe/issues/8

This first stage borrows the binary representation idea from `littlebit-approx`.
It uses exact pair coverage and a small Cartesian product, without a low-rank
model, numerical approximation, special kernels, or additional dependencies.
It is an input generator, not a predictor of failures or a test runner.

## Schema v1

`case_factor_matrix()` returns 25 source rows: 13 known corpus cases and 12
boundaries. Each row has its stable source ID and an integer `bits`. Bit `i`
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

## Generation and evidence

`generate_factor_cases(seed=0, count=20)` enumerates all 36 text/number boundary
pairs. Each candidate is a dictionary input template such as:

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
| candidate_total | Fixed pre-filter product size, currently 36 |
| selected_count | Number of returned records, at most count and 36 |
| excluded_count | Candidates filtered out or omitted by the count limit |
| exclusions.already_covered | Candidates with no uncovered pair |
| exclusions.limit | Eligible candidates omitted by the limit |
| matrix | Source matrix, ordered factor names, uncovered pairs |
| cases | Selected composite inputs |

`candidate_total == selected_count + excluded_count`. With the current presets,
seed 7/count 10 gives total 36, selected 10, excluded 26 (all limit exclusions).
Count zero still returns the full coverage evidence. Same seed and options on
the same schema/presets reproduce the selection, with no global RNG changes.
Stable IDs identify the input, not its position or seed; merging two selections
deduplicates identical inputs. Retain the report and producer commit alongside
cases when preserving selection evidence across future schema revisions.

This is bounded sampling, not a minimum covering array: it does not guarantee
that a capped selection covers every missing pair. Full selection covers all
42 eligible pairs, while producing 36 unique composite inputs. The 4096-char
text preset keeps allocation small. No additional corpus inputs, arbitrary
dimensions, Unicode × long-text mutations, or unbounded product are introduced.
Future stages can measure useful new consumer regressions, pair coverage per
budget, and selection cost before choosing low-rank or other candidate ranking.
