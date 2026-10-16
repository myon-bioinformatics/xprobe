"""load_toml / load_yaml: tomllib or Node (smol-toml / js-yaml), mirrored against tomllib and PyYAML."""
import datetime
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import xprobe

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "tests" / "js" / "node_modules"
node_ready = pytest.mark.skipif(shutil.which("node") is None or not JS.is_dir(),
                                reason="run `npm ci --prefix tests/js` (CI does) to enable the Node readers")

TOML = """title = "x"
[owner]
dob = 1979-05-27T07:32:00-08:00
local = 1979-05-27T07:32:00
day = 1979-05-27
t = 07:32:00
arr = [1, 2.5, true, "s"]
[[items]]
name = "a"
"""


@pytest.fixture(autouse=True)
def _node_path(monkeypatch):
    monkeypatch.setenv("NODE_PATH", str(JS))


@node_ready
def test_toml_via_node_matches_tomllib_shape():
    value = xprobe.load_toml(TOML, node=shutil.which("node"))
    assert value["owner"]["dob"] == datetime.datetime(1979, 5, 27, 15, 32, tzinfo=datetime.timezone.utc)
    assert value["owner"]["local"] == datetime.datetime(1979, 5, 27, 7, 32)
    assert value["owner"]["day"] == datetime.date(1979, 5, 27)
    assert value["owner"]["t"] == datetime.time(7, 32)
    assert value["owner"]["arr"] == [1, 2.5, True, "s"] and value["items"] == [{"name": "a"}]
    if sys.version_info >= (3, 11):
        import tomllib
        assert value == tomllib.loads(TOML) == xprobe.load_toml(TOML)


@node_ready
def test_yaml_failsafe_matches_pyyaml_baseloader_on_real_workflows():
    yaml = pytest.importorskip("yaml")
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        assert xprobe.load_yaml(text) == yaml.load(text, Loader=yaml.BaseLoader), path.name
    assert xprobe.load_yaml("on: push\nn: 1\n") == {"on": "push", "n": "1"}


@node_ready
def test_yaml_core_types_by_yaml_1_2():
    assert xprobe.load_yaml("a: yes\nb: 1\nc: 2026-10-16\nd: ~\ne: [1.5, true]\n", schema="core") == {
        "a": "yes", "b": 1, "c": "2026-10-16", "d": None, "e": [1.5, True]}
    assert xprobe.load_yaml("", schema="core") is None


@node_ready
def test_parse_errors_are_value_errors():
    with pytest.raises(ValueError, match="invalid YAML"):
        xprobe.load_yaml("a: [")
    with pytest.raises(ValueError, match="invalid TOML"):
        xprobe.load_toml("a = ", node=shutil.which("node"))


def test_backend_errors_name_the_missing_piece(tmp_path, monkeypatch):
    real = shutil.which("node")
    with pytest.raises(ValueError, match="schema"):
        xprobe.load_yaml("a: 1", schema="full")
    with pytest.raises(TypeError):
        xprobe.load_yaml(b"a: 1", node="node")
    if real:
        monkeypatch.setenv("NODE_PATH", str(tmp_path))  # no packages here
        with pytest.raises(RuntimeError, match="npm i --no-save js-yaml"):
            xprobe.load_yaml("a: 1", node=real)
    monkeypatch.setattr(shutil, "which", lambda name, **kw: None)
    with pytest.raises(RuntimeError, match="node not found"):
        xprobe.load_yaml("a: 1")


def test_tomllib_errors_are_value_errors():
    if sys.version_info < (3, 11):
        pytest.skip("tomllib is 3.11+")
    with pytest.raises(ValueError, match="invalid TOML"):
        xprobe.load_toml("a = ")


@node_ready
def test_cli_load(tmp_path, capsys):
    (tmp_path / "w.yml").write_text("on: push\n")
    (tmp_path / "p.toml").write_text('[tool]\nname = "x"\n')
    assert xprobe.main(["--load", "yaml", str(tmp_path / "w.yml")]) == 0
    assert '"on": "push"' in capsys.readouterr().out
    assert xprobe.main(["--load", "toml", str(tmp_path / "p.toml")]) == 0
    assert '"name": "x"' in capsys.readouterr().out
    assert xprobe.main(["--load", "yaml-core", str(tmp_path / "w.yml")]) == 0
    assert xprobe.main(["--load", "yaml", str(tmp_path / "missing.yml")]) == 2
    with pytest.raises(SystemExit):
        xprobe.main(["--load", "ini", str(tmp_path / "w.yml")])
