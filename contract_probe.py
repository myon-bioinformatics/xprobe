"""Run explicit JSON I/O contracts against caller-selected command adapters.

Each input starts a fresh process. Commands must read one JSON value from stdin
and write one JSON value to stdout. No shell, SDK, browser or target discovery.
This executes trusted local commands; it is not a sandbox or process-tree killer.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess

from xprobe import run_cases


def canonical(value):
    """Compare JSON types exactly (Python True must not equal JSON number 1)."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def probe(document, targets, *, timeout=10, workers=2, cwd=None):
    if not isinstance(document, dict) or document.get("schema") != "portable-io-cases/1":
        raise ValueError("expected portable-io-cases/1")
    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("nonempty explicit cases required")
    names = set()
    prepared = []
    for case in cases:
        if not isinstance(case, dict) or not {"name", "value", "expected"} <= case.keys() or "raises" in case:
            raise ValueError("each case needs name, value and expected JSON")
        name = case["name"]
        if not isinstance(name, str) or not name or name in names:
            raise ValueError("case names must be unique nonempty strings")
        names.add(name)
        prepared.append({"name": name, "value": canonical(case["value"]),
                         "expected": canonical(case["expected"])})
    if type(workers) is not int or not 1 <= workers <= 8:
        raise ValueError("workers must be 1..8")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive and finite")
    if not isinstance(targets, list) or len(targets) < 2:
        raise ValueError("at least two explicit targets required")
    target_names = set()
    for target in targets:
        if not isinstance(target, dict) or not isinstance(target.get("name"), str) or not target["name"] or target["name"] in target_names:
            raise ValueError("target names must be unique nonempty strings")
        target_names.add(target["name"])
        argv = target.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) and "\0" not in arg for arg in argv) or not argv[0]:
            raise ValueError("target argv must be a nonempty string array")
    cwd = str(Path(cwd or os.getcwd()).resolve())
    if not Path(cwd).is_dir():
        raise ValueError("cwd must be an existing directory")

    def execute(task):
        target, case = task
        details = {}

        def invoke(payload):
            try:
                done = subprocess.run(target["argv"], input=payload, text=True,
                                      encoding="utf-8", capture_output=True,
                                      timeout=timeout, cwd=cwd, shell=False,
                                      env={**os.environ, "PYTHONIOENCODING": "utf-8"})
                details.update(returncode=done.returncode, stderr=done.stderr)
                if done.returncode:
                    raise RuntimeError("target exited unsuccessfully")
                return canonical(json.loads(done.stdout))
            except (OSError, ValueError, subprocess.TimeoutExpired, RuntimeError) as error:
                details["error"] = str(error)
                raise

        result = run_cases(invoke, [case])["results"][0]
        value = result["value"]
        result.update(target=target["name"], value=json.loads(value) if value is not None else None,
                      expected=json.loads(case["expected"]), **details)
        return result

    tasks = [(target, case) for target in targets for case in prepared]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(execute, tasks))
    return {"schema": "portable-io-results/1", "scope": "explicit-json-io-contracts",
            "passed": all(row["passed"] for row in results), "cases": len(cases),
            "executions": len(results), "workers": workers, "timeout_seconds": timeout,
            "contract_sha256": hashlib.sha256(canonical(document).encode("utf-8")).hexdigest(),
            "cwd": cwd, "targets": [{**target, "executable": shutil.which(target["argv"][0])} for target in targets],
            "native_equivalence_verified": False, "results": results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path)
    parser.add_argument("--target", action="append", required=True,
                        help='JSON object: {"name":"python","argv":["python","adapter.py"]}')
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--cwd", type=Path)
    args = parser.parse_args(argv)
    try:
        result = probe(json.loads(args.cases.read_text(encoding="utf-8")),
                       [json.loads(target) for target in args.target],
                       timeout=args.timeout, workers=args.workers, cwd=args.cwd)
    except (OSError, ValueError, TypeError) as error:
        parser.exit(2, f"{error}\n")
    print(json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
