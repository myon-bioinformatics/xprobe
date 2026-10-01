import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import xprobe


def native(outcome="failed", *, finish=True, dropped=0):
    values = [
        {"event": "start", "schema": "xprobe.pytest.v1"},
        {"event": "report", "phase": "call", "outcome": outcome},
    ]
    if finish:
        values.append({"event": "finish", "exitstatus": 1, "complete": not dropped,
                       "dropped": dropped, "records_before_finish": 2,
                       "phase_outcomes": {outcome: 1}})
    return [dict(id=str(i), category="pytest_session", value=v, reason="observed",
                 context={"report_id": "run1", "commit_sha": None})
            for i, v in enumerate(values)]


def write_report(root, rows):
    (root / "reports").mkdir(exist_ok=True)
    (root / "reports/events.jsonl").write_text(xprobe.corpus_to_json(rows, jsonl=True))


def test_no_args(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("SECRET_TOKEN=do-not-print\n")
    assert xprobe.main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["configuration_categories"]["secret_like"] == 1
    assert "do-not-print" not in json.dumps(result)
    assert result["next_checks"]


@pytest.mark.parametrize("outcome", ["failed", "error", "xpass_strict", "xfail", "xpass", "passed", "skipped"])
def test_native_summary(tmp_path, outcome):
    write_report(tmp_path, native(outcome))
    report = xprobe.overview(tmp_path, evidence=True)
    assert not report["errors"]
    assert report["evidence"][0]["complete"]
    assert report["evidence"][0]["phase_outcomes"] == {outcome: 1}
    evidence_checks = [item for item in report["next_checks"]
                       if "failed phases" in item or "expected-failure" in item]
    assert bool(evidence_checks) == (outcome not in ("passed", "skipped"))


@pytest.mark.parametrize("finish,dropped", [(False, 0), (True, 1)])
def test_incomplete(tmp_path, capsys, finish, dropped):
    write_report(tmp_path, native(finish=finish, dropped=dropped))
    assert xprobe.main(["--root", str(tmp_path), "--evidence"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert not report["evidence"][0]["complete"]


def test_junit_is_not_completion_proof(tmp_path):
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports/fail.xml").write_text(
        '<testsuite><testcase name="secret[param]"><failure message="private"/></testcase></testsuite>')
    report = xprobe.overview(tmp_path, evidence=True)
    assert report["evidence"][0]["failure_identities"] == 1
    assert "private" not in json.dumps(report)
    assert "secret" not in json.dumps(report)
    assert "complete" not in report["evidence"][0]


@pytest.mark.parametrize("text", ["not json", "<!DOCTYPE x><x/>", ""])
def test_malformed(tmp_path, text):
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports/bad.xml").write_text(text)
    assert xprobe.overview(tmp_path, evidence=True)["errors"]


@pytest.mark.parametrize("edit", [
    lambda r: r[0]["value"].update(schema="unknown"),
    lambda r: r[1].update(context={"report_id": "other"}),
    lambda r: r[1]["value"].update(phase="unknown"),
    lambda r: r[1]["value"].update(outcome="unknown"),
    lambda r: r[-1]["value"].update(exitstatus=True),
    lambda r: r[-1]["value"].update(records_before_finish=999),
    lambda r: r[0].update(context={}),
    lambda r: r[1].update(value="not an object"),
    lambda r: r[-1]["value"].update(phase_outcomes={}),
])
def test_invalid_native(tmp_path, edit):
    rows = native()
    edit(rows)
    write_report(tmp_path, rows)
    assert xprobe.overview(tmp_path, evidence=True)["errors"]


def test_bounds(tmp_path):
    (tmp_path / "a.json").write_text('{"KEY": "' + "x" * 30 + '"}')
    (tmp_path / "b.json").write_text("{}")
    assert xprobe.overview(tmp_path, max_bytes=4)["truncated"]
    assert xprobe.overview(tmp_path, max_entries=1)["truncated"]
    with pytest.raises(ValueError):
        xprobe.overview(tmp_path, max_entries=1001)
    with pytest.raises(ValueError):
        xprobe.overview(tmp_path, max_bytes=0)


def test_symlinks(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    try:
        (root / ".github").symlink_to(outside, target_is_directory=True)
        (root / "reports").symlink_to(outside, target_is_directory=True)
        (root / "secret.json").symlink_to(outside / "absent")
    except OSError:
        pytest.skip("symlink unavailable")
    assert len(xprobe.overview(root, evidence=True)["skipped"]) == 3
    with pytest.raises(ValueError):
        xprobe.overview(root / "reports")


def test_file_error(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text("{}")
    original = Path.open
    def deny(path, *args, **kwargs):
        if path.name == "config.json":
            raise PermissionError("never disclose")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", deny)
    assert xprobe.overview(tmp_path)["errors"][0]["reason"] == "PermissionError"


def test_bad_root(tmp_path, capsys):
    assert xprobe.main(["--root", str(tmp_path / "missing")]) == 2
    assert capsys.readouterr().err == "FileNotFoundError\n"


def test_standalone(tmp_path):
    script = tmp_path / "standalone.py"
    script.write_bytes((Path(__file__).parents[1] / "xprobe.py").read_bytes())
    result = subprocess.run([sys.executable, "-S", str(script)], cwd=tmp_path,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["scope"] == "shallow_known_locations"


def test_real_native_pytest_evidence(tmp_path):
    (tmp_path / "test_failure.py").write_text("def test_fails():\n    assert False\n")
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[1]))
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "scripts.xprobe_pytest", "-q",
         "--xprobe-jsonl=reports/events.jsonl"], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=30)
    assert proc.returncode == 1, proc.stderr
    report = xprobe.overview(tmp_path, evidence=True)
    assert not report["errors"], report
    assert report["evidence"][0]["complete"]
    assert report["evidence"][0]["exitstatus"] == 1
    assert report["evidence"][0]["phase_outcomes"]["failed"] == 1
    assert report["next_checks"]


def test_daily_without_test_environment(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/main.py").write_text("# TODO example\nraise NotImplementedError\n")
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports/bad.xml").write_text("this is not XML")
    assert xprobe.main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert not result["errors"]
    assert not result["evidence"]
    assert {row["signal"] for row in result["source_signals"]} == {"todo", "unimplemented"}
    assert all("text" not in row for row in result["source_signals"])
    assert not any("pytest" in suggestion for suggestion in result["next_checks"])


@pytest.mark.parametrize("pattern,code", [("TODO", 0), ("absent", 1)])
def test_direct_search(tmp_path, capsys, pattern, code):
    (tmp_path / "sample.txt").write_text("TODO user text\n")
    assert xprobe.main(["--root", str(tmp_path), "--search", pattern]) == code
    report = json.loads(capsys.readouterr().out)
    assert bool(report["matches"]) == (code == 0)


def test_source_signal_limit(tmp_path):
    (tmp_path / "example.py").write_text("TODO\n" * 101)
    result = xprobe.overview(tmp_path)
    assert result["truncated"]
    assert len(result["source_signals"]) == 100


def test_total_signal_bound(tmp_path):
    (tmp_path / "a.py").write_text("TODO\n" * 100)
    (tmp_path / "b.py").write_text("TODO\n" * 100)
    result = xprobe.overview(tmp_path, max_entries=150)
    assert result["truncated"]
    assert len(result["source_signals"]) == 150
