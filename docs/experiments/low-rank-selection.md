# Binary low-rank candidate selection — 2026-10-29

Issue: https://github.com/myon-bioinformatics/xprobe/issues/8

## Decision

Do not add a production selection strategy. On this fixed population, the approximate model does not improve pair coverage over greedy, uses substantially more CPU/allocation, and does not improve the measured real consumer regression detection. Some settings detect the single artificial fault more often; this is not evidence of general fault-detection superiority. Existing xprobe.py, CLI, seeded/greedy APIs and strict pass/fail oracles are unchanged. Issue #8 remains open.

## Protocol

Baseline xprobe main: `ca03a165db2d675513b69e6980821de193c120c9` (includes merged #36). Reuse `generate_factor_cases(count=10000)` and its `case_factor_matrix()` report to obtain exactly the same 36 eligible candidates and 42 target pairs. Sort stable IDs before fitting. All methods use budgets 0, 1, 6, 10, 12, 18, 24, 30, 36 and seeds 0, 1, 7, 42, 99. Ten methods × nine budgets × five seeds = 450 fresh stdlib-only workers. Methods run in deterministically shuffled order per cell. Greedy validates/records seed but does not use it.

The experiment builds the exact candidate × pair 0/1 incidence matrix. It fits ranks 1, 2, 4, 8 as sums of signed binary outer products: seeded random signs, 16 alternating sign sweeps per component, least-squares scalar coefficient, and residual deflation. Each component has binary factors and a real scale; reconstructed entries are real, not necessarily binary. Column frequency correction is either absent or inverse-square-root frequency, reversed after fitting. This is a local binary-factor heuristic, not SVD, an optimal binary decomposition, or the official LittleBit implementation.

Nonnegative clipped reconstructed weights rank each remaining candidate against currently uncovered pairs. Stable IDs break ties; exact bitsets update coverage after each pick. All candidates remain eligible until the final budget. `approximation_excluded` counts eligible candidates omitted by approximate ranking at the budget; it overlaps `exclusions.limit` and must not be added to it. There is no separate pre-pruning stage or claim of large-product memory savings. Rank, seed, scaling, sweeps, coefficients, residual error, IDs and exclusion counts are retained in raw JSON.

Three individually timed warmed complete-generation calls per worker measure CPU and wall time, excluding import, tracing, JSON and oracles. A separate generation measures tracemalloc peak. RSS is whole-worker lifetime high-water including imports/tracing, not incremental selection memory. Timing is descriptive, with no CI threshold; these microbenchmarks do not establish production scaling.

## Budget 10 results

Ranges and detections cover all five seeds; CPU/allocation/RSS values are medians across workers.

| Method | Pairs / 42 | Artificial fault / 5 | Ironmate bug / 5 | CPU µs | Python peak bytes | Worker RSS bytes |
| --- | --- | --- | --- | --- | --- | --- |
| seeded | 15–18 | 2 | 5 | 194.2 | 32966 | 24035328 |
| greedy | 22 | 0 | 5 | 372.3 | 32730 | 24035328 |
| binary-1-frequency | 16–21 | 1 | 5 | 4979.4 | 227039 | 24035328 |
| binary-1-none | 15–16 | 5 | 5 | 4783.3 | 227178 | 24035328 |
| binary-2-frequency | 16–21 | 2 | 5 | 9068.3 | 227063 | 24035328 |
| binary-2-none | 16–17 | 5 | 5 | 8256.7 | 227202 | 24035328 |
| binary-4-frequency | 18–21 | 3 | 5 | 15321.1 | 227087 | 24035328 |
| binary-4-none | 15–18 | 3 | 4 | 14582.0 | 228882 | 24035328 |
| binary-8-frequency | 20–21 | 1 | 5 | 28986.9 | 227263 | 24035328 |
| binary-8-none | 16–20 | 1 | 5 | 28809.2 | 229562 | 24035328 |

All methods select 10 and omit 26 of 36 candidates at this budget. Seeded/greedy approximation exclusions are zero; binary methods record 26 overlapping budget omissions. Exact eligibility exclusions are zero. All selected inputs agree with the unmutated search_text oracle. Full budget restores all 36 IDs and 42 target pairs for every method. The compressed raw JSON (`low-rank-selection.json.gz`, standard gzip) contains all other budgets; no favorable rank/seed is presented as a universal winner.

## External consumer regression replay

Ironmate is a real sibling consumer with vendored xprobe. Its `size_estimate.base64_chars` is an actual application function, not a synthetic mutation. The documented floating-point rounding bug remains in pinned main `f633cd7c37490e5e7958f1393c79a0fa53d4ab97`; the fix is in **open Draft PR #164**, head `1792f7bc97ed7cfa43345212575ddfc09fb577bf`, not a merged historical release fix. See https://github.com/myon-bioinformatics/Ironmate/pull/164 . Full modules at both fixed revisions were loaded locally and their real functions executed; `consumer-base64.json` records source URLs, full-module SHA-256, exact function snapshots and observations.

Adapter: map `value.number` to nonnegative integer byte-length metadata, leaving `text` unused. No image allocation or huge byte buffer. Invalid negative/null/string inputs are outside this function’s length domain and excluded from this consumer check; this is not counted as a successful rejection. The six `large` cases supply `2**63`: expected `12297829382473034412`, old result `12297829382473033728` (684 too short), fixed result matches. Expected length uses independent `divmod(n,3)` group/remainder arithmetic, with small lengths cross-checked against actual Base64 padding.

The comparison runner uses the verified old function expression as an offline adapter, with exact integer expectation. The test executes both checked-in function snapshots, checks every valid full-population input, and verifies that the adapter identifies exactly the same six cases and the fix accepts their expected results. This is a replay of a documented real bug, not a newly discovered issue, end-to-end image failure, or proof that a huge image exists. Repeated text variants are the same semantic byte-length input, not six independent defects.

At budget 10, seeded and greedy both detect it for 5/5 seeds; every approximate setting except unscaled rank 4 also achieves 5/5 (that setting: 4/5). This one numeric-only bug does not establish behavior coverage of external consumers. The separate artificial positive-limit off-by-one mutation retains its own results and labels.

## Reproduce and validation

```sh
python -S scripts/experiment_low_rank_selection.py --output /tmp/low-rank-selection.json
python -m pytest -q tests/test_low_rank_experiment.py tests/test_factor_generation.py
```

Local validation: **125 passed**; no timing assertions. Controls check rank-one reconstruction/calibration, deterministic replay, the same exact candidate population, budget/exclusion identities, independent set-based pair counts, full-population historical old/fixed replay, unchanged seeded API reports, and the coverage-versus-artificial-fault counterexample. This is author validation, not an independent review or hosted CI claim.

Runtime: 3.12.14 (main, Aug 25 2026, 14:00:49) [Clang 22.1.3 ]. Platform: Linux-6.18.55-x86_64-with-glibc2.39. The raw JSON hashes the experiment script. Checked-in report data were measured before this documentation/test commit, against the stated unchanged main producer.

## Limits and next useful evidence

The model explicitly allocates dense candidate × pair matrices and recomputes fits for each budget. At 36×42 this is a small, transparent feasibility experiment, not an optimized implementation or streaming pruner. No hyperparameter tuning against held-out consumer defects was attempted. A useful follow-up needs a broader preregistered collection of independent historical defects and a larger candidate product before API adoption; neither good pair coverage nor detection of this single artificial mutation substitutes for that evidence.
