"""load_toml / load_yaml: tomllib or Node (smol-toml / js-yaml), mirrored against tomllib and PyYAML.

Also covers parity of the vendored njs_launch path with the legacy subprocess loader, and the
stdlib fallback launcher that a copied xprobe.py uses when vendor/njs_launch.py is absent.
"""
from __future__ import annotations

import ast, datetime, errno, io, json, os, shutil, subprocess, sys, threading
from pathlib import Path; from typing import NamedTuple, Union

import pytest

import xprobe
from vendor import fleet_check as fleet
from vendor.cli_args import run_cli

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "tests" / "js" / "node_modules"
NODE = fleet.node()  # Node 26+, the floor of the Node readers
ANY_NODE = fleet.node(minimum=0)  # any version: an old Node must still name the missing piece


node_ready = pytest.mark.skipif(
    NODE is None or not JS.is_dir(),
    reason="run `npm ci --prefix tests/js` and use Node 26+ (CI does) to enable the Node readers",
)

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


@pytest.fixture
def _node_path(monkeypatch):
    monkeypatch.setenv("NODE_PATH", str(JS))


@pytest.mark.usefixtures("_node_path")
@node_ready
def test_toml_via_node_matches_tomllib_shape():
    value = xprobe.load_toml(TOML, node=NODE)
    assert value["owner"]["dob"] == datetime.datetime(1979, 5, 27, 15, 32, tzinfo=datetime.timezone.utc)
    assert value["owner"]["local"] == datetime.datetime(1979, 5, 27, 7, 32)
    assert value["owner"]["day"] == datetime.date(1979, 5, 27)
    assert value["owner"]["t"] == datetime.time(7, 32)
    assert value["owner"]["arr"] == [1, 2.5, True, "s"] and value["items"] == [{"name": "a"}]
    if sys.version_info >= (3, 11):
        import tomllib
        assert value == tomllib.loads(TOML) == xprobe.load_toml(TOML)


@pytest.mark.usefixtures("_node_path")
@node_ready
@pytest.mark.parametrize("literal", [
    "0", "1", "-1", "9007199254740990", "9007199254740991",
    "9007199254740992", "9007199254740993", "-9007199254740991",
    "-9007199254740992", "-9007199254740993", "9223372036854775807",
    "-9223372036854775808", "+9_223_372_036_854_775_807",
    "0x7fff_ffff_ffff_ffff", "0o1000000000000000001",
    "0b100000000000000000000000000000000000000000000000000001",
])
def test_toml_integer_boundaries_and_nesting(literal):
    text = (f"scalar = {literal}\n"
            f"nested = {{value = {literal}, items = [{literal}, {{value = {literal}}}]}}\n"
            f"[[rows]]\nvalue = {literal}\n")
    integer = int(literal.replace("_", ""), 0)
    expected = {"scalar": integer,
                "nested": {"value": integer, "items": [integer, {"value": integer}]},
                "rows": [{"value": integer}]}
    value = xprobe.load_toml(text, node=NODE)
    assert value == expected
    assert type(value["scalar"]) is int
    assert type(value["nested"]["items"][1]["value"]) is int
    assert xprobe.load_toml(text) == expected  # includes automatic Node fallback on 3.9/3.10
    if sys.version_info >= (3, 11):
        import tomllib
        assert value == tomllib.loads(text)


@pytest.mark.usefixtures("_node_path")
@node_ready
@pytest.mark.parametrize("marker", ["toml-int", "toml-datetime", "toml-table"])
def test_toml_marker_like_keys_remain_tables(marker):
    text = (f'"\\u0000{marker}" = "9007199254740993"\n'
            'nested = [{"\\u0000toml-int" = "text", value = 9223372036854775807}]\n'
            'when = 1979-05-27T07:32:00Z\n')
    expected = {"\0" + marker: "9007199254740993",
                "nested": [{"\0toml-int": "text", "value": 9223372036854775807}],
                "when": datetime.datetime(1979, 5, 27, 7, 32, tzinfo=datetime.timezone.utc)}
    value = xprobe.load_toml(text, node=NODE)
    assert value == expected
    if sys.version_info >= (3, 11):
        import tomllib
        assert value == tomllib.loads(text)


