"""Real process runs of xprobe.py: agent exit codes, error JSON and the JUnit collector CI uses.

Collector success is not pytest success.
"""
import json
from pathlib import Path

import pytest

from vendor.cli_args import build_env, pytest_command, run_cli, run_command

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "xprobe.py"

def run(args, **kwargs):
    return run_cli(CLI, *args, timeout=30, env=build_env({"COLUMNS": "160"}), **kwargs)


def error_json(proc):
    assert proc.stdout == ""
    payload = json.loads(proc.stderr)
    assert payload["ok"] is False
    assert payload["exit"] == proc.returncode
    assert set(payload) <= {"ok", "code", "error", "exit", "message"}
    return payload


def test_help_documents_standalone_modes():
    proc = run(["--help"])
    assert proc.returncode == 0
    assert proc.stderr == ""
    for flag in ("--search", "--junit", "--annotate-junit", "--scan-config",
                 "--env-report", "--corpus", "--factor-cases", "--format"):
        assert flag in proc.stdout
    assert "3 partial" in proc.stdout


def test_junit_usage_errors_are_exit_2():
    for args in (["--not-a-real-flag"], ["--max-matches", "many", "--junit", "report.xml"]):
        proc = run(args)
        assert proc.returncode == 2
        assert proc.stdout == ""
        assert "usage:" in proc.stderr


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


def test_search_truncation_keeps_report_and_exits_2(tmp_path):
    (tmp_path / "a.txt").write_text("hit\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("hit\n", encoding="utf-8")
    proc = run(["--search", "hit", "--root", str(tmp_path), "--max-matches", "1"])
    assert proc.returncode == 2
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
    proc = run_command(
        pytest_command(extra=["-c", str(config), "--noconftest", "-p", "no:cacheprovider",
                              str(target), "--junitxml=" + str(report_path)]),
        cwd=tmp_path, timeout=60,
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

    mixed = run(["--search", "pattern", "--junit", str(report_path)])
    assert mixed.returncode == 2
    assert mixed.stdout == ""
    assert "not allowed with argument" in mixed.stderr
    assert "sentinel-secret" not in mixed.stderr


# ──── JUnit collector as CI runs it ────

@pytest.mark.parametrize('source,options,status', [
    (None, [], 2),
    ('<testsuites>', [], 2),
    ('<testsuite><testcase name="one"><failure/></testcase>'
     '<testcase name="two"><error/></testcase></testsuite>', ['--max-matches=1'], 3),
    ('<testsuite><testcase name="ok"/></testsuite>', [], 0),
    ('<testsuite><testcase name="bad"><failure/></testcase></testsuite>', [], 0),
])
def test_collector_does_not_hide_invalid_or_truncated_reports(tmp_path, source, options, status):
    report = tmp_path / 'junit.xml'
    if source is not None:
        report.write_text(source, encoding='utf-8')
    result = run(['--junit', str(report), '--repository=owner/repo', '--report-id=sample', *options])
    assert result.returncode == status
    if status == 2:
        assert result.stdout == ''  # No empty success report synthesized on error.
        failure = json.loads(result.stderr)
        assert failure['ok'] is False and failure['exit'] == 2
        assert failure['code'] in {'io_error', 'invalid_input'}
    elif status == 3:
        imported = json.loads(result.stdout)
        assert imported['truncated'] is True
        assert json.loads(result.stderr)['code'] == 'truncated'
        assert all(row['context']['commit_sha'] is None for row in imported['cases'])
    else:
        imported = json.loads(result.stdout)
        assert imported['truncated'] is False and result.stderr == ''
        assert all(row['context']['commit_sha'] is None for row in imported['cases'])


def test_standalone_reports_preserve_filters_and_hide_env_values(tmp_path):
    (tmp_path / "note.txt").write_text("TODO\n", encoding="utf-8")
    (tmp_path / "skip.json").write_text("TODO\n", encoding="utf-8")
    proc = run(["--search", "todo", "--ignore-case", "--include", "*.txt",
                "--root", str(tmp_path), "--format", "jsonl"])
    assert proc.returncode == 0, proc.stderr
    assert len(proc.stdout.splitlines()) == 1
    assert [row["path"] for row in json.loads(proc.stdout)["matches"]] == ["note.txt"]

    env = build_env({"TOKEN": "sentinel-sensitive-example"})
    proc = run_cli(CLI, "--env-report", "--format", "text", timeout=20, env=env)
    assert proc.returncode == 0, proc.stderr
    assert '"key": "TOKEN"' in proc.stdout
    assert "sentinel-sensitive-example" not in proc.stdout + proc.stderr
