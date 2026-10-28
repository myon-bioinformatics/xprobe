# Factor selection experiment — 2026-10-28

Issue: https://github.com/myon-bioinformatics/xprobe/issues/8

Baseline: main `45618dde1099202d202f31f9d0015abea89ca8fb`.
The unchanged seeded shuffle is compared with opt-in, stable-ID-tied greedy
maximum marginal pair coverage. Both enumerate the same 36 candidates, apply
the same exact eligibility filter, and fill the same budget. No dependencies,
low-rank approximation, binary decomposition or scale correction are added.

## Reproduce

```sh
python -S scripts/benchmark_factor_selection.py --output /tmp/factor-selection.json
python -m pytest -q tests/test_factor_generation.py
```

The adjacent `factor-selection.json` records all 90 method/budget/seed runs,
selected IDs, exclusions, pair counts/rates, raw timing samples, CPU samples,
Python/platform and producer revision. Five seeds: 0, 1, 7, 42, 99; nine budgets:
0, 1, 6, 10, 12, 18, 24, 30, 36. Each cell uses a fresh Python `-S` worker,
one warm-up and five samples of 25 complete report generations. Method order
alternates. Wall/CPU measurements exclude imports, coverage, consumer checks,
serialization and tracing. Timing samples are descriptive, not CI thresholds.

Memory is measured in a separate traced generation in each worker. Tracemalloc
peak means Python allocation peak for complete generation. RSS is the worker's
whole-process high-water mark, including imports and the traced generation;
it is not incremental selection memory. Linux reports KiB converted to bytes;
macOS reports bytes; unavailable resource metrics are null. These tiny presets
do not establish scaling to large products or production consumer workloads.

## Result

Pair coverage is exact against the 42 target pairs. Ranges span the five seeds.

| Budget | Seeded pairs | Greedy pairs | Seeded wall µs | Greedy wall µs |
| --- | --- | --- | --- | --- |
| 0 | 0/42 | 0/42 | 187.0 | 285.1 |
| 1 | 2/42 | 3/42 | 187.3 | 312.9 |
| 6 | 9–14/42 | 18/42 | 193.9 | 350.7 |
| 10 | 15–18/42 | 22/42 | 198.4 | 398.2 |
| 12 | 18–20/42 | 24/42 | 196.0 | 385.0 |
| 18 | 24–26/42 | 30/42 | 196.0 | 415.3 |
| 24 | 31–32/42 | 36/42 | 190.6 | 457.5 |
| 30 | 36–38/42 | 42/42 | 189.6 | 462.5 |
| 36 | 42/42 | 42/42 | 189.7 | 458.9 |

Wall values are medians of the per-worker medians across seeds. At budget 10:

| Method | CPU µs/call | Traced peak bytes | Whole-worker peak RSS bytes |
| --- | --- | --- | --- |
| seeded | 198.3 | 32806 | 14151680 |
| greedy | 398.1 | 32570 | 14151680 |

At seed 7/budget 10, coverage rises from 16/42 (38.1%) to 22/42 (52.4%).
Across the five measured seeds, greedy improves pair coverage at every measured
nonzero partial budget, reaching 42/42 at budget 30 rather than 36. On these
presets 30 is also necessary: each of empty, nul, unicode and long needs its own
case per number category (24 cases), and newline needs six more cases, which
also cover whitespace and ASCII. This argument is fixture-specific.

Greedy costs approximately twice the complete generation time at budget 10.
No memory saving is established: small traced-peak differences and process RSS
are not evidence of scalable savings. The heuristic scans remaining candidates
per selected case and stores pair masks; this has quadratic worst-case ranking
cost when selecting the full population. Production use stays opt-in.

## Consumer checks and fault detection

The actual `xprobe.search_text` API is exercised with text as input, literal `x`
as pattern and number as `max_matches`. An independent oracle rejects invalid
limits and counts literal occurrences per line, bounded by the limit. Every
selected case in all 90 runs agrees with this strict oracle. This is an in-repo
consumer check, not a sibling repository's historical regression replay. No
historical consumer bugs were demonstrated; that metric is null in the raw data.
External consumer regression detection remains unmeasured.

A separate controlled mutation passes positive limits as `max_matches + 1`.
At budget 10, seeded selection detects this fault for 2/5 seeds (42 and 99),
while greedy detects it for 0/5, despite higher pair coverage. At budget 30 both
detect it for 5/5 seeds. Only the long/positive fixture reveals this mutation;
stable-ID ties can delay that input. This counterexample has a regression test.
It is a synthetic fault, not a discovered or historical regression. The existing
API and its exact validation/results remain the oracle; ranking never decides
pass/fail. This limited mutation sample is not a general fault-detection rate.

## Decision and evidence contract

Add only `selection='greedy'` as an optional API strategy, retaining the seeded
default and CLI behavior. Do not claim it improves bug detection. The measured
pair-coverage gain warrants a small, optional exact heuristic, while low-rank
approximation still needs a separate implementation and experiment.

For seed 7/count 10, both methods enumerate 36, select 10, and exclude 26 via
`limit`. Exact eligibility exclusions are 0 and approximation exclusions are
separately 0. Greedy ranking is not reported as approximation pruning. The
required v1 report fields and accounting identities are unchanged; only greedy
adds descriptive selection metadata.

Regression tests protect seeded order, unchanged default reports, greedy ties
and prefixes, RNG isolation, exact counts/coverage, partial/all-covered/empty
inputs, consumer oracles and the coverage-vs-fault counterexample. An independent
comparison against the original main module matched all 50 default reports
(5 seeds × 10 budgets). Timing is never asserted as a test threshold.


## Local validation

Python 3.14.8 with the locked development environment and installed test-only
Node readers: 701 pytest tests passed (plus 13 subtests), 97.65% branch-inclusive
coverage (required minimum 90%), and 5 Node launcher tests passed. The stdlib-only isolated replay and changed
boundary-set accounting tests exercise both strategies. All required runtime
code remains in the single `xprobe.py` file. CI across other operating systems
and Python versions must still run on the PR.
