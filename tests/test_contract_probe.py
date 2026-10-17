import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET
from unittest.mock import patch

import pytest

from contract_probe import probe, write_junit
from xprobe import cases_from_junit


def document(expected=None):
    return {"schema": "portable-io-cases/1", "cases": [
        {"name": "unicode", "value": {"label": "日本語👩🏽‍💻", "zero": 0},
         "expected": {"label": "日本語👩🏽‍💻", "zero": 0} if expected is None else expected}]}


def target(name="python", code="import sys; print(sys.stdin.read())"):
    return {"name": name, "argv": [sys.executable, "-c", code]}


def test_real_python_and_node_json_adapters():
    node = shutil.which("node")
    if not node:
        pytest.skip("optional Node adapter integration; Python/error regressions still run")
    targets = [target(), {"name": "node", "argv": [node, "-e",
        "process.stdin.setEncoding('utf8');let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>console.log(JSON.stringify(JSON.parse(s))));"]}]
    result = probe(document(), targets)
    assert result["passed"] and result["executions"] == 2
    assert all(row["value"]["label"] == "日本語👩🏽‍💻" for row in result["results"])
    assert not result["native_equivalence_verified"]


def test_two_matching_wrong_implementations_do_not_pass():
    result = probe(document(expected=42), [target(), target("other")])
    assert not result["passed"]
    assert all(not row["passed"] for row in result["results"])


def test_json_boolean_does_not_equal_number():
    cases = {"schema": "portable-io-cases/1", "cases": [{"name": "typed", "value": True, "expected": 1}]}
    assert not probe(cases, [target(), target("other")])["passed"]


def test_pool_overlaps_work_without_exceeding_budget():
    lock = threading.Lock()
    two_active = threading.Event()
    state = {"active": 0, "maximum": 0}

    def process(argv, **options):
        with lock:
            state["active"] += 1
            state["maximum"] = max(state["maximum"], state["active"])
            if state["active"] == 2:
                two_active.set()
        assert two_active.wait(2), "work was serialized"
        with lock:
            state["active"] -= 1
        return subprocess.CompletedProcess(argv, 0, options["input"], "")

    with patch("contract_probe.subprocess.run", side_effect=process):
        result = probe(document(), [target(), target("second"), target("third")], workers=2)
    assert result["passed"] and result["executions"] == 3
    assert state["maximum"] == 2


@pytest.mark.parametrize("code,error", [
    ("raise SystemExit(3)", "RuntimeError"),
    ("print('not JSON')", "JSONDecodeError"),
    ("import time; time.sleep(5)", "TimeoutExpired"),
])
def test_bad_process_does_not_prevent_remaining_cases(code, error):
    result = probe(document(), [target("broken", code), target("healthy")], timeout=1, workers=1)
    assert not result["passed"]
    assert result["results"][0]["error_type"] == error
    assert result["results"][1]["passed"]


@pytest.mark.parametrize("change", [
    lambda doc: doc.update(cases=[]),
    lambda doc: doc["cases"].append(dict(doc["cases"][0])),
    lambda doc: doc["cases"][0].pop("expected"),
    lambda doc: doc["cases"][0].update(expected=float("nan")),
])
def test_invalid_contracts_start_no_process(change):
    data = document()
    change(data)
    with patch("contract_probe.subprocess.run") as run:
        with pytest.raises(ValueError):
            probe(data, [target(), target("other")])
        run.assert_not_called()


def test_cli_failure_receipt_and_status(tmp_path):
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps(document(expected=False)), encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "contract_probe.py"
    result = subprocess.run([sys.executable, "-S", str(script), str(cases),
        "--target", json.dumps(target()), "--target", json.dumps(target("other"))],
        capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "cp1252"})
    assert result.returncode == 1
    assert json.loads(result.stdout)["executions"] == 2


