# Integer popcount for exact factor selection

The opt-in greedy selector now counts marginal pair coverage with `int.bit_count`
on Python 3.10+ rather than allocating a binary string for every candidate at every
selection step. Python 3.9 retains the original `bin(...).count('1')` fallback.
No feature, pair, candidate, or coverage bit is removed. The public output schema,
ID tie ordering and fill-to-budget behavior remain unchanged. No dependencies added.

```sh
python -S -m unittest discover -s tests -p test_factor_popcount.py -v
python -S scripts/benchmark_factor_popcount.py
```

Tests compare complete selected records with an independent set-based greedy oracle
on fixed-seed inputs (0/1/8/64/256 pairs, 40 candidates, five budgets), the real
built-in corpus, empty candidates, equal-gain ties and the compatibility fallback.

## Measurement

2026-11-04, Linux x86_64, CPython 3.12.14. Built-in corpus: 36 candidates,
42 pairs, selection budget 20. One warmup and 21 timed samples per implementation,
with alternating execution order. The benchmark switches only the popcount helper
and verifies identical selected IDs in every run. Raw samples, input SHA-256 and
selected IDs are in `factor-popcount-measurement.json`.

Median full greedy selection: binary string 246,542 ns → integer 164,708 ns
(about 33.2% lower in this local measurement). This includes mask construction and
selection, but excludes generation of the input corpus. It is not evidence of CI
or build-time acceleration, lower distribution size, or a general application-wide
speedup. Bitmask width and the stored corpus remain unchanged.
