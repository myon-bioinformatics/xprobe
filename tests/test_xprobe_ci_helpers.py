"""junit_annotations, portability_findings and multi-root search (CLI included)."""
import json

import pytest

import xprobe

JUNIT = """<?xml version="1.0"?>
<testsuites><testsuite name="s">
  <testcase classname="tests.test_a" name="test_ok"/>
  <testcase classname="tests.test_a" name="test_bad" file="tests/test_a.py" line="9">
    <failure message="assert 1 == 2&#10;more detail">trace</failure></testcase>
  <testcase classname="tests.test_b.TestX" name="test_err[a,b]"><error>boom: 100%</error></testcase>
  <testcase classname="" name="bare"><failure/></testcase>
  <testcase classname="tests.test_c" name="skipped"><skipped/></testcase>
</testsuite></testsuites>"""


def test_junit_annotations_maps_files_lines_and_escapes():
    lines = xprobe.junit_annotations(JUNIT)
    assert lines == [
        "::error file=tests/test_a.py,line=10,title=tests.test_a%3A%3Atest_bad::assert 1 == 2",
        "::error file=tests/test_b.py,title=tests.test_b.TestX%3A%3Atest_err[a%2Cb]::boom: 100%25",
        "::error title=bare::failure",
    ]


def test_junit_annotations_limits_and_levels():
    lines = xprobe.junit_annotations(JUNIT, max_annotations=1, max_message=6, level="warning")
    assert lines == ["::warning file=tests/test_a.py,line=10,title=tests.test_a%3A%3Atest_bad::assert",
                     "::warning title=junit::2 more failing testcase(s) not annotated"]
    one_part = xprobe.junit_annotations('<testsuite><testcase classname="mod" name="t"><failure message="x"/>'
                                        '</testcase></testsuite>')
    assert one_part == ["::error file=mod.py,title=mod%3A%3At::x"]
    assert xprobe.junit_annotations("<testsuite/>") == []
    func = xprobe.junit_annotations('<testsuite><testcase classname="tests.test_m" name="t"><failure message="x"/>'
                                    '</testcase></testsuite>')
    assert func == ["::error file=tests/test_m.py,title=tests.test_m%3A%3At::x"]


@pytest.mark.parametrize("text, kwargs, error", [
    (b"<x/>", {}, TypeError),
    ("<x/>", {"level": "fatal"}, ValueError),
    ("<x/>", {"max_annotations": 0}, ValueError),
    ('<!DOCTYPE x [<!ENTITY e "y">]><x/>', {}, ValueError),
    ("<x>", {}, ValueError),
])
def test_junit_annotations_rejects(text, kwargs, error):
    with pytest.raises(error):
        xprobe.junit_annotations(text, **kwargs)


SOURCE = '''import json
import tomllib
from distutils import core
import cgi.parse
from wsgiref import types
from . import sibling
try:
    import tomllib as guarded
except ImportError:
    guarded = None
try:
    import imp
except (ValueError, ModuleNotFoundError):
    pass
try:
    import asyncore
except:
    pass
try:
    import zoneinfo
except KeyError:
    pass
if sys.version_info >= (3, 11):
    import tomllib
else:
    import distutils
path.read_text()
path.read_text(encoding="utf-8")
path.write_text("x")
path.write_text("x", "utf-8")
open("f")
open("f", "rb")
open("f", mode="w")
open("f", mode=m)
io.open("f", "r", -1, "utf-8")
subprocess.run(["x"], text=True)
subprocess.run(["x"], text=True, encoding="utf-8")
subprocess.run(["x"], capture_output=True)
other.run(text=True)
Path("f").open()
self.sub.run(text=True)
print("\\u00e9")
'''


def kinds(report):
    return [(f["line"], f["kind"]) for f in report["findings"]]


