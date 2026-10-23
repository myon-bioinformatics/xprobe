"""xprobe.py is the canonical artifact: one copied file, no helper module."""
import errno
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import xprobe

ROOT = Path(__file__).resolve().parents[1]


def _force_fallback(monkeypatch):
    monkeypatch.setattr(xprobe, "_NODE_LAUNCH", None)
    monkeypatch.setattr(
        xprobe,
        "_sibling_node_launch_path",
        lambda: Path("/absent/vendor/node_launch.py"),
    )
    launcher = xprobe._node_launch_module()
    launcher.clear_probe_cache()
    return launcher


def _patch_probe(launcher, monkeypatch, *, stdout=b"v24.0.0\n", returncode=0, error=None):
    calls = []

    def fake_run(args, *extra, **kwargs):
        argv = list(args)
        calls.append(argv)
        if error is not None:
            raise error
        return subprocess.CompletedProcess(argv, returncode, stdout, b"")

    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    return calls


class _MemoryProc:
    def __init__(self, command, *, stdout=b"", stderr=b"", returncode=0, stdin=False, wait=None, kill=None):
        self.args = [str(part) for part in command]
        self.stdin = io.BytesIO() if stdin is False else stdin
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = returncode
        self._wait = wait
        self._kill = kill

    def wait(self, timeout=None):
        if self._wait is not None:
            return self._wait(self, timeout)
        return self.returncode

    def kill(self):
        if self._kill is not None:
            self._kill(self)
            return
        self.returncode = -9


def _patch_popen(launcher, monkeypatch, factory):
    monkeypatch.setattr(launcher.subprocess, "Popen", factory)


def test_copied_xprobe_runs_without_helper(tmp_path):
    script_dir = tmp_path / "vendor-copy"
    script_dir.mkdir()
    (script_dir / "xprobe.py").write_bytes((ROOT / "xprobe.py").read_bytes())
    (script_dir / "note.txt").write_text("TODO keep\n", encoding="utf-8")
    (script_dir / "w.yml").write_text("on: push\n", encoding="utf-8")
    assert not (script_dir / "vendor").exists()
    assert not (script_dir / "node_launch.py").exists()

    def run(*args):
        return subprocess.run(
            [sys.executable, "-S", "xprobe.py", *args],
            cwd=script_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )

    help_done = run("--help")
    assert help_done.returncode == 0, help_done.stderr
    assert "--search" in help_done.stdout
    assert "node_launch" not in help_done.stderr

    search = run("--search", "TODO", "--root", "note.txt")
    assert search.returncode == 0, search.stderr
    report = json.loads(search.stdout)
    assert report["matches"][0]["match"] == "TODO"
    assert report["errors"] == []

    loaded = run("--load", "yaml", "w.yml")
    if loaded.returncode == 0:
        assert json.loads(loaded.stdout) == {"on": "push"}
    else:
        assert loaded.returncode == 2, loaded.stderr
        assert "Node 24+" in loaded.stderr
        assert "Traceback" not in loaded.stderr
        assert "node_launch.py" not in loaded.stderr


def test_checkout_prefers_sibling_launcher(monkeypatch):
    monkeypatch.setattr(xprobe, "_NODE_LAUNCH", None)
    module = xprobe._node_launch_module()
    assert str(getattr(module, "__file__", "")).replace("\\", "/").endswith("vendor/node_launch.py")


def test_tomllib_load_ignores_missing_sibling(monkeypatch):
    if sys.version_info < (3, 11):
        pytest.skip("tomllib is 3.11+")
    _force_fallback(monkeypatch)
    monkeypatch.setattr(shutil, "which", lambda *_args, **_kwargs: None)
    assert xprobe.load_toml('title = "x"\n') == {"title": "x"}


def test_fallback_missing_node_and_cli_message(monkeypatch, tmp_path, capsys):
    _force_fallback(monkeypatch)
    monkeypatch.setattr(shutil, "which", lambda *_args, **_kwargs: None)
    with pytest.raises(RuntimeError, match=r"Node 24\+.*node not found"):
        xprobe.load_yaml("a: 1\n")
    target = tmp_path / "w.yml"
    target.write_text("a: 1\n", encoding="utf-8")
    assert xprobe.main(["--load", "yaml", str(target)]) == 2
    err = capsys.readouterr().err
    assert "Node 24+" in err
    assert "node not found" in err
    assert "Traceback" not in err