@pytest.mark.usefixtures("_node_path")
@node_ready
@pytest.mark.parametrize("schema", ["failsafe", "core"])
def test_yaml_toml_marker_like_keys_are_not_restored(schema):
    assert xprobe.load_yaml('"\\0toml-int": "9007199254740993"\n', schema=schema) == {
        "\0toml-int": "9007199254740993"}


@pytest.mark.usefixtures("_node_path")
@node_ready
def test_yaml_failsafe_matches_pyyaml_baseloader_on_real_workflows():
    yaml = pytest.importorskip("yaml")
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        assert xprobe.load_yaml(text) == yaml.load(text, Loader=yaml.BaseLoader), path.name
    assert xprobe.load_yaml("on: push\nn: 1\n") == {"on": "push", "n": "1"}


@pytest.mark.usefixtures("_node_path")
@node_ready
def test_yaml_core_types_by_yaml_1_2():
    assert xprobe.load_yaml("a: yes\nb: 1\nc: 2026-10-16\nd: ~\ne: [1.5, true]\n", schema="core") == {
        "a": "yes", "b": 1, "c": "2026-10-16", "d": None, "e": [1.5, True]}
    assert xprobe.load_yaml("", schema="core") is None


@pytest.mark.usefixtures("_node_path")
@node_ready
def test_parse_errors_are_value_errors():
    with pytest.raises(ValueError, match="invalid YAML"):
        xprobe.load_yaml("a: [")
    with pytest.raises(ValueError, match="invalid TOML"):
        xprobe.load_toml("a = ", node=NODE)


@pytest.mark.usefixtures("_node_path")
def test_backend_errors_name_the_missing_piece(tmp_path, monkeypatch):
    real = ANY_NODE
    with pytest.raises(ValueError, match="schema"):
        xprobe.load_yaml("a: 1", schema="full")
    with pytest.raises(TypeError):
        xprobe.load_yaml(b"a: 1", node="node")
    if real:
        monkeypatch.setenv("NODE_PATH", str(tmp_path))  # no packages here
        with pytest.raises(RuntimeError, match="npm i --no-save js-yaml"):
            xprobe.load_yaml("a: 1", node=real)
    monkeypatch.setattr(shutil, "which", lambda name, **kw: None)
    with pytest.raises(RuntimeError, match=r"Node 26\+.*node not found"):
        xprobe.load_yaml("a: 1")


@pytest.mark.usefixtures("_node_path")
def test_tomllib_errors_are_value_errors():
    if sys.version_info < (3, 11):
        pytest.skip("tomllib is 3.11+")
    with pytest.raises(ValueError, match="invalid TOML"):
        xprobe.load_toml("a = ")


@pytest.mark.usefixtures("_node_path")
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


# ──── vendored njs_launch: parity with the legacy subprocess loader ────

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


@pytest.fixture
def _njs_launch_process_layer_stub(monkeypatch):
    njs_launch = xprobe._njs_launch_module()
    real_run = njs_launch.subprocess.run
    real_popen = njs_launch.subprocess.Popen

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

    monkeypatch.setattr(njs_launch.subprocess, "run", fake_run)
    monkeypatch.setattr(njs_launch.subprocess, "Popen", fake_popen)
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
    """Pre-njs_launch subprocess.run loader (reference for parity tests)."""
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


@pytest.mark.usefixtures("_njs_launch_process_layer_stub")
def test_normal_load_matches_legacy(tmp_path, monkeypatch):
    monkeypatch.setenv("NODE_PATH", str(JS))
    script = _write_fake_node(
        tmp_path,
        version="v26.0.0",
        on_eval="import json, sys; sys.stdout.write(json.dumps({'ok': True}))",
    )
    text = "a: 1\n"
    kwargs = {"kind": "yaml-failsafe", "text": text, "node": str(script), "timeout": 30}

    def old():
        return _legacy_node_load(kwargs["kind"], kwargs["text"], kwargs["node"], kwargs["timeout"])

    def new():
        return xprobe._node_load(kwargs["kind"], kwargs["text"], kwargs["node"], kwargs["timeout"])

    _assert_same_outcome(old, new)