def test_cli_unicode_success_with_non_utf8_parent_console(tmp_path):
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps(document()), encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "contract_probe.py"
    result = subprocess.run([sys.executable, "-S", str(script), str(cases),
        "--target", json.dumps(target()), "--target", json.dumps(target("other"))],
        capture_output=True, text=True, encoding="ascii",
        env={**os.environ, "PYTHONIOENCODING": "cp1252"})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["results"][0]["value"]["label"] == "日本語👩🏽‍💻"


def negative_document():
    return {"schema": "portable-io-cases/1", "context": {"purpose": "deliberate-negative-control"},
        "cases": [{"name": "bad-json", "value": "{", "expected_failures": {
            "first": {"returncode": 1, "stderr_contains": ["JSONDecodeError"]},
            "second": {"returncode": 1, "stderr_contains": ["JSONDecodeError"]}}}]}


def negative_targets():
    code = "import sys,json; json.loads(json.load(sys.stdin))"
    return [target("first", code), target("second", code)]


def test_real_failures_are_preserved_but_acceptance_junit_passes(tmp_path):
    result = probe(negative_document(), negative_targets())
    assert result["passed"]
    assert all(row["returncode"] == 1 and "JSONDecodeError" in row["stderr"] for row in result["results"])
    assert all(row["error_origin"] == "target_exit" for row in result["results"])
    for observed, name, count in [(False, "accept.xml", 0), (True, "observed.xml", 2)]:
        path = tmp_path / name
        write_junit(result, path, observations=observed)
        root = ET.parse(path).getroot()
        assert root.get("failures") == str(count)
        assert len(cases_from_junit(path.read_text(encoding="utf-8"))["cases"]) == count
        if observed:
            assert root.find("testcase/failure").get("type") == "ProcessExit"
        payload = json.loads(root.find("testcase/system-out").text)
        assert payload["input"] == "{" and payload["expectation_kind"] == "process_failure"
        assert "JSONDecodeError" in payload["stderr"]


@pytest.mark.parametrize("code", ["print('{}')", "import sys; print('different failure',file=sys.stderr);sys.exit(1)"])
def test_unexpected_success_or_different_error_fails_negative_contract(code):
    result = probe(negative_document(), [target("first", code), negative_targets()[1]])
    assert not result["passed"] and not result["results"][0]["passed"]


def test_missing_runtime_is_not_the_expected_native_error():
    targets = negative_targets()
    targets[0]["argv"] = ["no-such-native-runtime-xprobe-negative-test"]
    result = probe(negative_document(), targets)
    assert not result["passed"]
    assert result["results"][0]["error_type"] == "FileNotFoundError"
    assert result["results"][0]["error_origin"] == "process_launch_or_io"


@pytest.mark.parametrize("expectation", [None, {}, {"first": {"returncode": 1, "stderr_contains": ["x"]}},
    {name: {"returncode": 0, "stderr_contains": ["x"]} for name in ("first", "second")},
    {name: {"returncode": 1, "stderr_contains": []} for name in ("first", "second")}])
def test_invalid_failure_contract_starts_no_process(expectation):
    data = negative_document()
    data["cases"][0]["expected_failures"] = expectation
    with patch("contract_probe.subprocess.run") as run:
        with pytest.raises(ValueError):
            probe(data, negative_targets())
        run.assert_not_called()


def test_cli_deliberate_failure_emits_both_junit_reports(tmp_path):
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps(negative_document()), encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "contract_probe.py"
    acceptance, observed = tmp_path / "accept.xml", tmp_path / "observe.xml"
    argv = [sys.executable, "-S", str(script), str(cases), "--junit", str(acceptance),
            "--observed-junit", str(observed)]
    for item in negative_targets():
        argv += ["--target", json.dumps(item)]
    completed = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8")
    assert completed.returncode == 0, completed.stderr
    assert ET.parse(acceptance).getroot().get("failures") == "0"
    assert ET.parse(observed).getroot().get("failures") == "2"
