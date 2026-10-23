"""Real process runs of scripts/xprobe_cli.py for agent exit codes and error JSON."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "xprobe_cli.py"

# Help snippets that must appear for every flag. A missing help string fails this.
FLAG_HELP = {
    "pattern": "Literal or regular-expression text to search for",
    "root": "File or directory to search",
    "--regex": "Treat pattern as a Python regular expression",
    "--ignore-case": "Match without case sensitivity",
    "--include-hidden": "Search hidden files and directories",
    "--max-bytes": "Maximum bytes read from each file",
    "--max-matches": "Maximum matches, findings, or JUnit cases",
    "--scan-config": "Discover configuration keys under --root",
    "--env-report": "recognized environment variable names",
    "--corpus": "built-in regression corpus",
    "--factor-cases": "seeded factor-generation cases",
    "--junit": "bounded local JUnit report",
    "--include": "Glob of files to include",
    "--exclude-dir": "Directory name to skip",
    "--category": "Corpus category filter",
    "--repository": "Explicit owner/name for JUnit provenance",
    "--commit-sha": "Full SHA from canonical repository metadata",
    "--report-id": "Unique job/report identity",
    "--seed": "Seed for corpus or factor generation",
    "--count": "Number of generated corpus or factor cases",
    "--format": "Output format: json",
}


def run(args, **kwargs):
    env = os.environ.copy()
    env["COLUMNS"] = "160"
    return subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True,
                          timeout=30, env=env, **kwargs)


def error_json(proc):
    assert proc.stdout == ""
    payload = json.loads(proc.stderr)
    assert payload["ok"] is False
    assert payload["exit"] == proc.returncode
    assert set(payload) <= {"ok", "code", "error", "exit", "message"}
    return payload


def test_help_documents_every_flag_and_exit_3():
    proc = run(["--help"])
    assert proc.returncode == 0
    assert proc.stderr == ""
    for flag, snippet in FLAG_HELP.items():
        assert flag in proc.stdout, flag
        assert snippet in proc.stdout, flag
    assert "3  truncated JUnit report" in proc.stdout
    assert "argparse usage (2)" in proc.stdout
    # --root is both a positional and an option; the option help must be present.
    assert "overrides the positional root" in proc.stdout


def test_usage_errors_are_exit_2_json_and_not_truncation():
    missing_mode = run([])
    assert missing_mode.returncode == 2
    payload = error_json(missing_mode)
    assert payload["code"] == "usage" and payload["error"] == "usage"
    assert "pattern" in payload["message"]

    unknown = run(["--not-a-real-flag"])
    assert unknown.returncode == 2
    unknown_payload = error_json(unknown)
    assert unknown_payload["code"] == "usage"
    assert "--not-a-real-flag" in unknown_payload["message"]

    bad_type = run(["--max-matches", "many", "--junit", "report.xml"])
    assert bad_type.returncode == 2
    assert error_json(bad_type)["code"] == "usage"


def test_invalid_regex_json_does_not_echo_the_pattern(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("hit\n", encoding="utf-8")
    proc = run(["secret-pattern-[", str(target), "--regex"])
    assert proc.returncode == 2
    payload = error_json(proc)
    assert payload["code"] == "regex"
    # 3.12 and earlier spell this re.error; 3.13+ spell it re.PatternError.
    assert payload["error"] in {"error", "PatternError"}
    assert "message" not in payload
    assert "secret-pattern" not in proc.stderr


def test_missing_and_malformed_junit_json_hides_path_and_body(tmp_path):
    missing = tmp_path / "secret-path-token.xml"
    missing_proc = run(["--junit", str(missing), "--repository", "owner/repo", "--report-id", "sample"])
    assert missing_proc.returncode == 2
    missing_payload = error_json(missing_proc)
    assert missing_payload["code"] == "io_error"
    assert missing_payload["error"] == "FileNotFoundError"
    assert "secret-path-token" not in missing_proc.stderr + missing_proc.stdout

    malformed = tmp_path / "junit.xml"
    malformed.write_text("<testsuite>sentinel-secret", encoding="utf-8")
    bad = run(["--junit", str(malformed)])
    assert bad.returncode == 2
    bad_payload = error_json(bad)
    assert bad_payload["code"] == "invalid_input"
    assert bad_payload["error"] == "ValueError"
    assert "sentinel-secret" not in bad.stderr + bad.stdout

    binary = tmp_path / "binary.xml"
    binary.write_bytes(b"<testsuite>\xffsentinel-secret")
    decoded = run(["--junit", str(binary)])
    assert decoded.returncode == 2
    decoded_payload = error_json(decoded)
    assert decoded_payload["code"] == "invalid_input"
    assert decoded_payload["error"] == "UnicodeDecodeError"
    assert "sentinel-secret" not in decoded.stderr + decoded.stdout


def test_byte_limit_is_exit_2_not_truncation(tmp_path):
    path = tmp_path / "junit.xml"
    path.write_text("<testsuite><testcase name='n'><failure/></testcase></testsuite>", encoding="utf-8")
    proc = run(["--junit", str(path), "--max-bytes", "1", "--repository", "owner/repo", "--report-id", "sample"])
    assert proc.returncode == 2
    payload = error_json(proc)
    assert payload["code"] == "invalid_input"
    assert payload["exit"] != 3


def test_case_limit_truncation_exits_3_with_partial_report(tmp_path):
    xml = (
        "<testsuite>"
        "<testcase name='one'><failure/></testcase>"
        "<testcase name='two'><error/></testcase>"
        "</testsuite>"
    )
    path = tmp_path / "junit.xml"
    path.write_text(xml, encoding="utf-8")
    complete = run(["--junit", str(path), "--repository", "owner/repo", "--report-id", "sample"])
    assert complete.returncode == 0
    assert complete.stderr == ""
    complete_report = json.loads(complete.stdout)
    assert complete_report["truncated"] is False
    assert len(complete_report["cases"]) == 2

    truncated = run(["--junit", str(path), "--max-matches", "1",
                     "--repository", "owner/repo", "--report-id", "sample"])
    assert truncated.returncode == 3
    assert truncated.returncode != 2
    report = json.loads(truncated.stdout)
    assert report["truncated"] is True
    assert [row["value"]["test"] for row in report["cases"]] == ["one"]
    notice = json.loads(truncated.stderr)
    assert notice == {
        "code": "truncated",
        "error": "truncated",
        "exit": 3,
        "message": "JUnit case limit reached; partial report is on stdout",
        "ok": False,
    }


def test_search_truncation_stays_exit_0(tmp_path):
    (tmp_path / "a.txt").write_text("hit\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("hit\n", encoding="utf-8")
    proc = run(["hit", str(tmp_path), "--max-matches", "1"])
    assert proc.returncode == 0
    assert proc.stderr == ""
    report = json.loads(proc.stdout)
    assert report["truncated"] is True
    assert len(report["matches"]) == 1


def test_real_pytest_junit_import_and_case_limit(tmp_path):
    target = tmp_path / "test_recorded.py"
    target.write_text(
        "def test_first():\n"
        "    assert False, 'sentinel-secret-one'\n"
        "def test_second():\n"
        "    assert False, 'sentinel-secret-two'\n",
        encoding="utf-8",
    )
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n", encoding="utf-8")
    report_path = tmp_path / "junit.xml"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-c", str(config), "--noconftest", "-p", "no:cacheprovider",
         str(target), "--junitxml=" + str(report_path)],
        cwd=tmp_path, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 1, proc.stderr
    xml = report_path.read_text(encoding="utf-8")
    assert "sentinel-secret-one" in xml and "sentinel-secret-two" in xml

    imported = run(["--junit", str(report_path), "--repository", "owner/repo", "--report-id", "linux-py"])
    assert imported.returncode == 0
    assert imported.stderr == ""
    body = json.loads(imported.stdout)
    assert body["truncated"] is False
    assert {row["value"]["test"] for row in body["cases"]} == {"test_first", "test_second"}
    assert "sentinel-secret-one" not in imported.stdout
    assert "sentinel-secret-two" not in imported.stdout

    limited = run(["--junit", str(report_path), "--max-matches", "1",
                   "--repository", "owner/repo", "--report-id", "linux-py"])
    assert limited.returncode == 3
    limited_body = json.loads(limited.stdout)
    assert limited_body["truncated"] is True
    assert len(limited_body["cases"]) == 1
    assert "sentinel-secret" not in limited.stdout + limited.stderr
    assert json.loads(limited.stderr)["code"] == "truncated"

    mixed = run(["pattern", "--junit", str(report_path)])
    assert mixed.returncode == 2
    mixed_payload = error_json(mixed)
    assert mixed_payload["code"] == "usage"
    assert "sentinel-secret" not in mixed.stderr