@pytest.mark.usefixtures("_njs_launch_process_layer_stub")
def test_node_missing_matches_legacy_type(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name, **kw: None)
    xprobe._njs_launch_module().clear_probe_cache()

    def old():
        return _legacy_node_load("yaml-failsafe", "a: 1\n", None, 30)

    def new():
        return xprobe._node_load("yaml-failsafe", "a: 1\n", None, 30)

    with pytest.raises(RuntimeError, match="node not found"):
        old()
    with pytest.raises(RuntimeError, match=r"Node 26\+.*node not found"):
        new()


@pytest.mark.usefixtures("_njs_launch_process_layer_stub")
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
    with pytest.raises(RuntimeError, match=r"Node 26\+.*found Node 20"):
        xprobe._node_load("yaml-failsafe", text, str(script), 30)


@pytest.mark.usefixtures("_njs_launch_process_layer_stub")
def test_nonzero_exit_matches_legacy(tmp_path, monkeypatch):
    monkeypatch.setenv("NODE_PATH", str(JS))
    script = _write_fake_node(
        tmp_path,
        version="v26.0.0",
        on_eval="import sys; sys.stderr.write('parse:bad token'); sys.exit(3)",
    )
    text = "a: 1\n"

    def old():
        return _legacy_node_load("yaml-failsafe", text, str(script), 30)

    def new():
        return xprobe._node_load("yaml-failsafe", text, str(script), 30)

    _assert_same_outcome(old, new)


@pytest.mark.usefixtures("_njs_launch_process_layer_stub")
def test_timeout_cmd_includes_resolved_node(tmp_path, monkeypatch):
    script = _write_fake_node(tmp_path, version="v26.0.0", on_eval="import time; time.sleep(60)")
    njs_launch = xprobe._njs_launch_module()

    def hang(*args, **kwargs):
        raise njs_launch.LaunchError(
            "njs_launch: Node process timed out",
            code="ELAUNCHFAILURE",
            stdout=b"",
            stderr=b"",
        )

    monkeypatch.setattr(njs_launch, "run", hang)
    with pytest.raises(subprocess.TimeoutExpired) as info:
        xprobe._xprobe_node_run("-e", "sleep", input="x", node=str(script), timeout=7, check=False)
    assert info.value.timeout == 7
    assert info.value.cmd == [str(script), "-e", "sleep"]


@pytest.mark.usefixtures("_njs_launch_process_layer_stub")
def test_timeout_matches_legacy(monkeypatch, tmp_path):
    script = _write_fake_node(tmp_path, version="v26.0.0", on_eval="pass")
    cmd = [str(script), "-e", xprobe._NODE_LOADER, "toml"]
    timeout = 11
    njs_launch = xprobe._njs_launch_module()

    def launch_timeout(*args, **kwargs):
        raise njs_launch.LaunchError(
            "njs_launch: Node process timed out",
            code="ELAUNCHFAILURE",
            stdout=b"",
            stderr=b"",
        )

    monkeypatch.setattr(njs_launch, "run", launch_timeout)

    def old():
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

    def new():
        return xprobe._node_load("toml", "a = 1\n", str(script), timeout)

    _assert_same_outcome(old, new)


@pytest.mark.usefixtures("_njs_launch_process_layer_stub")
def test_stdin_closed_nonzero_surfaces_legacy_value_error(tmp_path, monkeypatch):
    script = _write_fake_node(tmp_path, version="v26.0.0", close_stdin_unread=True)
    monkeypatch.setenv("NODE_PATH", str(JS))

    def old():
        return _legacy_node_load("toml", _STDIN_CLOSED_PAYLOAD, str(script), 30)

    def new():
        return xprobe._node_load("toml", _STDIN_CLOSED_PAYLOAD, str(script), 30)

    with pytest.raises(ValueError, match="invalid TOML: boom"):
        old()
    with pytest.raises(ValueError, match="invalid TOML: boom"):
        new()


@pytest.mark.usefixtures("_njs_launch_process_layer_stub")
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


