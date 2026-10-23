"""Parity between legacy subprocess Node loading and vendored node_launch."""
from __future__ import annotations

import ast
import errno
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import NamedTuple, Union

import pytest

import xprobe
import test_load_config as _load_config_mod

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "tests" / "js" / "node_modules"
_STDIN_CLOSED_PAYLOAD = "a = " + repr("x" * 70000) + "\n"
_LARGE_INPUT = "k: v\n" + ("#" * (4 * 1024 * 1024 - 5))


class _FakeNodeSpec(NamedTuple):
    version: str
    on_eval: str
    close_stdin_unread: bool = False
    stdin_close_exit_code: int = 3
    stdin_close_stdout: bytes = b""


_FAKE_NODE_SPECS: dict[str, _FakeNodeSpec] = {}


def _fake_node_key(path: Union[Path, str]) -> str:
    return str(Path(path).resolve())


class _StdinClosesEarly:
    def __init__(self, pipe_byte_limit: int = 4096) -> None:
        self._limit = pipe_byte_limit
        self._written = 0

    def write(self, data: bytes) -> int:
        if self._written >= self._limit:
            raise BrokenPipeError()
        remaining = self._limit - self._written
        if len(data) > remaining:
            self._written = self._limit
            raise BrokenPipeError()
        self._written += len(data)
        return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


def _run_fake_on_eval(on_eval: str) -> tuple[bytes, bytes, int]:
    from io import StringIO

    stdout = StringIO()
    stderr = StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    code = 0
    try:
        sys.stdout = stdout
        sys.stderr = stderr
        exec(on_eval, {"sys": sys})  # noqa: S102
    except SystemExit as exc:
        if exc.code is None:
            code = 0
        elif isinstance(exc.code, int):
            code = exc.code
        else:
            code = 1
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
    return (
        stdout.getvalue().encode("utf-8", errors="replace"),
        stderr.getvalue().encode("utf-8", errors="replace"),
        code,
    )


class _FakeNodePopen:
    def __init__(
        self,
        command: list[str],
        on_eval: str,
        *,
        close_stdin_unread: bool = False,
        stdin_close_exit_code: int = 3,
        stdin_close_stdout: bytes = b"",
        **_kwargs: object,
    ) -> None:
        self.args = command
        self._on_eval = on_eval
        self._close_stdin_unread = close_stdin_unread
        self._stdin_close_exit_code = stdin_close_exit_code
        self._stdin_close_stdout = stdin_close_stdout
        stdout_r, stdout_w = os.pipe()
        stderr_r, stderr_w = os.pipe()
        if close_stdin_unread:
            self.stdin = _StdinClosesEarly()
            self._stdin_r = None
        else:
            stdin_r, stdin_w = os.pipe()
            self.stdin = os.fdopen(stdin_w, "wb")
            self._stdin_r = stdin_r
        self.stdout = os.fdopen(stdout_r, "rb")
        self.stderr = os.fdopen(stderr_r, "rb")
        self._stdout_w = stdout_w
        self._stderr_w = stderr_w
        self.returncode: int | None = None
        self._done = threading.Event()

        def worker() -> None:
            if self._close_stdin_unread:
                try:
                    if self._stdin_close_stdout:
                        os.write(self._stdout_w, self._stdin_close_stdout)
                    if self._stdin_close_exit_code != 0:
                        os.write(self._stderr_w, b"boom\n")
                finally:
                    os.close(self._stdout_w)
                    os.close(self._stderr_w)
                    self.returncode = self._stdin_close_exit_code
                    self._done.set()
                return

            def drain_stdin() -> None:
                try:
                    with os.fdopen(self._stdin_r, "rb") as stream:
                        while stream.read(65536):
                            pass
                except OSError:
                    pass

            threading.Thread(target=drain_stdin, daemon=True).start()
            stdout, stderr, rc = _run_fake_on_eval(self._on_eval)
            try:
                if stdout:
                    os.write(self._stdout_w, stdout)
                if stderr:
                    os.write(self._stderr_w, stderr)
            finally:
                os.close(self._stdout_w)
                os.close(self._stderr_w)
                self.returncode = rc
                self._done.set()

        threading.Thread(target=worker, daemon=True).start()

    def wait(self, timeout: float | None = None) -> int:
        if not self._done.wait(timeout):
            raise subprocess.TimeoutExpired(self.args, timeout)
        return self.returncode if self.returncode is not None else -1

    def kill(self) -> None:
        self.returncode = -9
        self._done.set()


