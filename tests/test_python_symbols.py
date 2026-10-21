"""Static name discovery, checked against real unittest name collection."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

import pytest

import xprobe

ROOT = Path(__file__).resolve().parents[1]


def test_short_names_match_unittest_loader_without_running_tests():
    # Only this controlled in-memory class is inspected by unittest.
    class TestProbe(unittest.TestCase):
        def test_alpha(self):
            raise AssertionError("must never run")

        def test_beta(self):
            raise AssertionError("must never run")

        def helper(self):
            pass

    source = "class TestProbe:\n def test_beta(self): pass\n def helper(self): pass\n def test_alpha(self): pass\n"
    assert [r["name"] for r in xprobe.python_symbols(source, pattern="test_*")] == (
        unittest.TestLoader().getTestCaseNames(TestProbe))


def test_nested_async_conditional_definitions_and_no_execution(tmp_path):
    marker = tmp_path / "executed"
    source = f'''from pathlib import Path
Path({str(marker)!r}).touch()
raise RuntimeError("import must not run")
import nonexistent_dependency
fake = "def test_fake(): pass"
# def test_comment(): pass
class TestOuter:
    @unknown_decorator()
    async def test_async(self):
        def helper(): pass
    class Inner:
        def test_sync(self): pass
if False:
    def test_conditional(): pass
'''
    rows = xprobe.python_symbols(source, pattern="TestOuter.*")
    assert [(r["qualname"], r["kind"], r["line"]) for r in rows] == [
        ("TestOuter.Inner", "class", 11),
        ("TestOuter.Inner.test_sync", "function", 12),
        ("TestOuter.test_async", "async_function", 9),
        ("TestOuter.test_async.helper", "function", 10),
    ]
    assert [r["name"] for r in xprobe.python_symbols(source, pattern="test_*")] == [
        "test_sync", "test_async", "test_conditional"]
    assert not marker.exists()


def test_case_patterns_duplicates_and_source_encodings():
    source = b"# coding: latin-1\n# caf\xe9\ndef Test_A(): pass\ndef test_b(): pass\ndef test_b(): pass\n"
    assert xprobe.python_symbols(source, pattern="test_[ab]") == [
        {"name": "test_b", "qualname": "test_b", "kind": "function", "line": 4},
        {"name": "test_b", "qualname": "test_b", "kind": "function", "line": 5},
    ]
    assert xprobe.python_symbols(b"\xef\xbb\xbfdef work(): pass")[0]["name"] == "work"
    assert xprobe.python_symbols("# only a comment") == []
    assert xprobe.python_symbols("def work(): pass", pattern="missing*") == []


@pytest.mark.parametrize("source,options,error", [
    (None, {}, TypeError), ([], {}, TypeError),
    ("", {"pattern": None}, TypeError), ("", {"pattern": ""}, ValueError),
    ("def bad(", {}, SyntaxError), (b"\xff", {}, SyntaxError),
])
def test_invalid_source_and_options(source, options, error):
    with pytest.raises(error):
        xprobe.python_symbols(source, **options)


def test_cli_json_brief_empty_exact_limit_and_truncation(tmp_path, capsys):
    path = tmp_path / "sample.py"
    path.write_text("def beta(): pass\ndef alpha(): pass\n", encoding="utf-8")
    args = ["--symbols", str(path)]
    assert xprobe.main(args + ["--max-matches", "2"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert not report["truncated"]
    assert [r["name"] for r in report["symbols"]] == ["alpha", "beta"]
    assert xprobe.main(args + ["--max-matches", "1"]) == 2
    assert json.loads(capsys.readouterr().out)["truncated"]
    assert xprobe.main(args + ["--brief", "--max-matches", "1"]) == 2
    assert "truncated: raise --max-matches" in capsys.readouterr().out
    assert xprobe.main(args + ["--brief", "--symbol-pattern", "beta"]) == 0
    assert capsys.readouterr().out == f"{path}:1: function beta\n"
    assert xprobe.main(args + ["--symbol-pattern", "missing"]) == 1
    assert json.loads(capsys.readouterr().out)["symbols"] == []


def test_cli_rejects_bad_missing_and_oversized_inputs(tmp_path, capsys):
    path = tmp_path / "bad.py"
    path.write_text("def sentinel_secret(\n", encoding="utf-8")
    for args, reason in [
        (["--symbols", str(path)], "SyntaxError"),
        (["--symbols", str(path), "--max-bytes", "1"], "ValueError"),
        (["--symbols", str(path), "--max-matches", "0"], "ValueError"),
        (["--symbols", str(tmp_path / "missing.py")], "FileNotFoundError"),
    ]:
        assert xprobe.main(args) == 2
        output = capsys.readouterr()
        assert output.out == "" and output.err == reason + "\n"


def test_cli_rejects_symbolic_link(tmp_path, capsys):
    target = tmp_path / "target.py"
    target.write_text("def probe(): pass\n", encoding="utf-8")
    link = tmp_path / "link.py"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    assert xprobe.main(["--symbols", str(link)]) == 2
    assert capsys.readouterr().err == "ValueError\n"


def test_single_file_works_without_site_packages(tmp_path):
    # A vendored xprobe.py and target with a top-level failure: no imports/run.
    (tmp_path / "xprobe.py").write_bytes((ROOT / "xprobe.py").read_bytes())
    (tmp_path / "target.py").write_text("raise RuntimeError('do not execute')\ndef probe(): pass\n", encoding="utf-8")
    result = subprocess.run([sys.executable, "-S", "xprobe.py", "--symbols", "target.py"],
                            cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["symbols"][0]["name"] == "probe"
