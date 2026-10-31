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
(84 and 168). This is a consumer-specific factor schema: absolute pair
counts cannot be compared with the earlier experiment's 42 pairs; method
comparisons are within the same population. No within-axis impossible pairs. All candidates are eligible.
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
  Saved measurements use `--jobs 4` on an 8-CPU-quota / 8-GiB host; workers
  are separate processes, with at most four concurrent selections. CPU time
  is per process; shared caches/scheduling can still affect measurements.
  Default `--jobs 1` permits a sequential reproduction; neither configuration
  establishes wall-time scaling or an exclusive-host performance guarantee.
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
python -S scripts/experiment_consumer_selection.py --jobs 4 --output docs/experiments/consumer-selection.json
python -m pytest -q tests/test_consumer_selection_experiment.py tests/test_factor_generation.py
```

The normal CI discovers the offline regression tests. The complete benchmark is
opt-in and has no timing assertion. Raw results are archived in `consumer-selection.json.gz`.

For a compact archive after reproduction (the experiment itself writes plain
JSON), use deterministic standard gzip:

```sh
python -c "import gzip,pathlib; p=pathlib.Path('docs/experiments/consumer-selection.json'); p.with_suffix('.json.gz').write_bytes(gzip.compress(p.read_bytes(), mtime=0))"
```

The checked-in archive is `consumer-selection.json.gz`; decompress with the
standard-library `gzip` module. No external dataset or model downloads needed.

## Saved results

Historical detection is a fraction of five seeds, each with one defect as denominator.
Failing-input counts are not additional independent defects.

### 128 candidates

| Method | Detected seeds: budgets 0 / 1 / 10 / 32 / full (each /5) | Budget-10 pairs | CPU ms, median | Python peak KiB, median | Worker RSS MiB, median |
| --- | --- | --- | --- | --- | --- |
| binary-1-frequency | 0 / 0 / 0 / 5 / 5 | 22–22 / 84 | 27.806 | 1360.9 | 20.54 |
| binary-1-none | 0 / 0 / 0 / 5 / 5 | 22–25 / 84 | 29.615 | 1399.6 | 20.56 |
| binary-2-frequency | 0 / 0 / 0 / 5 / 5 | 22–22 / 84 | 50.962 | 1361.0 | 20.39 |
| binary-2-none | 0 / 0 / 3 / 5 / 5 | 23–25 / 84 | 47.374 | 1399.7 | 20.56 |
| binary-4-frequency | 0 / 2 / 4 / 5 / 5 | 22–34 / 84 | 96.163 | 1345.6 | 20.38 |
| binary-4-none | 0 / 3 / 5 / 5 / 5 | 25–36 / 84 | 86.533 | 1367.6 | 20.39 |
| binary-8-frequency | 0 / 3 / 5 / 5 / 5 | 36–43 / 84 | 184.770 | 1332.9 | 20.23 |
| binary-8-none | 0 / 3 / 5 / 5 / 5 | 35–38 / 84 | 177.191 | 1338.0 | 20.23 |
| greedy | 0 / 0 / 5 / 5 / 5 | 50–50 / 84 | 1.195 | 10.2 | 16.71 |
| seeded | 0 / 3 / 5 / 5 / 5 | 38–45 / 84 | 0.027 | 4.2 | 16.84 |

### 512 candidates

| Method | Detected seeds: budgets 0 / 1 / 10 / 32 / full (each /5) | Budget-10 pairs | CPU ms, median | Python peak KiB, median | Worker RSS MiB, median |
| --- | --- | --- | --- | --- | --- |
| binary-1-frequency | 0 / 0 / 0 / 0 / 5 | 25–31 / 168 | 248.979 | 10477.4 | 62.18 |
| binary-1-none | 0 / 0 / 0 / 1 / 5 | 31–31 / 168 | 230.096 | 10932.2 | 62.68 |
| binary-2-frequency | 0 / 1 / 1 / 2 / 5 | 25–29 / 168 | 463.488 | 10593.8 | 61.19 |
| binary-2-none | 0 / 0 / 0 / 3 / 5 | 27–32 / 168 | 456.165 | 10932.2 | 62.68 |
| binary-4-frequency | 0 / 1 / 5 / 5 / 5 | 28–35 / 168 | 819.177 | 10497.9 | 60.71 |
| binary-4-none | 0 / 0 / 4 / 5 / 5 | 25–35 / 168 | 788.420 | 10678.9 | 61.57 |
| binary-8-frequency | 0 / 3 / 5 / 5 / 5 | 22–44 / 168 | 1605.399 | 10388.5 | 60.21 |
| binary-8-none | 0 / 4 / 5 / 5 / 5 | 35–50 / 168 | 1638.854 | 10460.8 | 60.57 |
| greedy | 0 / 0 / 5 / 5 / 5 | 58–58 / 168 | 8.161 | 43.8 | 22.21 |
| seeded | 0 / 5 / 5 / 5 / 5 | 47–50 / 168 | 0.095 | 7.3 | 21.96 |

At full budget every method selects all IDs and covers all target pairs. The old module fails on 80/128 and 320/512 inputs; the fixed module matches the independent expectation on all 640 inputs. All budget-10 selections omit 118 or 502 candidates respectively. Binary omissions are budget omissions, not an extra pruning stage.

## Interpretation and validation

At 512 candidates / budget 10, seeded and greedy detect the defect for 5/5
seeds; binary settings achieve 0–5/5. Greedy covers 58/168 pairs, seeded
47–50 and binary 22–50. Median selection CPU is 8.161 ms for greedy versus
230–1639 ms for binary; Python allocation peak is 43.8 KiB versus roughly
10–11 MiB. The larger product therefore provides no evidence to adopt this
implementation. At budget 1, seeded detects 5/5, greedy 0/5 and binary 0–4/5,
further demonstrating that structural coverage and detection differ.

The two populations contain one additional historical defect, with intentionally high failing-input density (62.5%). Repeated phrase variants and five seeds are not independent defects or estimates of general production sensitivity. Pair coverage is a structural measure, not a fault-detection oracle. This product is larger than the original 36 candidates but still small, dense, hand-designed and not a held-out multi-defect benchmark. No production adoption, memory-saving or general low-rank superiority is supported. All ranks, seeds and unfavorable results are retained.

The archived source hashes identify the measured code. CPU and memory are descriptive measurements from a shared host with four concurrent isolated workers; no performance thresholds or confidence claims. The offline evidence-consistency test re-executes both full historical modules, checks exact expected results and selected/failing IDs, independently reconstructs pair sets, and verifies exclusions and all 500 distinct conditions.

Local complete suite: **693 passed, 27 skipped, 13 subtests passed**. This is
local author validation, not an independent-review or hosted-CI claim.