@pytest.mark.usefixtures("_njs_launch_process_layer_stub")
def test_node_not_on_path_raises_runtime_error(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name, **kw: None)
    xprobe._njs_launch_module().clear_probe_cache()
    with pytest.raises(RuntimeError, match=r"Node 26\+.*node not found"):
        xprobe._node_load("yaml-failsafe", "a: 1\n", None, 30)


@pytest.mark.usefixtures("_njs_launch_process_layer_stub")
def test_node_env_var_does_not_override_path(tmp_path, monkeypatch):
    monkeypatch.setenv("NODE", str(tmp_path / "nonexistent-x"))
    script = _write_fake_node(
        tmp_path,
        version="v26.0.0",
        on_eval="import json, sys; sys.stdout.write(json.dumps({'via': 'path'}))",
    )
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name, **kw: str(script) if name == "node" else None,
    )
    xprobe._njs_launch_module().clear_probe_cache()
    assert xprobe._node_load("yaml-failsafe", "a: 1\n", None, 30) == {"via": "path"}


@pytest.mark.usefixtures("_njs_launch_process_layer_stub")
def test_stdin_closed_zero_exit_returns_result_with_large_input(tmp_path, monkeypatch):
    payload = json.dumps({"ok": True}).encode()
    script = _write_fake_node(
        tmp_path,
        version="v26.0.0",
        close_stdin_unread=True,
        stdin_close_exit_code=0,
        stdin_close_stdout=payload,
    )
    monkeypatch.setenv("NODE_PATH", str(JS))
    assert xprobe._node_load("yaml-failsafe", _LARGE_INPUT, str(script), 30) == {"ok": True}


@pytest.mark.usefixtures("_njs_launch_process_layer_stub")
@node_ready
def test_load_yaml_under_python_I_subprocess():
    env = os.environ.copy()
    env["NODE_PATH"] = str(JS)
    code = (
        "import pathlib, sys; "
        f"sys.path.insert(0, {str(ROOT)!r}); "
        "import xprobe; "
        "print(xprobe.load_yaml('a: 1\\n'))"
    )
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
    assert ast.literal_eval(done.stdout.strip()) == {"a": "1"}


@pytest.mark.usefixtures("_njs_launch_process_layer_stub")
def test_unmapped_launch_error_propagates(tmp_path, monkeypatch):
    script = _write_fake_node(tmp_path, version="v26.0.0", on_eval="pass")
    njs_launch = xprobe._njs_launch_module()

    def launch_weird(*args, **kwargs):
        raise njs_launch.LaunchError(
            "njs_launch: unexpected child failure",
            code="EUNMAPPED",
            status=2,
            stdout=b"",
            stderr=b"",
        )

    monkeypatch.setattr(njs_launch, "run", launch_weird)
    with pytest.raises(njs_launch.LaunchError, match="unexpected child failure"):
        xprobe._node_load("toml", "a = 1\n", str(script), 30)


@pytest.mark.usefixtures("_njs_launch_process_layer_stub")
def test_mutation_stdin_zero_mapping_required(tmp_path, monkeypatch):
    payload = json.dumps({"z": 1}).encode()
    script = _write_fake_node(
        tmp_path,
        version="v26.0.0",
        close_stdin_unread=True,
        stdin_close_exit_code=0,
        stdin_close_stdout=payload,
    )
    monkeypatch.setenv("NODE_PATH", str(JS))
    assert xprobe._node_load("yaml-failsafe", _LARGE_INPUT, str(script), 30) == {"z": 1}
    njs_launch = xprobe._njs_launch_module()
    real_map = xprobe._map_njs_launch_error

    def map_without_stdin_zero_success(exc, command, timeout):
        if exc.code == "ELAUNCHSTDINCLOSED" and (exc.status if exc.status is not None else -1) == 0:
            raise exc
        return real_map(exc, command, timeout)

    monkeypatch.setattr(xprobe, "_map_njs_launch_error", map_without_stdin_zero_success)
    with pytest.raises(njs_launch.LaunchError, match="stdin pipe closed"):
        xprobe._node_load("yaml-failsafe", _LARGE_INPUT, str(script), 30)