def test_fallback_rejects_old_explicit_node_and_missing_path(monkeypatch, tmp_path):
    launcher = _force_fallback(monkeypatch)
    old = tmp_path / "node20"
    _patch_probe(launcher, monkeypatch, stdout=b"v20.19.0\n")
    with pytest.raises(RuntimeError, match=r"Node 24\+.*found Node 20"):
        xprobe.load_yaml("a: 1\n", node=str(old))

    launcher.clear_probe_cache()
    missing = tmp_path / "missing-node"
    _patch_probe(
        launcher,
        monkeypatch,
        error=FileNotFoundError(errno.ENOENT, "No such file", str(missing)),
    )
    with pytest.raises(FileNotFoundError) as info:
        xprobe.load_yaml("a: 1\n", node=str(missing))
    assert info.value.errno == errno.ENOENT
    assert info.value.filename == str(missing)

    launcher.clear_probe_cache()
    _patch_probe(launcher, monkeypatch, returncode=1, stdout=b"")
    with pytest.raises(RuntimeError, match="node not found"):
        xprobe.load_yaml("a: 1\n", node=str(tmp_path / "bad-probe"))

    launcher.clear_probe_cache()
    _patch_probe(launcher, monkeypatch, returncode=0, stdout=b"not-a-version\n")
    with pytest.raises(RuntimeError, match="node not found"):
        xprobe.load_yaml("a: 1\n", node=str(tmp_path / "garbage-version"))

    launcher.clear_probe_cache()
    _patch_probe(launcher, monkeypatch, error=subprocess.TimeoutExpired("node", 5))
    with pytest.raises(RuntimeError, match="node not found"):
        xprobe.load_yaml("a: 1\n", node=str(tmp_path / "slow-probe"))

    launcher.clear_probe_cache()
    _patch_probe(launcher, monkeypatch, error=OSError("probe failed"))
    with pytest.raises(RuntimeError, match="node not found"):
        xprobe.load_yaml("a: 1\n", node=str(tmp_path / "os-error"))


def test_fallback_rejects_batch_wrappers(monkeypatch):
    launcher = _force_fallback(monkeypatch)
    for name in ("node.cmd", "node.bat", "NODE.CMD"):
        with pytest.raises(RuntimeError, match="node not found"):
            xprobe.load_yaml("a: 1\n", node=name)
    monkeypatch.setattr(shutil, "which", lambda *_args, **_kwargs: "C:/Program Files/nodejs/node.cmd")
    with pytest.raises(RuntimeError, match="node not found"):
        xprobe.load_yaml("a: 1\n")
    assert launcher.resolve_node(node="plain-node", probe=False) == "plain-node"


def test_fallback_parses_and_reports_reader_errors(monkeypatch, tmp_path):
    launcher = _force_fallback(monkeypatch)
    node = tmp_path / "node24"
    calls = _patch_probe(launcher, monkeypatch)
    holder = {"stdout": b'{"a": "1"}', "stderr": b"", "code": 0}

    def popen(command, **_kwargs):
        return _MemoryProc(command, stdout=holder["stdout"], stderr=holder["stderr"], returncode=holder["code"])

    _patch_popen(launcher, monkeypatch, popen)
    assert xprobe.load_yaml("a: 1\n", node=str(node)) == {"a": "1"}
    assert calls and calls[0][1] == "--version"
    assert xprobe.load_yaml("a: 1\n", node=str(node)) == {"a": "1"}
    assert len(calls) == 1  # successful probes are cached

    holder.update(stdout=b"", stderr=b"missing:Cannot find module 'js-yaml'\n", code=3)
    with pytest.raises(RuntimeError, match="npm i --no-save js-yaml"):
        xprobe.load_yaml("a: 1\n", node=str(node))

    holder.update(stderr=b"parse:bad token\n", code=3)
    with pytest.raises(ValueError, match="invalid YAML: bad token"):
        xprobe.load_yaml("a: 1\n", node=str(node))


def test_fallback_timeout_maps_to_timeout_expired(monkeypatch, tmp_path):
    launcher = _force_fallback(monkeypatch)
    node = tmp_path / "node24"
    _patch_probe(launcher, monkeypatch)

    def popen(command, **_kwargs):
        def wait(proc, timeout):
            raise subprocess.TimeoutExpired(proc.args, timeout or 1)

        def kill(proc):
            proc.returncode = -9

        return _MemoryProc(command, wait=wait, kill=kill, returncode=None)

    _patch_popen(launcher, monkeypatch, popen)
    with pytest.raises(subprocess.TimeoutExpired) as info:
        xprobe.load_yaml("a: 1\n", node=str(node), timeout=3)
    assert info.value.timeout == 3
    assert info.value.cmd[0] == str(node)
    assert info.value.cmd[1] == "-e"


def test_fallback_timeout_survives_stuck_kill(monkeypatch, tmp_path):
    launcher = _force_fallback(monkeypatch)
    node = tmp_path / "node24"
    _patch_probe(launcher, monkeypatch)

    def popen(command, **_kwargs):
        def wait(proc, timeout):
            raise subprocess.TimeoutExpired(proc.args, timeout or 1)

        def kill(proc):
            raise OSError("kill failed")

        return _MemoryProc(command, wait=wait, kill=kill, returncode=None)

    _patch_popen(launcher, monkeypatch, popen)
    with pytest.raises(subprocess.TimeoutExpired):
        xprobe._node_load("yaml-failsafe", "a: 1\n", str(node), 2)


