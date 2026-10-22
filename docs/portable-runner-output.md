# Portable runner output selection

Optional stdlib-only `portable_output.py` extracts summary lines from Python or
Node test output. This is a **pure helper**: it never launches processes,
discovers browsers, rewrites Playwright configuration, or infers success from
text. Preserve the subprocess exit code independently.

```python
from portable_output import result_receipt
receipt = result_receipt(7, "1 failed\n", "Error: assertion\n", limit=20)
assert receipt["exit_code"] == 7
```

Use `python -m unittest discover -s tests -p test_portable_output.py`
to check the contract without Playwright. The optional helper deliberately
does not modify the single-file vendorable `xprobe.py` API or introduce a
dependency on a Node or browser installation.

The portfolio's Playwright runner may vendor this small helper or reproduce
its JSON contract, but should not depend on a live checkout of xprobe.
`limit=0` means unlimited matching lines. The default regex matches
Playwright summary/error lines; callers may override it.

When matching lines exceed a positive limit, selection prioritizes `Error:`
and numbered failure diagnostics, then `failed` summaries, from either stream.
Within each priority, earlier stdout lines precede stderr lines. Remaining
space includes at least one matching stderr line, then earlier matching lines.
Selected lines are emitted in their original stdout-then-stderr order;
duplicates are preserved. The pattern still controls which lines are eligible.
If diagnostics alone exceed the limit, only the first matching diagnostics
fit; use `limit=0` or retain the original logs when all details are needed.
