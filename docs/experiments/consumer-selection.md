# Larger-population historical consumer replay — 2026-11-01

Related: [xprobe #8](https://github.com/myon-bioinformatics/xprobe/issues/8).
This is a separate experiment. No changes to xprobe.py, CLI, supported selection
modes or exact success criteria. No approximate strategy is proposed for adoption.

## Historical target and independent oracle

Investigated the merged TalkCompress [PR #94](https://github.com/myon-bioinformatics/TalkCompress/pull/94).
It fixes RuleBook replacement strings being interpreted as regex replacement
templates (exceptions for `\1`/`\q`, interpretation of `\g<0>`/`\t`/`\n`).
The independent application is consumed directly by this replay harness; this
report does **not** claim TalkCompress already vendors or depends on xprobe.
The numeric Ironmate regression from the earlier experiment is not reused.

- [Old module](https://github.com/myon-bioinformatics/TalkCompress/blob/766211bb4729c2666df7f6c23980b16a1096b8d4/Zipilogue/rulebook.py): `766211bb4729c2666df7f6c23980b16a1096b8d4`.
- [Fixed module](https://github.com/myon-bioinformatics/TalkCompress/blob/9bd32ad120a1cf1f96a426c8927261f4ad9203e8/Zipilogue/rulebook.py): `9bd32ad120a1cf1f96a426c8927261f4ad9203e8`.
- Merged commit: `075af7d87cb6792d326d2ec9a51b6df6fac887d8`.
- Path: `Zipilogue/rulebook.py`.
- Old Git blob: `edc3e4bfdfcac197c171a0173c7b4a666e3ffa0a`.
- Fixed Git blob: `ecde76e000e32f98ee3a3f3c5a722bb462e73f26`.

The complete byte-identical old/fixed modules are checked in under
`tests/fixtures/rulebook-{old,fixed}.py` with TalkCompress's MIT license.
Tests verify upstream Git blob hashes without network or git dependencies.
Both full modules, including real Rule/RuleBook classes and encode/decode
methods, execute locally. No hand-written mutation stands in for the bug.
Expected results use literal string formatting: a known exact source span in
four declared contexts becomes a known literal target. No regex replacement,
consumer function or approximate score is used to compute expected output.
Rules are constructed directly using the public dataclasses; declare/learning,
multiple interacting rules, language inference and LLM quality are outside scope.

## Registered comparison protocol

The finite Cartesian products contain **128 and 512 distinct concrete inputs**:
8 replacement strings × 4 contexts × 2 encode/decode directions × 2 or 8
phrase values. The strings include five unsafe replacements and three controls.
This is deliberately defect-enriched, not a random production workload.
Phrase variants enlarge the product without adding independent historical bugs;
all failures of this template handling problem count as **one defect**.
The extra ASCII-casefold repair in #94 is not counted as another defect.

Each axis value is a one-hot factor; target pairs are all cross-axis pairs
(84 and 168). No within-axis impossible pairs. All candidates are eligible.
Cases are sorted by stable ID. Each method gets the same input population,
pairs, budget and seed; expected values never enter ranking.

- Seeded: existing `random.Random(seed).shuffle` without replacement.
- Greedy: calls the existing `xprobe._greedy_factor_cases` implementation.
- Binary: unchanged `approximate` function copied from xprobe
  `830568a1d20ba5f07b899d5e6a3bbb3e6bb21550` into an experiment-only module.
  Ranks 1/2/4/8; no scaling or inverse-square-root frequency correction;
  16 sign sweeps/component, calibrated scalar, residual deflation. Nonnegative
  clipped reconstructed weights rank remaining candidates against uncovered
  pairs. Exact bitsets update coverage, stable ID breaks ties.
- Budgets: 0, 1, 10, 32, full population. Seeds: 0, 1, 7, 42, 99.
- 2 populations × 5 budgets × 5 seeds × 10 methods = **500 fresh workers**.
  Method order is deterministically shuffled in each cell. No rank/seed tuning
  or selection based on defect outcomes.

Three warmed selection calls measure process CPU nanoseconds, excluding imports,
population construction, oracle execution, tracing and serialization. Allocation
peak comes from a separate traced selection; it excludes prebuilt input/matrix
storage. RSS is the worker lifetime high-water up to that point, including
imports/prebuilt population/tracing, not an incremental ranking measurement.
RSS is bytes on Linux/macOS and null when unavailable (Windows). Numbers must
not be compared directly to the earlier complete-generation timings.
Timing/memory are observations, never CI pass/fail thresholds.

Raw rows separately preserve defect detected (0/1), defect denominator (1),
failing selected input count, selected IDs, pair coverage, CPU samples, Python
allocation peak, worker RSS, exact eligibility exclusions, budget exclusions,
and IDs omitted by approximation. Approximation performs **zero pre-pruning**;
its omitted IDs overlap budget exclusions and must not be added to them.
Dense matrices remain allocated; no memory-saving claim is made.
Full-population old/fixed observations, exact expectations and source SHA-256
hashes are retained with all results, including unfavorable runs.

## Reproduce

```sh
python -S scripts/experiment_consumer_selection.py --output docs/experiments/consumer-selection.json
python -m pytest -q tests/test_consumer_selection_experiment.py tests/test_factor_generation.py
```

The normal CI discovers the offline regression tests. The complete benchmark is
opt-in and has no timing assertion. Raw results are in `consumer-selection.json`.