def test_portability_reports_imports_only_by_default(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "m.py").write_text(SOURCE, encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.py").write_text("import tomllib\n", encoding="utf-8")
    report = xprobe.portability_findings(tmp_path)
    assert report["min_python"] == [3, 10] and report["min_python_source"] == "default"
    assert report["files"] == 1 and not report["truncated"]
    assert kinds(report) == [(2, "too_new"), (3, "removed"), (4, "removed"), (5, "too_new")]
    details = {f["line"]: f["detail"] for f in report["findings"]}
    assert details[2] == "tomllib is stdlib from 3.11; min_python is 3.10"
    assert details[3] == "distutils was removed in 3.12"
    assert details[5] == "wsgiref.types is stdlib from 3.11; min_python is 3.10"


def test_portability_versions_and_locale_hints(tmp_path):
    (tmp_path / "m.py").write_text(SOURCE, encoding="utf-8")
    newer = xprobe.portability_findings(tmp_path, min_python=(3, 11), max_python=(3, 11))
    assert kinds(newer) == []
    hints = xprobe.portability_findings(tmp_path / "m.py", min_python=(3, 12), locale_io=True)
    assert hints["files"] == 1 and {f["path"] for f in hints["findings"]} == {"m.py"}
    locale = {f["line"]: f["detail"] for f in hints["findings"] if f["kind"] == "locale_io"}
    assert locale == {27: "read_text() without encoding=", 29: "write_text() without encoding=",
                      31: "open() in text mode without encoding=", 33: "open() in text mode without encoding=",
                      36: "run(text=True) without encoding="}


def test_portability_bytes_unparsable_pyproject_and_limits(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nrequires-python = ">= 3.11"\n', encoding="utf-8")
    (tmp_path / "a.py").write_text("import tomllib\nX = '\u2501'\n", encoding="utf-8")
    (tmp_path / "b.py").write_bytes(b"\xff\xfe = 1\n")
    (tmp_path / "c.py").write_text("def (:\n", encoding="utf-8")
    report = xprobe.portability_findings(tmp_path, undecodable=True)
    assert report["min_python"] == [3, 11] and report["min_python_source"] == "pyproject.toml"
    assert [(f["path"], f["line"], f["kind"]) for f in report["findings"]] == [
        ("a.py", 2, "undecodable"), ("b.py", 1, "unparsable"), ("c.py", 1, "unparsable")]
    assert report["findings"][0]["detail"] == "byte 0x81 is not cp1252"
    assert report["findings"][1]["detail"] == "UnicodeDecodeError"
    capped = xprobe.portability_findings(tmp_path, max_files=1)
    assert capped["files"] == 1 and capped["truncated"]
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    assert xprobe.portability_findings(tmp_path)["min_python_source"] == "default"
    for bad in ({"min_python": "3.10"}, {"max_python": (3,)}, {"min_python": (3, 1.0)}):
        with pytest.raises(ValueError):
            xprobe.portability_findings(tmp_path, **bad)


def test_cli_annotate_junit(tmp_path, capsys):
    report = tmp_path / "junit.xml"
    report.write_text(JUNIT, encoding="utf-8")
    assert xprobe.main(["--annotate-junit", str(report)]) == 0
    assert capsys.readouterr().out.splitlines()[0].startswith("::error file=tests/test_a.py,line=10,")


def test_cli_portability_exit_codes(tmp_path, capsys):
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir(), two.mkdir()
    (one / "m.py").write_text("import tomllib\n", encoding="utf-8")
    (two / "m.py").write_text("open('f')\n", encoding="utf-8")
    assert xprobe.main(["--portability", "--root", str(two)]) == 0
    assert capsys.readouterr().out == "portability: 0 finding(s) in 1 file(s); min python 3.10 (default)\n"
    assert xprobe.main(["--portability", "--root", str(two), "--windows-locale"]) == 0
    assert capsys.readouterr().out.startswith("m.py:1: locale_io: open() in text mode")
    assert xprobe.main(["--portability", "--root", str(one), "--root", str(two), "--min-python", "3.10"]) == 1
    out = capsys.readouterr().out.splitlines()
    assert out[0] == f"{one}/m.py:1: too_new: tomllib is stdlib from 3.11; min_python is 3.10"
    assert xprobe.main(["--portability", "--root", str(one), "--min-python", "3.11"]) == 0
    capsys.readouterr()


def test_cli_search_across_roots(tmp_path, capsys):
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir(), two.mkdir()
    (one / "a.txt").write_text("needle here\n", encoding="utf-8")
    (two / "b.txt").write_text("needle there\n", encoding="utf-8")
    assert xprobe.main(["--search", "needle", "--root", str(one), "--root", str(two) + "/"]) == 0
    paths = [m["path"] for m in json.loads(capsys.readouterr().out)["matches"]]
    assert paths == [f"{one}/a.txt", f"{two}/b.txt"]
    assert xprobe.main(["--search", "needle", "--root", str(one)]) == 0
    assert [m["path"] for m in json.loads(capsys.readouterr().out)["matches"]] == ["a.txt"]
    assert xprobe.main(["--search", "needle", "--max-matches", "1", "--root", str(one), "--root", str(two)]) == 2
    capped = json.loads(capsys.readouterr().out)
    assert [m["path"] for m in capped["matches"]] == [f"{one}/a.txt"] and capped["truncated"]