def test_fallback_stdin_closed_keeps_child_result(monkeypatch, tmp_path):
    launcher = _force_fallback(monkeypatch)
    node = tmp_path / "node24"
    _patch_probe(launcher, monkeypatch)

    class _Broken:
        def write(self, _data):
            raise BrokenPipeError()

        def flush(self):
            return None

        def close(self):
            raise OSError(errno.EIO, "close")

    class _Epipe:
        def write(self, _data):
            raise OSError(errno.EPIPE, "pipe")

        def flush(self):
            return None

        def close(self):
            return None

    class _Other:
        def write(self, _data):
            raise OSError(errno.EINVAL, "bad stdin")

        def flush(self):
            return None

        def close(self):
            raise OSError(errno.EIO, "close")

    scripts = {"mode": "broken", "code": 0, "stdout": b'{"ok": true}', "stderr": b""}

    def popen(command, **_kwargs):
        mode = scripts["mode"]
        stdin = {"broken": _Broken(), "epipe": _Epipe(), "other": _Other(), "none": None}[mode]
        return _MemoryProc(
            command,
            stdin=stdin,
            stdout=scripts["stdout"],
            stderr=scripts["stderr"],
            returncode=scripts["code"],
        )

    _patch_popen(launcher, monkeypatch, popen)
    assert xprobe.load_yaml("a: 1\n", node=str(node)) == {"ok": True}

    scripts["mode"] = "epipe"
    scripts.update(code=3, stdout=b"", stderr=b"parse:early\n")
    with pytest.raises(ValueError, match="invalid YAML: early"):
        xprobe.load_yaml("a: 1\n", node=str(node))

    scripts["mode"] = "other"
    with pytest.raises(launcher.LaunchError, match="bad stdin"):
        xprobe.load_yaml("a: 1\n", node=str(node))

    scripts["mode"] = "none"
    scripts.update(code=0, stdout=b'{"n": 1}', stderr=b"")
    assert xprobe.load_yaml("a: 1\n", node=str(node)) == {"n": 1}


def test_fallback_node_env_does_not_override_path(monkeypatch, tmp_path):
    launcher = _force_fallback(monkeypatch)
    node = tmp_path / "from-path"
    monkeypatch.setenv("NODE", str(tmp_path / "from-env"))
    monkeypatch.setattr(shutil, "which", lambda name, **_kwargs: str(node) if name == "node" else None)
    _patch_probe(launcher, monkeypatch)

    def popen(command, **_kwargs):
        assert command[0] == str(node)
        return _MemoryProc(command, stdout=b'{"via": "path"}')

    _patch_popen(launcher, monkeypatch, popen)
    assert xprobe.load_yaml("a: 1\n") == {"via": "path"}

    chosen = launcher.resolve_node(env_var="NODE", probe=False)
    assert chosen == str(tmp_path / "from-env")


def test_fallback_run_accepts_bytes_and_check(monkeypatch, tmp_path):
    launcher = _force_fallback(monkeypatch)
    node = tmp_path / "node24"
    _patch_probe(launcher, monkeypatch)
    seen = {}

    class _Capture:
        def __init__(self):
            self.chunks = []

        def write(self, data):
            self.chunks.append(bytes(data))
            return len(data)

        def flush(self):
            return None

        def close(self):
            return None

    def popen(command, **_kwargs):
        proc = _MemoryProc(command, stdin=_Capture(), returncode=0, stdout=b"ok")
        seen["proc"] = proc
        return proc

    _patch_popen(launcher, monkeypatch, popen)
    payload = b"x" * 70000
    done = launcher.run("-e", "script", node=str(node), probe=True, input=payload, check=False, timeout=5)
    assert done.returncode == 0
    assert b"".join(seen["proc"].stdin.chunks) == payload

    def popen_fail(command, **_kwargs):
        return _MemoryProc(command, returncode=3, stdout=b"", stderr=b"")

    _patch_popen(launcher, monkeypatch, popen_fail)
    with pytest.raises(launcher.LaunchError, match="Node script failed"):
        launcher.run("-e", "script", node=str(node), probe=False, input=None, check=True)

    def popen_text(command, **_kwargs):
        return _MemoryProc(command, returncode=4, stderr=b"parse:nope\n")

    _patch_popen(launcher, monkeypatch, popen_text)
    with pytest.raises(launcher.LaunchError, match="parse:nope"):
        launcher.run("-e", "script", node=str(node), probe=False, input="text", check=True)

    def popen_no_status(command, **_kwargs):
        def wait(_proc, _timeout):
            return None

        return _MemoryProc(command, returncode=0, stdout=b"{}", wait=wait)

    _patch_popen(launcher, monkeypatch, popen_no_status)
    quiet = launcher.run("-e", "script", node=str(node), probe=False, input="", check=False)
    assert quiet.returncode == -1


def test_fallback_popen_oserror(monkeypatch, tmp_path):
    launcher = _force_fallback(monkeypatch)
    node = tmp_path / "node24"
    _patch_probe(launcher, monkeypatch)

    def popen(_command, **_kwargs):
        raise OSError("spawn failed")

    _patch_popen(launcher, monkeypatch, popen)
    with pytest.raises(launcher.LaunchError, match="spawn failed"):
        xprobe.load_yaml("a: 1\n", node=str(node))