@pytest.mark.usefixtures("_njs_launch_process_layer_stub")
def test_mutation_timeout_mapping_required(tmp_path, monkeypatch):
    script = _write_fake_node(tmp_path, version="v26.0.0", on_eval="pass")
    njs_launch = xprobe._njs_launch_module()

    def launch_timeout(*args, **kwargs):
        raise njs_launch.LaunchError(
            "njs_launch: Node process timed out",
            code="ELAUNCHFAILURE",
            stdout=b"",
            stderr=b"",
        )

    monkeypatch.setattr(njs_launch, "run", launch_timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        xprobe._node_load("toml", "a = 1\n", str(script), 9)

    real_map = xprobe._map_njs_launch_error

    def map_without_timeout(exc, command, timeout):
        if exc.code == "ELAUNCHFAILURE" and "timed out" in str(exc):
            raise exc
        return real_map(exc, command, timeout)

    monkeypatch.setattr(xprobe, "_map_njs_launch_error", map_without_timeout)
    with pytest.raises(njs_launch.LaunchError, match="timed out"):
        xprobe._node_load("toml", "a = 1\n", str(script), 9)


@pytest.mark.usefixtures("_njs_launch_process_layer_stub")
def test_mutation_file_not_found_mapping_required(tmp_path, monkeypatch):
    missing = tmp_path / "no-node-here"
    with pytest.raises(FileNotFoundError):
        xprobe._node_load("yaml-failsafe", "a: 1\n", str(missing), 30)

    def broken_backend(exc, package, node):
        raise RuntimeError(
            f"needs Node 26+ with {package} (npm i --no-save {package}); node not found"
        )

    monkeypatch.setattr(xprobe, "_node_backend_error", broken_backend)
    with pytest.raises(RuntimeError, match="node not found"):
        xprobe._node_load("yaml-failsafe", "a: 1\n", str(missing), 30)


@pytest.mark.usefixtures("_njs_launch_process_layer_stub")
def test_mutation_version_mapping_required(tmp_path, monkeypatch):
    script = _write_fake_node(tmp_path, version="v20.0.0", on_eval="pass")
    with pytest.raises(RuntimeError, match="found Node 20"):
        xprobe._node_load("yaml-failsafe", "a: 1\n", str(script), 30)

    def broken_backend(exc, package, node):
        raise RuntimeError(
            f"needs Node 26+ with {package} (npm i --no-save {package}); node not found"
        )

    monkeypatch.setattr(xprobe, "_node_backend_error", broken_backend)
    with pytest.raises(RuntimeError, match="node not found"):
        xprobe._node_load("yaml-failsafe", "a: 1\n", str(script), 30)


@pytest.mark.usefixtures("_njs_launch_process_layer_stub")
@pytest.mark.parametrize('major', [24, 25])
@pytest.mark.parametrize('explicit', [False, True])
def test_below_node_26_reports_actual_version(tmp_path, monkeypatch, major, explicit):
    script = _write_fake_node(tmp_path, version=f'v{major}.0.0', on_eval='pass')
    monkeypatch.setattr(shutil, 'which', lambda name, **kw: str(script) if name == 'node' else None)
    xprobe._njs_launch_module().clear_probe_cache()
    with pytest.raises(RuntimeError, match=rf'Node 26\+.*found Node {major}'):
        xprobe._node_load('yaml-failsafe', 'a: 1\n', str(script) if explicit else None, 30)


# ──── copied xprobe.py alone: stdlib fallback launcher, no vendor/njs_launch.py ────

def _force_fallback(monkeypatch):
    monkeypatch.setattr(xprobe, "_NJS_LAUNCH", None)
    monkeypatch.setattr(
        xprobe,
        "_sibling_njs_launch_path",
        lambda: Path("/absent/vendor/njs_launch.py"),
    )
    launcher = xprobe._njs_launch_module()
    launcher.clear_probe_cache()
    return launcher


def _patch_probe(launcher, monkeypatch, *, stdout=b"v26.0.0\n", returncode=0, error=None):
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
    assert not (script_dir / "njs_launch.py").exists()

    def run(*args):
        return run_cli("xprobe.py", *args, python_options=("-S",), cwd=script_dir, timeout=30)

    help_done = run("--help")
    assert help_done.returncode == 0, help_done.stderr
    assert "--search" in help_done.stdout
    assert "njs_launch" not in help_done.stderr

    search = run("--search", "TODO", "--root", "note.txt")
    assert search.returncode == 0, search.stderr
    report = json.loads(search.stdout)
    assert report["matches"][0]["match"] == "TODO"
    assert report["errors"] == []

    (script_dir / "junit.xml").write_text(
        "<testsuite><testcase name='one'><failure>not in output</failure></testcase>"
        "<testcase name='two'><error/></testcase></testsuite>", encoding="utf-8")
    imported = run("--junit", "junit.xml", "--repository", "owner/repo")
    assert imported.returncode == 0, imported.stderr
    assert len(json.loads(imported.stdout)["cases"]) == 2
    assert "not in output" not in imported.stdout
    partial = run("--junit", "junit.xml", "--max-matches", "1")
    assert partial.returncode == 3, partial.stderr
    assert json.loads(partial.stdout)["truncated"] is True
    assert json.loads(partial.stderr)["code"] == "truncated"
    failed = run("--junit", "unavailable.xml")
    assert failed.returncode == 2
    assert failed.stdout == ""
    assert json.loads(failed.stderr)["code"] == "io_error"
    assert "unavailable.xml" not in failed.stderr

    loaded = run("--load", "yaml", "w.yml")
    if loaded.returncode == 0:
        assert json.loads(loaded.stdout) == {"on": "push"}
    else:
        assert loaded.returncode == 2, loaded.stderr
        assert "Node 26+" in loaded.stderr
        assert "Traceback" not in loaded.stderr
        assert "njs_launch.py" not in loaded.stderr


def test_checkout_prefers_sibling_launcher(monkeypatch):
    monkeypatch.setattr(xprobe, "_NJS_LAUNCH", None)
    module = xprobe._njs_launch_module()
    assert str(getattr(module, "__file__", "")).replace("\\", "/").endswith("vendor/njs_launch.py")


def test_tomllib_load_ignores_missing_sibling(monkeypatch):
    if sys.version_info < (3, 11):
        pytest.skip("tomllib is 3.11+")
    _force_fallback(monkeypatch)
    monkeypatch.setattr(shutil, "which", lambda *_args, **_kwargs: None)
    assert xprobe.load_toml('title = "x"\n') == {"title": "x"}


def test_fallback_missing_node_and_cli_message(monkeypatch, tmp_path, capsys):
    _force_fallback(monkeypatch)
    monkeypatch.setattr(shutil, "which", lambda *_args, **_kwargs: None)
    with pytest.raises(RuntimeError, match=r"Node 26\+.*node not found"):
        xprobe.load_yaml("a: 1\n")
    target = tmp_path / "w.yml"
    target.write_text("a: 1\n", encoding="utf-8")
    assert xprobe.main(["--load", "yaml", str(target)]) == 2
    err = capsys.readouterr().err
    assert "Node 26+" in err
    assert "node not found" in err
    assert "Traceback" not in err


def test_fallback_rejects_old_explicit_node_and_missing_path(monkeypatch, tmp_path):
    launcher = _force_fallback(monkeypatch)
    old = tmp_path / "node20"
    _patch_probe(launcher, monkeypatch, stdout=b"v20.19.0\n")
    with pytest.raises(RuntimeError, match=r"Node 26\+.*found Node 20"):
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
    node = tmp_path / "node26"
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
    node = tmp_path / "node26"
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
    node = tmp_path / "node26"
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
    node = tmp_path / "node26"
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
    node = tmp_path / "node26"
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
    node = tmp_path / "node26"
    _patch_probe(launcher, monkeypatch)

    def popen(_command, **_kwargs):
        raise OSError("spawn failed")

    _patch_popen(launcher, monkeypatch, popen)
    with pytest.raises(launcher.LaunchError, match="spawn failed"):
        xprobe.load_yaml("a: 1\n", node=str(node))
