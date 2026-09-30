# Native pytest observations and exploration

Use pytest's native reports as the Python observation source. JUnit remains a
cross-runner CI interchange format; it is not the reproduction model.

The opt-in test adapter requires pytest, already provided by
`tests/requirements.txt`. `xprobe.py` itself remains independently vendorable,
stdlib-only, and imports without pytest.

```sh
python -m pytest -p scripts.xprobe_pytest \
  --xprobe-jsonl=reports/pytest-events.jsonl \
  --xprobe-repository=owner/repository
```

Use a new output path for every run: existing evidence is never overwritten.
The parent directory is created. A fresh run ID is generated unless supplied by
`--xprobe-run-id`. Only pass `--xprobe-commit-sha` when measured by the canonical
metadata producer; the adapter never reads GitHub SHA environment variables.

Every line satisfies the existing `id/category/value/reason/context` corpus
contract. `value.event` is `start`, `report`, or `finish`. Start declares
`xprobe.pytest.v1`. Report records carry:

- setup/call/teardown or collection phase;
- native pytest outcome and normalized passed/failed/skipped/error/xfail/xpass/
  xpass_strict outcome;
- a parameter-label-free node display plus SHA-256 of the original node ID, so
  parameter variants remain distinct;
- expected-failure and strict-XPASS flags.

These are **phase observations**, not one final result per test. A passed setup
does not mean the test passed; teardown may still fail. The strict-XPASS signal
uses pytest's `[XPASS(strict)]` report string because strict XPASS has no
`wasxfail` attribute; subprocess regressions verify that convention.

The finish record carries pytest's exit status, phase counts and dropped record
count. `complete` means the adapter reached finish without dropping observations,
not that tests passed or every intended test ran. Missing finish means interrupted
or otherwise incomplete evidence. Exit 5 remains "no tests collected". A run with
test failure still exits nonzero. The adapter does not change pytest's result.

`--xprobe-max-records` bounds observation rows (default 10000, maximum 100000).
Start/finish are additional rows; hitting the limit marks incomplete evidence.
Each row is flushed so a terminated process can leave readable partial JSONL.
Serial pytest is supported; xdist execution is rejected until controller/worker
report ownership is implemented.

## Explore with the existing xprobe surface

```sh
python scripts/xprobe_cli.py '"outcome": "xfail"' reports --include '*.jsonl'
python scripts/xprobe_cli.py '"phase": "teardown"' reports --include '*.jsonl'
```

```python
from pathlib import Path
import xprobe

rows = xprobe.corpus_from_json(Path('reports/pytest-events.jsonl').read_text(), jsonl=True)
failures = [row for row in rows
            if row['value'].get('outcome') in {'failed', 'error', 'xpass_strict'}]
```

The rows omit captured output, tracebacks, marker reasons and parameter values.
Hashed identifiers are pseudonymous, not encryption. Test/module names are still
visible. Arbitrary fixture values are never serialized automatically.

To preserve a reproducer, create an explicit corpus case with a new ID and an
`origin_id` referencing an observation. Put the reviewed input in its `value` and
the explanation in `reason`; `merge_cases` validates it. A provided transcript
reference can be added as JSON-compatible context. Neither original inputs nor
causes can be reconstructed reliably from a failed test name. Automatic chat
history ingestion, causal inference and fixture replay are not implemented here.
