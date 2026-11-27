# Formal verification of greedy pair bookkeeping

`formal/Coverage.lean` models the coverage updates and marginal masks inside
`xprobe._greedy_factor_cases()`. Runtime remains standard-library-only. Lean is
an optional verification tool, fixed by `formal/lean-toolchain`; Mathlib is not
required. The runner and named-theorem axiom audit are shared through the
[parent's `lean_verify.py`](https://github.com/myon-bioinformatics/myon-bioinformatics/blob/main/lean_verify.py).

## What the proof establishes

A mask bit identifies an **entry in `pairs`**, not a source factor. For example,
a pair referring to source factors 64 and 65 can occupy pair-mask position 0.
With `width = len(pairs)`, the model represents a mask by `BitVec width`.
`covered` starts at zero and accumulates the masks of the chosen cases with OR.
`marginal` intersects a candidate's mask with the complement of that coverage.

| Audited theorem, in namespace `Xprobe` | Property | Python connection |
| --- | --- | --- |
| `covered_exact` | A bit is covered exactly when at least one chosen mask contains it | `covered = 0` and `covered |= masks[case['id']]` over any chosen prefix |
| `selected_prefix_monotone` | Extending the chosen prefix cannot lose a covered bit | Successive coverage updates |
| `marginal_exact` | A marginal bit is set exactly when the candidate contains it and every previously chosen mask lacks it | The argument of `_factor_popcount(masks[remaining[index]['id']] & ~covered)` |

These statements hold for arbitrary widths and finite chosen sequences, not
just the built-in 42 pairs. They establish exact bookkeeping: neither invented
coverage nor double counting of an already covered pair in a later gain.
`marginal_exact` quantifies indices inside the finite pair universe. Width zero
has no such indices and represents an empty universe.

## Connection tests

`tests/test_formal_coverage_bridge.py` calls the real selector. Its observation
hook records each argument to the real `_factor_popcount` and preserves that
function's return value. The test consumes these observed batches in the order
of the actual returned selection; it does not implement a second greedy picker.
An independent set-inclusion check derives which source factors satisfy each
pair, then checks every scored mask against the pairs absent from the previously
chosen cases. It also checks the observed score against the set's cardinality.

The tests cover all 512 assignments of three pair masks to three candidates at
five budgets (2,560 cases), partial two-factor pairs, repeated pair descriptions,
empty inputs, zero-gain budget filling, pair widths through 257, and source
factor positions through 512. Seven budgets also run the public generator on
the actual built-in corpus. Synthetic private-selector inputs exercise mask
boundaries; they do not add a public preset-extension API.

The existing `tests/test_factor_popcount.py` remains the independent greedy
selection oracle, including tie behavior and the Python 3.9 popcount fallback.
`tests/test_factor_generation.py` covers the public schema, count accounting,
budget caps, and consumer checks. The new tests specifically observe the
intermediate masks used for scoring.

## Assumptions and limits

Candidate IDs are unique and source bitsets are nonnegative integers. The
per-candidate pair masks fit `width` bits, as intended by enumerating the pair
list. Under that condition, finite-width complement gives the same masked
result as Python's arbitrary-precision `mask & ~covered`; Python's negative
intermediate complement cannot introduce a bit outside `mask`.

The Lean model accepts a chosen sequence. It does not prove the Python mask
construction, `max`, sorting, integer popcount, ID uniqueness, or selection
budget control. Those connections are exercised by finite Python tests. It
also does not prove that the final selection is globally optimal or fully
covers the candidate universe. A zero-gain candidate can still fill the budget.
The public generator reports selected cases and matrix evidence, rather than an
internal `covered` mask; this proof does not add a new output field.

Pair co-occurrence in a finite input pool is separate from consumer behavior,
fault detection, or coverage of every possible input. Neither the theorem nor
the connection tests turn those measures into a correctness guarantee. Python
regressions and Lean verification remain separate evidence; the Python module
has not been translated into or completely verified by Lean.

## Run

The connection tests need no Lean or third-party packages:

```sh
python -S -m unittest discover -s tests -p test_formal_coverage_bridge.py -v
```

With the parent repository checked out alongside this repository as
`myon-bioinformatics`, run the shared verifier:

```sh
python -S ../myon-bioinformatics/lean_verify.py \
  --cwd formal --required --json-output build/lean-verification.json \
  --theorem Xprobe.covered_exact \
  --theorem Xprobe.selected_prefix_monotone \
  --theorem Xprobe.marginal_exact \
  Coverage.lean
```

The dedicated CI lane uses the shared workflow at a fixed parent commit. A
missing Lean toolchain is **unverified**, which fails that required lane. Proof
failure, warnings, `sorryAx`, and unexpected axiom dependencies also fail. Normal
runtime and Python tests do not require Lean.
