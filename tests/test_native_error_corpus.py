"""Offline integrity and JUnit reuse of real historical language observations."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from contract_probe import write_junit
from xprobe import cases_from_junit

ROOT = Path(__file__).parent / "fixtures/native_error_sweep"
INDEX = json.loads((ROOT / "index.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(INDEX["files"]))
def test_archived_bytes_match_explicit_index(name):
    data = (ROOT / name).read_bytes()
    assert len(data) == INDEX["files"][name]["bytes"]
    assert hashlib.sha256(data).hexdigest() == INDEX["files"][name]["sha256"]


@pytest.mark.parametrize("language", ["dart", "kotlin", "swift"])
def test_actual_receipts_are_complete_and_remain_historical(language):
    record = json.loads((ROOT / (language + ".json")).read_text(encoding="utf-8"))
    cases = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))["cases"]
    assert len(cases) == INDEX["case_count"] == 9
    assert sum("error" in case["expected"] for case in cases) == INDEX["negative_categories"] == 7
    assert record["passed"] and all(row["passed"] for row in record["results"])
    assert not record["native_equivalence_verified"]
    assert not record["context"]["healthy_build_executed_current_run"]
    assert record["context"]["metadata"]["0"]["stdout"].strip() == INDEX["source_commit"]
    assert record["context"]["run_id"] == str(INDEX["run_id"])
    assert record["context"]["source_sha256"]["cases.json"] == INDEX["files"]["cases.json"]["sha256"]
    for target in ("python", "node"):
        rows = {row["name"]: row for row in record["results"] if row["target"] == target}
        assert set(rows) == {case["name"] for case in cases}
        for case in cases:
            assert rows[case["name"]]["input"] == case["input"]
            assert rows[case["name"]]["value"] == case["expected"]
            if "error" in case["expected"]:
                assert rows[case["name"]]["returncode"] != 0
                assert rows[case["name"]]["stderr"]
    if language == "kotlin":
        assert record["context"]["unobserved"] == [{"case": "invalid_json", "reason": cases[7]["kotlin_unobserved"]}]
        native = next(row["value"] for row in record["results"] if row["name"] == "array-length-native-suite")
        for case in cases:
            expected = {"unobserved": case["kotlin_unobserved"]} if "kotlin_unobserved" in case else case["expected"]
            assert native[case["name"]] == expected
    else:
        assert not record["context"]["unobserved"]
        rows = {row["name"]: row for row in record["results"] if row["target"] == language}
        for case in cases:
            assert rows[case["name"]]["input"] == case["input"]
            assert rows[case["name"]]["value"] == case["expected"]
            if "error" in case["expected"]:
                assert all(marker in rows[case["name"]]["stderr"] for marker in case["markers"][language])


@pytest.mark.parametrize("language,failures", [("dart", 21), ("kotlin", 15), ("swift", 21)])
def test_existing_junit_importer_can_collect_real_failure_identities(tmp_path, language, failures):
    record = json.loads((ROOT / (language + ".json")).read_text(encoding="utf-8"))
    for observed, count in ((False, 0), (True, failures)):
        path = tmp_path / ("observed.xml" if observed else "acceptance.xml")
        write_junit(record, path, observations=observed)
        text = path.read_text(encoding="utf-8")
        assert ET.fromstring(text).get("failures") == str(count)
        imported = cases_from_junit(text, repository=INDEX["repository"], commit_sha=INDEX["source_commit"],
                                    report_id="native-" + language + "-" + str(INDEX["run_id"]))
        assert len(imported["cases"]) == count and not imported["truncated"]


def test_kotlin_original_junit_retains_native_failures_and_known_gap():
    root = ET.parse(ROOT / "kotlin-original-junit.xml").getroot()
    assert root.get("tests") == "9" and root.get("failures") == "6" and root.get("skipped") == "1"
    skipped = [case.get("name") for case in root.findall("testcase") if case.find("skipped") is not None]
    assert skipped == ["invalid_json"]
    text = (ROOT / "kotlin-original-junit.xml").read_text(encoding="utf-8")
    imported = cases_from_junit(text)
    assert len(imported["cases"]) == 6
