"""Conventions injected by callers, for production code and arbitrary files."""
import json
from pathlib import Path

import pytest

import xprobe


def test_production_conventions_are_ored_once_and_kinds_intersect():
    source = '''class ReaderAdapter:
    def read_json(self): pass
    async def fetch_records(self): pass
def load_pack(): pass
def validate_input(): pass
def unrelated(): pass
'''
    rows = xprobe.python_symbols(source, pattern=("read_*", "*Adapter.*", "load_*", "validate_*"),
                                  kinds=("function",))
    assert [r["qualname"] for r in rows] == ["ReaderAdapter.read_json", "load_pack", "validate_input"]
    assert len({r["qualname"] for r in rows}) == len(rows)
    assert xprobe.python_symbols(source, pattern=()) == []


def test_file_conventions_are_not_python_or_tests_only(tmp_path):
    for name in ("a.yml", "b.toml", "c.py", "d.txt", ".env.local"):
        (tmp_path / name).write_text("configuration", encoding="utf-8")
    nested = tmp_path / "production"
    nested.mkdir()
    (nested / "settings.json").write_text("{}", encoding="utf-8")
    hidden = tmp_path / ".github"
    hidden.mkdir()
    (hidden / "ci.yml").write_text("{}", encoding="utf-8")
    report = xprobe.discover_files(tmp_path, include=("*.yml", "production/*.json", ".env*"))
    assert report["files"] == ["a.yml", "production/settings.json"]
    hidden_report = xprobe.discover_files(tmp_path, include=("*.yml", ".env*"), include_hidden=True)
    assert hidden_report["files"] == [".env.local", "a.yml", ".github/ci.yml"]
    assert xprobe.discover_files(tmp_path, include=())['files'] == []


def test_directory_filters_and_global_limits(tmp_path):
    for name in ("a.py", "b.py", "a.PY"):
        (tmp_path / name).write_text("def load_data(): pass\ndef save_data(): pass\n", encoding="utf-8")
    for directory in ("node_modules", "generated", "pkg/skip", "pkg/keep"):
        folder = tmp_path / directory
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "source.py").write_text("def load_extra(): pass\n", encoding="utf-8")
    excluded = ("node_modules", "generated", "pkg/skip")
    report = xprobe.discover_python(tmp_path, patterns=("load_*",), exclude_dirs=excluded)
    assert [(r["path"], r["name"]) for r in report["symbols"]] == [
        ("a.py", "load_data"), ("b.py", "load_data"), ("pkg/keep/source.py", "load_extra")]
    assert report["scanned"] == 3 and not report["truncated"]
    assert not xprobe.discover_python(tmp_path, exclude_dirs=excluded, max_symbols=6)["truncated"]
    assert xprobe.discover_python(tmp_path, exclude_dirs=excluded, max_symbols=2)["truncated"]
    assert not xprobe.discover_files(tmp_path, include=("*.py",), exclude_dirs=excluded, max_files=3)["truncated"]
    assert xprobe.discover_files(tmp_path, include=("*.py",), exclude_dirs=excluded, max_files=2)["truncated"]


def test_per_file_errors_and_size_skips_survive(tmp_path):
    (tmp_path / "bad.py").write_text("def secret(\n", encoding="utf-8")
    (tmp_path / "big.py").write_bytes(b"#" * 100)
    (tmp_path / "good.py").write_text("def load_a(): pass\n", encoding="utf-8")
    report = xprobe.discover_python(tmp_path, max_bytes=50)
    assert report["errors"] == [{"path": "bad.py", "reason": "SyntaxError"}]
    assert report["skipped"] == [{"path": "big.py", "reason": "too_large"}]
    assert report["scanned"] == 1 and report["symbols"][0]["name"] == "load_a"
    assert "secret" not in json.dumps(report)


def test_single_file_root_and_parse_encoding(tmp_path):
    path = tmp_path / "source.py"
    path.write_bytes(b"# coding: latin-1\n# caf\xe9\ndef read_a(): pass\n")
    assert xprobe.discover_files(path)["files"] == ["source.py"]
    report = xprobe.discover_python(path, patterns=("read_*",))
    assert report["symbols"] == [{"path": "source.py", "name": "read_a", "qualname": "read_a",
                                   "kind": "function", "line": 3}]


