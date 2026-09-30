"""Stdlib-only search and failure probes; copy this file to vendor it.

Importing this module performs no I/O. Probes execute only caller-supplied
callables, and are not a sandbox or a timeout mechanism.
"""

import os
import re
import stat
from pathlib import Path

__version__ = "0.1.0"
__all__ = ["search_text", "search_files", "boundary_cases", "run_cases"]


def _limit(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(name + " must be a positive integer")


def _pattern(pattern, regex, ignore_case):
    if not isinstance(pattern, str) or not pattern:
        raise ValueError("pattern must be a non-empty string")
    return re.compile(pattern if regex else re.escape(pattern),
                      re.IGNORECASE if ignore_case else 0)


def _matches(text, compiled):
    for number, line in enumerate(text.splitlines(), 1):
        for match in compiled.finditer(line):
            yield {"line": number, "column": match.start() + 1,
                   "end_column": match.end() + 1,
                   "match": match.group(), "text": line}


def search_text(text, pattern, *, regex=False, ignore_case=False,
                max_matches=1000):
    """Return non-overlapping, line-local matches with 1-based coordinates.

    end_column is exclusive. Literal search is the default. Empty patterns
    are rejected; regex syntax errors propagate as re.error.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    _limit(max_matches, "max_matches")
    compiled = _pattern(pattern, regex, ignore_case)
    result = []
    for match in _matches(text, compiled):
        result.append(match)
        if len(result) == max_matches:
            break
    return result


def search_files(root, pattern, *, regex=False, ignore_case=False,
                 include_hidden=False, max_bytes=1_000_000,
                 max_matches=1000, encoding="utf-8"):
    """Search a file or directory, returning matches, skipped files and errors.

    Sorted traversal; symlinks and special files are never deliberately read.
    Binary/NUL, oversized and undecodable files are reported as skipped.
    Read/walk errors are reported, not interpreted as no matches. No gitignore
    interpretation; hidden entries are excluded by default. Root path errors
    raise OSError. Ordinary concurrent filesystem changes are not isolated.
    """
    _limit(max_bytes, "max_bytes")
    _limit(max_matches, "max_matches")
    compiled = _pattern(pattern, regex, ignore_case)
    # Validate codec even when no files are encountered.
    "".encode(encoding)
    root = Path(root)
    mode = root.lstat().st_mode
    if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
        raise ValueError("root must be a regular file or directory, not a symlink")
    report = {"matches": [], "skipped": [], "errors": [], "truncated": False}

    def label(path):
        return path.relative_to(root).as_posix() if root.is_dir() else path.name

    def candidates():
        if stat.S_ISREG(mode):
            yield root
            return
        def walk_error(error):
            report["errors"].append({"path": str(error.filename),
                                     "reason": type(error).__name__})
        for directory, dirs, files in os.walk(root, followlinks=False,
                                              onerror=walk_error):
            dirs[:] = sorted(d for d in dirs if
                             (include_hidden or not d.startswith(".")) and
                             not (Path(directory) / d).is_symlink())
            for filename in sorted(files):
                if include_hidden or not filename.startswith("."):
                    yield Path(directory) / filename

    for path in candidates():
        name = label(path)
        try:
            mode_now = path.lstat().st_mode
            if not stat.S_ISREG(mode_now):
                report["skipped"].append({"path": name, "reason": "non_regular"})
                continue
            with path.open("rb") as stream:
                data = stream.read(max_bytes + 1)
            if len(data) > max_bytes:
                reason = "too_large"
            elif b"\x00" in data:
                reason = "binary"
            else:
                reason = None
            if reason:
                report["skipped"].append({"path": name, "reason": reason})
                continue
            try:
                text = data.decode(encoding)
            except UnicodeError:
                report["skipped"].append({"path": name, "reason": "decode_error"})
                continue
            for match in _matches(text, compiled):
                # Look one match ahead, so exactly max_matches is not truncated.
                if len(report["matches"]) == max_matches:
                    report["truncated"] = True
                    return report
                report["matches"].append({"path": name, **match})
        except OSError as error:
            report["errors"].append({"path": name, "reason": type(error).__name__})
    return report


def boundary_cases(kind="text"):
    """Return fresh named input values; no target function is inferred.

    These are test inputs, not assertions that every target must reject them.
    """
    if kind == "text":
        values = [("empty", ""), ("space", " "), ("newline", "\n"),
                  ("nul", "\x00"), ("unicode", "日本語🙂"),
                  ("long", "x" * 4096)]
    elif kind == "number":
        values = [("negative", -1), ("zero", 0), ("positive", 1),
                  ("large", 2 ** 63), ("none", None), ("wrong_type", "1")]
    else:
        raise ValueError("kind must be text or number")
    return [{"name": name, "value": value} for name, value in values]


def run_cases(function, cases):
    """Call function(value) and check explicit per-case expectations.

    Each case needs name/value and exactly one of expected or raises (an
    Exception subclass). Validate the full case list before any execution.
    Return raw observed values for Python callers. Unexpected Exception is
    recorded; KeyboardInterrupt/SystemExit propagate. No subprocess/shell,
    isolation, timeout or automatic target discovery.
    """
    if not callable(function):
        raise TypeError("function must be callable")
    cases = list(cases)
    names = set()
    for case in cases:
        if not isinstance(case, dict) or not {"name", "value"} <= case.keys():
            raise ValueError("case needs name and value")
        name = case["name"]
        if not isinstance(name, str) or not name or name in names:
            raise ValueError("case names must be non-empty and unique")
        names.add(name)
        if ("expected" in case) == ("raises" in case):
            raise ValueError("case needs exactly one of expected or raises")
        error_type = case.get("raises")
        if "raises" in case and not (isinstance(error_type, type) and
                                      issubclass(error_type, Exception)):
            raise ValueError("raises must be an Exception subclass")
    results = []
    for case in cases:
        result = {"name": case["name"], "passed": False, "value": None,
                  "error_type": None}
        try:
            value = function(case["value"])
        except Exception as error:
            result["error_type"] = type(error).__name__
            result["passed"] = ("raises" in case and
                                isinstance(error, case["raises"]))
        else:
            result["value"] = value
            if "expected" in case:
                result["passed"] = bool(value == case["expected"])
        results.append(result)
    return {"passed": all(r["passed"] for r in results), "results": results}
