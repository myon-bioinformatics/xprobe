"""Real pytest processes: native outcomes, evidence, and unchanged exit status."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import xprobe

ROOT = Path(__file__).resolve().parents[1]


def execute(tmp_path, source, *options):
    (tmp_path / 'test_example.py').write_text(source, encoding='utf-8')
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    env.pop('PYTEST_ADDOPTS', None)
    command = [sys.executable, '-m', 'pytest', '-p', 'scripts.xprobe_pytest', '-q',
               '--xprobe-jsonl=events.jsonl', '--xprobe-repository=owner/repo',
               '--xprobe-run-id=sample', *options]
    result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    path = tmp_path / 'events.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return result, rows


def test_native_outcomes_and_explore(tmp_path):
    result, rows = execute(tmp_path, '''import pytest
@pytest.mark.parametrize("value", ["SECRET_ONE", "SECRET_TWO"])
def test_bad(value):
    assert False, value
@pytest.mark.skip(reason="SECRET_SKIP")
def test_skip(): pass
@pytest.mark.xfail(reason="SECRET_XFAIL")
def test_xfail(): assert False
@pytest.mark.xfail(reason="SECRET_XPASS")
def test_xpass(): pass
@pytest.mark.xfail(strict=True, reason="SECRET_STRICT")
def test_strict(): pass
@pytest.fixture
def broken(): raise RuntimeError("SECRET_SETUP")
def test_setup(broken): pass
@pytest.fixture
def teardown():
    yield
    raise RuntimeError("SECRET_TEARDOWN")
def test_teardown(teardown): pass
''')
    assert result.returncode == 1
    outcomes = {row['value'].get('outcome') for row in rows}
    assert {'failed', 'skipped', 'xfail', 'xpass', 'xpass_strict', 'error'} <= outcomes
    errors = [r['value']['phase'] for r in rows if r['value'].get('outcome') == 'error']
    assert set(errors) == {'setup', 'teardown'}
    bad = [r for r in rows if r['value'].get('node', '').endswith('test_bad') and r['value'].get('phase') == 'call']
    assert len({r['value']['node_hash'] for r in bad}) == 2
    assert 'SECRET_' not in json.dumps(rows)
    validated = xprobe.pytest_receipt(rows, expected_context={
        'repository': 'owner/repo', 'commit_sha': None, 'report_id': 'sample'})
    assert validated['exitstatus'] == result.returncode
    assert validated['phase_counts']['teardown']['error'] == 1
    text = (tmp_path / 'events.jsonl').read_text()
    assert len(xprobe.corpus_from_json(text, jsonl=True)) == len(rows)
    matches = xprobe.search_files(tmp_path, '"outcome": "xfail"', include=('*.jsonl',))
    assert len(matches['matches']) == 1


def test_collection_error_and_no_false_green(tmp_path):
    result, rows = execute(tmp_path, 'def broken(:\n')
    assert result.returncode == 2
    assert any(r['value'].get('phase') == 'collection' and r['value']['outcome'] == 'error' for r in rows)
    assert rows[-1]['value']['exitstatus'] == 2
    assert xprobe.pytest_receipt(rows)['exitstatus'] == result.returncode


def test_limit_marks_incomplete(tmp_path):
    result, rows = execute(tmp_path, 'def test_ok(): pass\n', '--xprobe-max-records=2')
    assert result.returncode == 0
    assert len(rows) == 4
    assert rows[-1]['value']['dropped'] == 1
    assert not rows[-1]['value']['complete']
    with pytest.raises(ValueError, match='incomplete'):
        xprobe.pytest_receipt(rows)


def test_existing_evidence_is_preserved(tmp_path):
    evidence = tmp_path / 'events.jsonl'
    evidence.write_text('[]\n')
    result, _ = execute(tmp_path, 'def test_ok(): pass\n')
    assert result.returncode != 0
    assert evidence.read_text() == '[]\n'


@pytest.mark.parametrize('options', [('--xprobe-repository=bad',), ('--xprobe-commit-sha=short',),
    ('--xprobe-run-id=bad/value',), ('--xprobe-max-records=0',)])
def test_invalid_configuration_fails_before_running(tmp_path, options):
    result, rows = execute(tmp_path, 'def test_bad(): assert False\n', *options)
    assert result.returncode == 4 and not rows


def test_canonical_sha_is_explicit_and_no_tests_is_not_pass(tmp_path):
    result, rows = execute(tmp_path, '', '--xprobe-commit-sha=' + 'A' * 40)
    assert result.returncode == 5 and rows[-1]['value']['exitstatus'] == 5
    assert all(row['context']['commit_sha'] == 'a' * 40 for row in rows)
    assert xprobe.pytest_receipt(rows)['exitstatus'] == result.returncode


def test_adapter_is_opt_in(tmp_path):
    (tmp_path / 'test_ok.py').write_text('def test_ok(): pass\n')
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    env.pop('PYTEST_ADDOPTS', None)
    result = subprocess.run([sys.executable, '-m', 'pytest', '-p', 'scripts.xprobe_pytest', '-q'],
                            cwd=tmp_path, env=env, capture_output=True, timeout=30)
    assert result.returncode == 0 and not list(tmp_path.glob('*.jsonl'))


def test_abrupt_exit_leaves_partial_evidence_without_finish(tmp_path):
    result, rows = execute(tmp_path, 'import os\ndef test_exit(): os._exit(17)\n')
    assert result.returncode == 17 and rows
    assert rows[0]['value']['event'] == 'start'
    assert not any(row['value']['event'] == 'finish' for row in rows)
    with pytest.raises(ValueError):
        xprobe.pytest_receipt(rows)