def test_permission_errors_and_walk_errors_are_visible(tmp_path, monkeypatch):
    path = tmp_path / "source.py"
    path.write_text("def read_a(): pass\n", encoding="utf-8")
    original = Path.open
    def denied(self, *args, **kwargs):
        if self == path:
            raise PermissionError("secret")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "open", denied)
    report = xprobe.discover_python(tmp_path)
    assert report["errors"] == [{"path": "source.py", "reason": "PermissionError"}]
    def bad_walk(root, **kwargs):
        kwargs["onerror"](PermissionError(13, "secret", str(root / "blocked")))
        return iter(())
    monkeypatch.setattr(xprobe.os, "walk", bad_walk)
    report = xprobe.discover_files(tmp_path)
    assert report["errors"] == [{"path": str(tmp_path / "blocked"), "reason": "PermissionError"}]


def test_symlinks_do_not_supply_candidates(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("def read_a(): pass\n", encoding="utf-8")
    link = tmp_path / "link.py"
    try:
        link.symlink_to(source)
        (tmp_path / "loop").symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    report = xprobe.discover_python(tmp_path)
    assert len(report["symbols"]) == 1
    assert report["skipped"] == [{"path": "link.py", "reason": "non_regular"}]
    with pytest.raises(ValueError):
        xprobe.discover_files(link)


@pytest.mark.parametrize("kwargs,error", [
    ({"patterns": "load_*"}, TypeError), ({"patterns": [1]}, ValueError),
    ({"kinds": ("unknown",)}, ValueError), ({"kinds": "class"}, TypeError),
    ({"include": "*.py"}, TypeError), ({"max_files": 0}, ValueError),
    ({"max_bytes": True}, ValueError), ({"max_symbols": -1}, ValueError),
])
def test_validate_even_on_empty_roots(tmp_path, kwargs, error):
    with pytest.raises(error):
        xprobe.discover_python(tmp_path, **kwargs)


def test_cli_directory_and_multiple_conventions(tmp_path, capsys):
    (tmp_path / "tool.py").write_text("class Adapter: pass\ndef read_a(): pass\ndef write_b(): pass\n", encoding="utf-8")
    args = ["--symbols", str(tmp_path), "--symbol-pattern", "read_*", "--symbol-pattern", "write_*",
            "--symbol-kind", "function"]
    assert xprobe.main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert [r["name"] for r in report["symbols"]] == ["read_a", "write_b"]
    assert xprobe.main(args + ["--brief", "--max-matches", "1"]) == 2
    output = capsys.readouterr()
    assert "tool.py:2: function read_a" in output.out and "truncated" in output.err
    assert xprobe.main(["--symbols", str(tmp_path), "--symbol-pattern", "missing"]) == 1
    assert json.loads(capsys.readouterr().out)["symbols"] == []


def test_cli_arbitrary_files_and_empty_or_incomplete_roots(tmp_path, capsys):
    (tmp_path / "app.yml").write_text("{}", encoding="utf-8")
    (tmp_path / "bad.py").write_text("def bad(\n", encoding="utf-8")
    assert xprobe.main(["--discover", "--root", str(tmp_path), "--include", "*.yml", "--brief"]) == 0
    assert capsys.readouterr().out == "app.yml\n"
    assert xprobe.main(["--discover", "--root", str(tmp_path), "--max-files", "1"]) == 2
    assert json.loads(capsys.readouterr().out)["truncated"]
    assert xprobe.main(["--symbols", str(tmp_path), "--brief"]) == 2
    assert "SyntaxError" in capsys.readouterr().err
    assert xprobe.main(["--discover", "--root", str(tmp_path), "--include", "*.txt"]) == 1
    assert not json.loads(capsys.readouterr().out)["files"]
    assert xprobe.main(["--discover", "--root", str(tmp_path), "--root", str(tmp_path)]) == 2
    assert capsys.readouterr().err == "ValueError\n"
