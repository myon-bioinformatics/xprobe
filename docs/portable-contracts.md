# Explicit Python / Node I/O contracts

`contract_probe.py` is an optional stdlib CLI beside the vendorable `xprobe.py`.
The single-file artifact and its no-subprocess `run_cases` API are unchanged.
This CLI supplies explicit process adapters to that existing assertion engine.

Create `cases.json` with independently chosen expectations:

```json
{
  "schema": "portable-io-cases/1",
  "cases": [
    {"name": "empty", "value": "", "expected": ""},
    {"name": "unicode", "value": "日本語👩🏽‍💻", "expected": "日本語👩🏽‍💻"}
  ]
}
```

Each adapter reads one JSON value from stdin and writes one JSON value to stdout.
Use the API from Python or pass explicit argv arrays to the CLI:

```sh
python -S contract_probe.py cases.json --target '{"name":"python","argv":["python","python_adapter.py"]}' --target '{"name":"node","argv":["node","node_adapter.mjs"]}' --workers 2 --timeout 10
```

The arrays work without shell interpolation inside the runner. Shell quoting in
the example is for POSIX shells; Python callers on any platform can pass the same
dicts directly to `probe(document, targets, workers=2, timeout=10)`.

- At least two explicitly named targets and nonempty, uniquely named cases are required.
  All specifications are validated before starting a target.
- A bounded thread pool (1–8 slots) supervises fresh direct child processes.
  Finishing/failing/timing-out cases free slots for remaining work. Ordered results
  do not imply sequential execution. Each invocation gets its own timeout.
- Each implementation must satisfy the expected value. Agreement between two
  wrong implementations does not pass. JSON objects compare independently of key
  order; booleans and numbers stay distinct. Version 1 compares canonical JSON
  serializations exactly, including `1` versus `1.0`. Encode exact large integers
  as decimal strings when crossing JavaScript's safe-integer boundary.
- Nonzero exit, invalid JSON, missing executable and timeout are failures with
  receipts; they do not silently skip the target or stop subsequent cases.
- `portable-io-results/1` includes argv, resolved executable, working directory,
  contract SHA-256, actual and expected values, errors and process return codes.
  This does **not** fingerprint a target's full source/dependency closure or
  attest that the tested commands correspond to a published/native build.
- Exit 0: every selected execution meets its explicit contract. Exit 1: at least
  one execution failed. Exit 2: invalid specification or unreadable input.

Commands are trusted local leaf adapters. This is not a sandbox, output-size
limiter, long-running server supervisor or descendant-process cleanup facility.
Adapter subprocesses should not launch detached services or browsers. For
stateful behavior, a case may contain a sequence, with one expected final state
or trace; the adapter must implement and return those transitions. The runner
does not synthesize a backend or native platform automatically.

Use BlueProbe's saved Web structure/geometry/action observations to identify
which contracts are missing, and its source inventory to record relevant files.
Do not automatically turn a producer's old output into the expected answer.
Browser-test-kit continues to own real pointer/navigation/emoji operation tests.
Passing this suite proves only the chosen I/O contracts: not UI rendering,
native permissions, clipboard integration, or Dart/Kotlin/Swift semantic equivalence.

The first external smoke check used Flutter's existing stdlib
`python/conversion_patterns.py` and Node's independent `Buffer` implementation:
empty, ASCII and Japanese/emoji UTF-8-to-base64 contracts, six real executions.
No Flutter, Dart SDK or browser was started. The production application has not
been replaced by these three examples.
