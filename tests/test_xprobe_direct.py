import json
from pathlib import Path
import subprocess
import sys

import pytest
import xprobe


def test_default_delegates_to_existing_api(monkeypatch, capsys):
    calls = []
    expected = {"findings": [{"key": "TOKEN", "value": "<redacted>"}],
                "errors": [], "skipped": [], "truncated": False}
    def scan(root, **kwargs):
        calls.append((root, kwargs))
        return expected
    monkeypatch.setattr(xprobe, "scan_config", scan)
    assert xprobe.main([]) == 0
    assert json.loads(capsys.readouterr().out) == expected
    assert calls == [(".", {"max_bytes": 1000000, "max_findings": 1000})]


def test_default_without_test_environment(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("SECRET_TOKEN=private\n")
    assert xprobe.main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["findings"]
    assert "private" not in json.dumps(report)
    assert not (tmp_path / "reports").exists()


@pytest.mark.parametrize("pattern,code", [("TODO", 0), ("absent", 1)])
def test_search(tmp_path, capsys, pattern, code):
    (tmp_path / "a.txt").write_text("TODO example")
    assert xprobe.main(["--root", str(tmp_path), "--search", pattern]) == code
    report = json.loads(capsys.readouterr().out)
    assert bool(report["matches"]) == (code == 0)


def test_existing_corpus(capsys):
    assert xprobe.main(["--corpus"]) == 0
    assert capsys.readouterr().out == xprobe.corpus_to_json(xprobe.known_bad_cases())


@pytest.mark.parametrize("field", ["errors", "skipped", "truncated"])
def test_partial(monkeypatch, capsys, field):
    report = {"findings": [], "errors": [], "skipped": [], "truncated": False}
    report[field] = True if field == "truncated" else ["partial"]
    monkeypatch.setattr(xprobe, "scan_config", lambda *a, **k: report)
    assert xprobe.main([]) == 2


def test_invalid_limit(capsys):
    assert xprobe.main(["--max-bytes", "0"]) == 2
    assert capsys.readouterr().err == "ValueError\n"


def test_standalone_copy(tmp_path):
    script = tmp_path / "tool.py"
    script.write_bytes((Path(__file__).parents[1] / "xprobe.py").read_bytes())
    result = subprocess.run([sys.executable, "-S", str(script)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert "findings" in json.loads(result.stdout)
