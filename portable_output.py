"""Pure, stdlib-only output selection for Python/Node process runners.

Does not execute subprocesses or interpret test success; caller preserves exit status.
"""
import re

DEFAULT_PATTERN = r"passed|failed|skipped|^\s+\d+\) |Error:"

def select_lines(stdout="", stderr="", *, pattern=DEFAULT_PATTERN, limit=20, flags=0):
    """Return matched lines in stdout-then-stderr order without dropping failures."""
    if not isinstance(stdout, str) or not isinstance(stderr, str):
        raise TypeError("stdout and stderr must be strings")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("limit must be a nonnegative integer")
    expression = re.compile(pattern, flags)
    matched = (line for line in (stdout + "\n" + stderr).splitlines() if expression.search(line))
    if limit == 0:
        return list(matched)
    from itertools import islice
    return list(islice(matched, limit))

def result_receipt(exit_code, stdout="", stderr="", *, timed_out=False, pattern=DEFAULT_PATTERN, limit=20):
    """Produce a JSON-serializable receipt; no subprocess side effects."""
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
        raise TypeError("exit_code must be an integer")
    return {"exit_code": exit_code, "timed_out": bool(timed_out),
            "lines": select_lines(stdout, stderr, pattern=pattern, limit=limit)}