@pytest.fixture(autouse=True)
def _node_launch_process_layer_stub(monkeypatch):
    node_launch = xprobe._node_launch_module()
    real_run = node_launch.subprocess.run
    real_popen = node_launch.subprocess.Popen

    def _complete_fake_run(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
        spec = _FAKE_NODE_SPECS[_fake_node_key(argv[0])]
        proc = _FakeNodePopen(argv, spec.on_eval, close_stdin_unread=spec.close_stdin_unread)
        input_data = kwargs.get("input")
        if input_data is not None:
            payload = input_data.encode("utf-8") if isinstance(input_data, str) else input_data
            if proc.stdin is not None and hasattr(proc.stdin, "write"):
                try:
                    proc.stdin.write(payload)
                    proc.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
        timeout = kwargs.get("timeout")
        try:
            rc = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise
        stdout = proc.stdout.read() if proc.stdout else b""
        stderr = proc.stderr.read() if proc.stderr else b""
        text = kwargs.get("text", False)
        if text:
            stdout = stdout.decode("utf-8", errors="replace")
            stderr = stderr.decode("utf-8", errors="replace")
        return subprocess.CompletedProcess(tuple(argv), rc, stdout, stderr)

    def fake_run(args, *pargs, **kwargs):
        if args and not isinstance(args, (str, bytes)):
            argv = list(args)
        else:
            argv = [args, *pargs]
        spec = _FAKE_NODE_SPECS.get(_fake_node_key(argv[0])) if argv else None
        if spec is not None and len(argv) >= 2 and argv[1] == "--version":
            return subprocess.CompletedProcess(
                tuple(argv), 0, (spec.version + "\n").encode(), b""
            )
        if spec is not None and len(argv) >= 2 and argv[1] == "-e":
            return _complete_fake_run(argv, **kwargs)
        return real_run(args, *pargs, **kwargs)

    def fake_popen(command, **kwargs):
        argv = [os.fspath(part) for part in command]
        spec = _FAKE_NODE_SPECS.get(_fake_node_key(argv[0])) if argv else None
        if spec is None:
            return real_popen(command, **kwargs)
        return _FakeNodePopen(
            argv,
            spec.on_eval,
            close_stdin_unread=spec.close_stdin_unread,
            stdin_close_exit_code=spec.stdin_close_exit_code,
            stdin_close_stdout=spec.stdin_close_stdout,
            **kwargs,
        )

    monkeypatch.setattr(node_launch.subprocess, "run", fake_run)
    monkeypatch.setattr(node_launch.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    yield
    _FAKE_NODE_SPECS.clear()


def _write_fake_node(
    tmp_path: Path,
    *,
    version: str,
    on_eval: str = "pass",
    close_stdin_unread: bool = False,
    stdin_close_exit_code: int = 3,
    stdin_close_stdout: bytes = b"",
) -> Path:
    name = "fake_node.exe" if os.name == "nt" else "fake_node"
    dest = tmp_path / name
    dest.write_bytes(b"")
    _FAKE_NODE_SPECS[_fake_node_key(dest)] = _FakeNodeSpec(
        version,
        on_eval,
        close_stdin_unread=close_stdin_unread,
        stdin_close_exit_code=stdin_close_exit_code,
        stdin_close_stdout=stdin_close_stdout,
    )
    return dest


def _legacy_node_load(kind: str, text: str, node: str | None, timeout: float):
    """Pre-node_launch subprocess.run loader (reference for parity tests)."""
    import shutil

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    executable = node or shutil.which("node")
    package = "smol-toml" if kind == "toml" else "js-yaml"
    if executable is None:
        raise RuntimeError(f"needs Node with {package} (npm i --no-save {package}); node not found")
    done = subprocess.run(
        [executable, "-e", xprobe._NODE_LOADER, kind],
        input=text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )
    if done.returncode:
        reason = done.stderr.strip()
        if reason.startswith("missing:"):
            raise RuntimeError(
                f"needs Node with {package} (npm i --no-save {package}): {reason[8:][:200]}"
            )
        raise ValueError(
            f"invalid {kind.split('-')[0].upper()}: {reason.removeprefix('parse:')[:300]}"
        )
    return json.loads(done.stdout)


def _assert_same_outcome(old_call, new_call):
    try:
        old_value = old_call()
    except BaseException as old_exc:
        try:
            new_call()
        except BaseException as new_exc:
            assert type(old_exc) is type(new_exc), (old_exc, new_exc)
            assert str(old_exc) == str(new_exc), (old_exc, new_exc)
            if isinstance(old_exc, subprocess.TimeoutExpired):
                assert old_exc.timeout == new_exc.timeout
                assert old_exc.cmd == new_exc.cmd
            return
        raise AssertionError(f"legacy raised {old_exc!r}, new succeeded")
    new_value = new_call()
    assert old_value == new_value


def test_normal_load_matches_legacy(tmp_path, monkeypatch):
    monkeypatch.setenv("NODE_PATH", str(JS))
    script = _write_fake_node(
        tmp_path,
        version="v24.0.0",
        on_eval="import json, sys; sys.stdout.write(json.dumps({'ok': True}))",
    )
    text = "a: 1\n"
    kwargs = {"kind": "yaml-failsafe", "text": text, "node": str(script), "timeout": 30}

    def old():
        return _legacy_node_load(kwargs["kind"], kwargs["text"], kwargs["node"], kwargs["timeout"])

    def new():
        return xprobe._node_load(kwargs["kind"], kwargs["text"], kwargs["node"], kwargs["timeout"])

    _assert_same_outcome(old, new)


def test_node_missing_matches_legacy_type(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name, **kw: None)
    xprobe._node_launch_module().clear_probe_cache()

    def old():
        return _legacy_node_load("yaml-failsafe", "a: 1\n", None, 30)

    def new():
        return xprobe._node_load("yaml-failsafe", "a: 1\n", None, 30)

    with pytest.raises(RuntimeError, match="node not found"):
        old()
    with pytest.raises(RuntimeError, match=r"Node 24\+.*node not found"):
        new()


def test_node_v20_rejected_while_legacy_would_run(tmp_path, monkeypatch):
    monkeypatch.setenv("NODE_PATH", str(JS))
    script = _write_fake_node(
        tmp_path,
        version="v20.0.0",
        on_eval="import json, sys; sys.stdout.write(json.dumps({'v': 20}))",
    )
    text = "a: 1\n"
    legacy = _legacy_node_load("yaml-failsafe", text, str(script), 30)
    assert legacy == {"v": 20}
    with pytest.raises(RuntimeError, match=r"Node 24\+.*found Node 20"):
        xprobe._node_load("yaml-failsafe", text, str(script), 30)


def test_nonzero_exit_matches_legacy(tmp_path, monkeypatch):
    monkeypatch.setenv("NODE_PATH", str(JS))
    script = _write_fake_node(
        tmp_path,
        version="v24.0.0",
        on_eval="import sys; sys.stderr.write('parse:bad token'); sys.exit(3)",
    )
    text = "a: 1\n"

    def old():
        return _legacy_node_load("yaml-failsafe", text, str(script), 30)

    def new():
        return xprobe._node_load("yaml-failsafe", text, str(script), 30)

    _assert_same_outcome(old, new)


def test_timeout_cmd_includes_resolved_node(tmp_path, monkeypatch):
    script = _write_fake_node(tmp_path, version="v24.0.0", on_eval="import time; time.sleep(60)")
    node_launch = xprobe._node_launch_module()

    def hang(*args, **kwargs):
        raise node_launch.LaunchError(
            "node_launch: Node process timed out",
            code="ELAUNCHFAILURE",
            stdout=b"",
            stderr=b"",
        )

    monkeypatch.setattr(node_launch, "run", hang)
    with pytest.raises(subprocess.TimeoutExpired) as info:
        xprobe._xprobe_node_run("-e", "sleep", input="x", node=str(script), timeout=7, check=False)
    assert info.value.timeout == 7
    assert info.value.cmd == [str(script), "-e", "sleep"]


def test_timeout_matches_legacy(monkeypatch, tmp_path):
    script = _write_fake_node(tmp_path, version="v24.0.0", on_eval="pass")
    cmd = [str(script), "-e", xprobe._NODE_LOADER, "toml"]
    timeout = 11
    node_launch = xprobe._node_launch_module()

    def launch_timeout(*args, **kwargs):
        raise node_launch.LaunchError(
            "node_launch: Node process timed out",
            code="ELAUNCHFAILURE",
            stdout=b"",
            stderr=b"",
        )

    monkeypatch.setattr(node_launch, "run", launch_timeout)

    def old():
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

    def new():
        return xprobe._node_load("toml", "a = 1\n", str(script), timeout)

    _assert_same_outcome(old, new)


def test_stdin_closed_nonzero_surfaces_legacy_value_error(tmp_path, monkeypatch):
    script = _write_fake_node(tmp_path, version="v24.0.0", close_stdin_unread=True)
    monkeypatch.setenv("NODE_PATH", str(JS))

    def old():
        return _legacy_node_load("toml", _STDIN_CLOSED_PAYLOAD, str(script), 30)

    def new():
        return xprobe._node_load("toml", _STDIN_CLOSED_PAYLOAD, str(script), 30)

    with pytest.raises(ValueError, match="invalid TOML: boom"):
        old()
    with pytest.raises(ValueError, match="invalid TOML: boom"):
        new()


def test_explicit_missing_node_path_raises_file_not_found(tmp_path, monkeypatch):
    missing = tmp_path / "definitely-not-node"
    assert not missing.exists()

    def old():
        return _legacy_node_load("yaml-failsafe", "a: 1\n", str(missing), 30)

    def new():
        return xprobe._node_load("yaml-failsafe", "a: 1\n", str(missing), 30)

    with pytest.raises(FileNotFoundError) as old_exc:
        old()
    with pytest.raises(FileNotFoundError) as new_exc:
        new()
    assert new_exc.value.errno == errno.ENOENT
    assert str(missing) in (new_exc.value.filename or "")


def test_node_not_on_path_raises_runtime_error(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name, **kw: None)
    xprobe._node_launch_module().clear_probe_cache()
    with pytest.raises(RuntimeError, match=r"Node 24\+.*node not found"):
        xprobe._node_load("yaml-failsafe", "a: 1\n", None, 30)


def test_stdin_closed_zero_exit_returns_result_with_large_input(tmp_path, monkeypatch):
    payload = json.dumps({"ok": True}).encode()
    script = _write_fake_node(
        tmp_path,
        version="v24.0.0",
        close_stdin_unread=True,
        stdin_close_exit_code=0,
        stdin_close_stdout=payload,
    )
    monkeypatch.setenv("NODE_PATH", str(JS))
    assert xprobe._node_load("yaml-failsafe", _LARGE_INPUT, str(script), 30) == {"ok": True}


@pytest.mark.skipif(
    not _load_config_mod._node_reader_ready(),
    reason="Node 24+ and tests/js required",
)
def test_load_yaml_under_python_I_subprocess():
    env = os.environ.copy()
    env["NODE_PATH"] = str(JS)
    env["PYTHONPATH"] = str(ROOT)
    code = "import xprobe; print(xprobe.load_yaml('a: 1\\n'))"
    done = subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert ast.literal_eval(done.stdout.strip()) == {"a": 1}


def _broken_xprobe_node_run_no_stdin_zero(target, *args, **kwargs):
    """Simulates removing the ELAUNCHSTDINCLOSED status==0 branch in production."""
    import subprocess

    node_launch = xprobe._node_launch_module()
    run_kwargs = dict(kwargs)
    node = run_kwargs.pop("node", None)
    env_var = run_kwargs.pop("env_var", node_launch.DEFAULT_ENV_VAR)
    run_kwargs.pop("probe", None)
    timeout = run_kwargs.pop("timeout", 30)
    executable = node_launch.resolve_node(node=node, env_var=env_var)
    command = node_launch.node_command(
        target, *args, node=executable, probe=False, env_var=env_var
    )
    try:
        return node_launch.run(
            target,
            *args,
            timeout=timeout,
            node=executable,
            probe=False,
            **run_kwargs,
        )
    except node_launch.LaunchError as exc:
        if exc.code == "ELAUNCHSTDINCLOSED":
            status = exc.status if exc.status is not None else -1
            if status != 0:
                return subprocess.CompletedProcess(
                    command, status, exc.stdout, exc.stderr
                )
            raise
        if exc.code == "ELAUNCHFAILURE" and "timed out" in str(exc):
            raise subprocess.TimeoutExpired(
                cmd=command,
                timeout=timeout,
                output=exc.stdout,
                stderr=exc.stderr,
            ) from exc
        raise


def test_mutation_stdin_zero_mapping_required(tmp_path, monkeypatch):
    payload = json.dumps({"z": 1}).encode()
    script = _write_fake_node(
        tmp_path,
        version="v24.0.0",
        close_stdin_unread=True,
        stdin_close_exit_code=0,
        stdin_close_stdout=payload,
    )
    monkeypatch.setenv("NODE_PATH", str(JS))
    assert xprobe._node_load("yaml-failsafe", _LARGE_INPUT, str(script), 30) == {"z": 1}
    node_launch = xprobe._node_launch_module()
    monkeypatch.setattr(xprobe, "_xprobe_node_run", _broken_xprobe_node_run_no_stdin_zero)
    with pytest.raises(node_launch.LaunchError, match="stdin pipe closed"):
        xprobe._node_load("yaml-failsafe", _LARGE_INPUT, str(script), 30)


def _broken_xprobe_node_run_no_timeout(target, *args, **kwargs):
    node_launch = xprobe._node_launch_module()
    run_kwargs = dict(kwargs)
    node = run_kwargs.pop("node", None)
    env_var = run_kwargs.pop("env_var", node_launch.DEFAULT_ENV_VAR)
    run_kwargs.pop("probe", None)
    timeout = run_kwargs.pop("timeout", 30)
    executable = node_launch.resolve_node(node=node, env_var=env_var)
    return node_launch.run(
        target,
        *args,
        timeout=timeout,
        node=executable,
        probe=False,
        **run_kwargs,
    )


def test_mutation_timeout_mapping_required(tmp_path, monkeypatch):
    script = _write_fake_node(tmp_path, version="v24.0.0", on_eval="pass")
    node_launch = xprobe._node_launch_module()

    def launch_timeout(*args, **kwargs):
        raise node_launch.LaunchError(
            "node_launch: Node process timed out",
            code="ELAUNCHFAILURE",
            stdout=b"",
            stderr=b"",
        )

    monkeypatch.setattr(node_launch, "run", launch_timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        xprobe._node_load("toml", "a = 1\n", str(script), 9)

    monkeypatch.setattr(xprobe, "_xprobe_node_run", _broken_xprobe_node_run_no_timeout)
    with pytest.raises(node_launch.LaunchError, match="timed out"):
        xprobe._node_load("toml", "a = 1\n", str(script), 9)


def test_mutation_file_not_found_mapping_required(tmp_path, monkeypatch):
    missing = tmp_path / "no-node-here"
    with pytest.raises(FileNotFoundError):
        xprobe._node_load("yaml-failsafe", "a: 1\n", str(missing), 30)

    def broken_backend(exc, package, node):
        raise RuntimeError(
            f"needs Node 24+ with {package} (npm i --no-save {package}); node not found"
        )

    monkeypatch.setattr(xprobe, "_node_backend_error", broken_backend)
    with pytest.raises(RuntimeError, match="node not found"):
        xprobe._node_load("yaml-failsafe", "a: 1\n", str(missing), 30)


def test_mutation_version_mapping_required(tmp_path, monkeypatch):
    script = _write_fake_node(tmp_path, version="v20.0.0", on_eval="pass")
    with pytest.raises(RuntimeError, match="found Node 20"):
        xprobe._node_load("yaml-failsafe", "a: 1\n", str(script), 30)

    def broken_backend(exc, package, node):
        raise RuntimeError(
            f"needs Node 24+ with {package} (npm i --no-save {package}); node not found"
        )

    monkeypatch.setattr(xprobe, "_node_backend_error", broken_backend)
    with pytest.raises(RuntimeError, match="node not found"):
        xprobe._node_load("yaml-failsafe", "a: 1\n", str(script), 30)
