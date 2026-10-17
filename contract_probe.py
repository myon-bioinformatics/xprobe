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
import sys
import xml.etree.ElementTree as ET

from xprobe import run_cases


def canonical(value):
    """Compare JSON types exactly (Python True must not equal JSON number 1)."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def probe(document, targets, *, timeout=10, workers=2, cwd=None):
    if not isinstance(document, dict) or document.get("schema") != "portable-io-cases/1":
        raise ValueError("expected portable-io-cases/1")
    cases = document.get("cases")
    contract_sha = hashlib.sha256(canonical(document).encode("utf-8")).hexdigest()
    if not isinstance(cases, list) or not cases:
        raise ValueError("nonempty explicit cases required")
    names = set()
    prepared = []
    for case in cases:
        if (not isinstance(case, dict) or not {"name", "value"} <= case.keys()
                or ("expected" in case) == ("expected_failures" in case) or "raises" in case):
            raise ValueError("each case needs name/value and exactly one expectation")
        name = case["name"]
        if not isinstance(name, str) or not name or name in names:
            raise ValueError("case names must be unique nonempty strings")
        names.add(name)
        prepared.append({"name": name, "value": canonical(case["value"]),
                         "expected": canonical(case.get("expected")),
                         "expected_failures": case.get("expected_failures"),
                         "expects_failure": "expected_failures" in case,
                         "context": case.get("context")})
    if type(workers) is not int or not 1 <= workers <= 8:
        raise ValueError("workers must be 1..8")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive and finite")
    if not isinstance(targets, list) or len(targets) < 2:
        raise ValueError("at least two explicit targets required")
    canonical(targets)
    target_names = set()
    for target in targets:
        if not isinstance(target, dict) or not isinstance(target.get("name"), str) or not target["name"] or target["name"] in target_names:
            raise ValueError("target names must be unique nonempty strings")
        target_names.add(target["name"])
        argv = target.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) and "\0" not in arg for arg in argv) or not argv[0]:
            raise ValueError("target argv must be a nonempty string array")
    for case in prepared:
        failures = case["expected_failures"]
        if failures is None:
            # A null expected_failures is invalid, not an expected JSON null.
            if case["expects_failure"]:
                raise ValueError("expected_failures must name every target")
            continue
        if not isinstance(failures, dict) or set(failures) != target_names:
            raise ValueError("expected_failures must name every target")
        for expectation in failures.values():
            if (not isinstance(expectation, dict)
                    or set(expectation) != {"returncode", "stderr_contains"}
                    or type(expectation["returncode"]) is not int or expectation["returncode"] == 0
                    or not isinstance(expectation["stderr_contains"], list)
                    or not expectation["stderr_contains"]
                    or not all(isinstance(token, str) and token for token in expectation["stderr_contains"])):
                raise ValueError("expected failure requires nonzero returncode and nonempty stderr markers")
    cwd = str(Path(cwd or os.getcwd()).resolve())
    if not Path(cwd).is_dir():
        raise ValueError("cwd must be an existing directory")

    def execute(task):
        target, case = task
        details = {}
        failure = (case["expected_failures"] or {}).get(target["name"])
        expected = canonical(failure) if failure is not None else case["expected"]

        def invoke(payload):
            try:
                done = subprocess.run(target["argv"], input=payload, text=True,
                                      encoding="utf-8", capture_output=True,
                                      timeout=timeout, cwd=cwd, shell=False,
                                      env={**os.environ, "PYTHONIOENCODING": "utf-8"})
                details.update(returncode=done.returncode, stdout=done.stdout, stderr=done.stderr,
                               error_origin="target_exit" if done.returncode else None)
                if failure is not None:
                    return canonical({"returncode": done.returncode,
                        "stderr_contains": [token for token in failure["stderr_contains"] if token in done.stderr]})
                if done.returncode:
                    raise RuntimeError("target exited unsuccessfully")
                return canonical(json.loads(done.stdout))
            except (OSError, ValueError, subprocess.TimeoutExpired, RuntimeError) as error:
                details["error"] = str(error)
                details["error_origin"] = ("supervision_timeout" if isinstance(error, subprocess.TimeoutExpired)
                    else "process_launch_or_io" if isinstance(error, OSError)
                    else "adapter_protocol" if isinstance(error, ValueError) else "target_exit")
                raise

        result = run_cases(invoke, [{"name": case["name"], "value": case["value"], "expected": expected}])["results"][0]
        value = result["value"]
        result.update(target=target["name"], value=json.loads(value) if value is not None else None,
                      input=json.loads(case["value"]), case_context=case["context"],
                      expected=json.loads(expected),
                      expectation_kind="process_failure" if failure is not None else "json_value", **details)
        return result

    tasks = [(target, case) for target in targets for case in prepared]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(execute, tasks))
    return {"schema": "portable-io-results/1", "scope": "explicit-json-io-contracts",
            "passed": all(row["passed"] for row in results), "cases": len(cases),
            "executions": len(results), "workers": workers, "timeout_seconds": timeout,
            "contract_sha256": contract_sha, "context": document.get("context"),
            "collector_environment": {"python": sys.version, "platform": sys.platform},
            "cwd": cwd, "targets": [{**target, "executable": shutil.which(target["argv"][0])} for target in targets],
            "native_equivalence_verified": False, "results": results}


def write_junit(result, path, *, observations=False):
    """Separate actual process failures from whether explicit expectations passed.

    Observation XML intentionally contains failures; do not use it as the CI
    acceptance report. Existing JUnit identity import deliberately omits payloads,
    so retain this XML and the JSON receipt together as artifacts.
    """
    rows = result["results"]
    def failed(row):
        if observations:
            return row.get("returncode", 0) != 0 or row["error_type"] is not None
        return not row["passed"]
    scope = "process-observations" if observations else "contract-acceptance"
    suite = ET.Element("testsuite", name=scope, tests=str(len(rows)),
                       failures=str(sum(bool(failed(row)) for row in rows)), errors="0", skipped="0")
    properties = ET.SubElement(suite, "properties")
    for name, value in (("scope", scope), ("contract_sha256", result["contract_sha256"]),
                        ("context", json.dumps(result["context"], ensure_ascii=True)),
                        ("collector_environment", json.dumps(result["collector_environment"], ensure_ascii=True)),
                        ("targets", json.dumps(result["targets"], ensure_ascii=True))):
        ET.SubElement(properties, "property", name=name, value=value)
    for row in rows:
        name = json.dumps({"target": row["target"], "case": row["name"]}, ensure_ascii=True)
        case = ET.SubElement(suite, "testcase", classname="xprobe.portable_io", name=name)
        payload = json.dumps(row, ensure_ascii=True, allow_nan=False)
        ET.SubElement(case, "system-out").text = payload
        if failed(row):
            failure_type = ("ProcessExit" if row.get("error_origin") == "target_exit"
                            else "Collector:" + (row["error_type"] or "Unknown")) if observations else "ContractMismatch"
            ET.SubElement(case, "failure", message=scope, type=failure_type).text = payload
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path)
    parser.add_argument("--target", action="append", required=True,
                        help='JSON object: {"name":"python","argv":["python","adapter.py"]}')
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--cwd", type=Path)
    parser.add_argument("--junit", type=Path, help="CI acceptance report")
    parser.add_argument("--observed-junit", type=Path, help="raw failure observations; intentionally may contain failures")
    args = parser.parse_args(argv)
    try:
        paths = [path.resolve() for path in (args.cases, args.junit, args.observed_junit) if path is not None]
        if len(paths) != len(set(paths)):
            raise ValueError("input and report paths must be distinct")
        result = probe(json.loads(args.cases.read_text(encoding="utf-8")),
                       [json.loads(target) for target in args.target],
                       timeout=args.timeout, workers=args.workers, cwd=args.cwd)
        if args.junit:
            write_junit(result, args.junit)
        if args.observed_junit:
            write_junit(result, args.observed_junit, observations=True)
    except (OSError, ValueError, TypeError) as error:
        parser.exit(2, f"{error}\n")
    print(json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
