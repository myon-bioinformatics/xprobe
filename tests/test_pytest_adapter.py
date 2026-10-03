"""Real pytest processes: native outcomes, evidence, and unchanged exit status."""
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import xml.etree.ElementTree as ET

import pytest
import xprobe

ROOT = Path(__file__).resolve().parents[1]


def execute(tmp_path, source, *options, evidence_directory=None):
    (tmp_path / 'test_example.py').write_text(source, encoding='utf-8')
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    env.pop('PYTEST_ADDOPTS', None)
    command = [sys.executable, '-m', 'pytest', '-p', 'scripts.xprobe_pytest', '-q',
               '--xprobe-jsonl=events.jsonl', '--xprobe-repository=owner/repo',
               '--xprobe-run-id=sample', *options]
    result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    # Preserve raw child outputs before JSON parsing or any validation can fail.
    if evidence_directory is not None:
        evidence_directory.mkdir(parents=True, exist_ok=True)
        for name in ('junit.xml', 'events.jsonl'):
            source_path = tmp_path / name
            if source_path.exists():
                target = 'pytest-events.jsonl' if name == 'events.jsonl' else name
                shutil.copyfile(source_path, evidence_directory / target)
    path = tmp_path / 'events.jsonl'
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []
    return result, rows


@pytest.mark.parametrize('junit', [False, True])
def test_native_outcomes_and_explore(tmp_path, junit):
    destination = os.environ.get('XPROBE_FAILURE_EVIDENCE') if junit else None
    directory = Path(destination) if destination else None
    result, rows = execute(tmp_path, '''import pytest
import sys
@pytest.mark.parametrize("value", ["SECRET_ONE", "SECRET_TWO"])
def test_bad(value):
    print("SECRET_STDOUT")
    print("SECRET_STDERR", file=sys.stderr)
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
def test_pass(): pass
''', *(['--junitxml=junit.xml', '-o', 'junit_logging=all'] if junit else []),
        evidence_directory=directory)
    if junit:
        xml = (tmp_path / 'junit.xml').read_text(encoding='utf-8')
        report = xprobe.cases_from_junit(xml, repository='owner/repo', report_id='sample')
        compact = xprobe.corpus_to_json(report['cases'], jsonl=True)
        if directory is not None:
            (directory / 'failures.jsonl').write_text(compact, encoding='utf-8')
    validated = xprobe.pytest_receipt(rows, expected_context={
        'repository': 'owner/repo', 'commit_sha': None, 'report_id': 'sample'})
    if directory is not None:
        (directory / 'receipt.json').write_text(
            json.dumps(validated, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    assert validated['phase_counts'] == {
        'setup': {'passed': 7, 'skipped': 1, 'error': 1},
        'call': {'failed': 2, 'passed': 2, 'xfail': 1, 'xpass': 1, 'xpass_strict': 1},
        'teardown': {'passed': 8, 'error': 1}}
    assert result.returncode == 1
    outcomes = {row['value'].get('outcome') for row in rows}
    assert {'failed', 'skipped', 'xfail', 'xpass', 'xpass_strict', 'error'} <= outcomes
    errors = [r['value']['phase'] for r in rows if r['value'].get('outcome') == 'error']
    assert set(errors) == {'setup', 'teardown'}
    bad = [r for r in rows if r['value'].get('node', '').endswith('test_bad') and r['value'].get('phase') == 'call']
    assert len({r['value']['node_hash'] for r in bad}) == 2
    assert 'SECRET_' not in json.dumps(rows)
    assert validated['exitstatus'] == result.returncode
    assert validated['phase_counts']['teardown']['error'] == 1
    text = (tmp_path / 'events.jsonl').read_text(encoding='utf-8')
    assert len(xprobe.corpus_from_json(text, jsonl=True)) == len(rows)
    matches = xprobe.search_files(tmp_path, '"outcome": "xfail"', include=('*.jsonl',))
    assert len(matches['matches']) == 1
    if junit:
        assert not report['truncated']
        # Fixture-local correspondence, not a universal cross-schema node key.
        native_failures = sorted(
            (r['value']['node'].split('::')[-1],
             'failure' if r['value']['phase'] == 'call' else 'error')
            for r in rows if r['value'].get('outcome') in {'failed', 'error', 'xpass_strict'})
        compact_failures = sorted((r['value']['test'], r['value']['kind'])
                                  for r in report['cases'])
        assert native_failures == compact_failures == [
            ('test_bad', 'failure'), ('test_bad', 'failure'),
            ('test_setup', 'error'), ('test_strict', 'failure'), ('test_teardown', 'error')]
        cases = list(ET.fromstring(xml).iter('testcase'))
        assert {c.get('name') for c in cases if c.find('skipped') is not None} == {
            'test_skip', 'test_xfail'}
        assert {c.get('name') for c in cases if not any(
            child.tag in {'failure', 'error', 'skipped'} for child in c)} == {
            'test_pass', 'test_xpass'}
        assert validated['phase_counts']['call']['passed'] == 2
        assert validated['phase_counts']['call']['xpass'] == 1
        assert all(r['context'] == validated['context'] for r in report['cases'])
        # Prove that values, messages and both output streams exercised redaction.
        assert all(token in xml for token in (
            'SECRET_ONE', 'SECRET_TWO', 'SECRET_SETUP', 'SECRET_TEARDOWN',
            'SECRET_STDOUT', 'SECRET_STDERR'))
        assert 'SECRET_' not in compact
        assert not any(token in compact for token in ('traceback', 'system-out', 'system-err'))
        assert xprobe.corpus_from_json(compact, jsonl=True) == report['cases']



def test_evidence_survives_identity_assertion_failure(tmp_path, tmp_path_factory, monkeypatch):
    directory = tmp_path_factory.mktemp('evidence')
    monkeypatch.setenv('XPROBE_FAILURE_EVIDENCE', str(directory))
    importer = xprobe.cases_from_junit

    def mismatched_identity(*args, **kwargs):
        report = importer(*args, **kwargs)
        report['cases'][0]['value']['test'] = 'unexpected_identity'
        return report

    monkeypatch.setattr(xprobe, 'cases_from_junit', mismatched_identity)
    with pytest.raises(AssertionError, match='unexpected_identity'):
        test_native_outcomes_and_explore(tmp_path, True)
    assert {p.name for p in directory.iterdir()} == {
        'junit.xml', 'pytest-events.jsonl', 'failures.jsonl', 'receipt.json'}
    assert 'SECRET_ONE' in (directory / 'junit.xml').read_text(encoding='utf-8')
    assert json.loads((directory / 'receipt.json').read_text(encoding='utf-8'))['exitstatus'] == 1


@pytest.mark.parametrize('junit', [False, True])
def test_collection_error_and_no_false_green(tmp_path, junit):
    result, rows = execute(tmp_path, 'def broken(:\n',
                           *(['--junitxml=junit.xml'] if junit else []))
    assert result.returncode == 2
    assert any(r['value'].get('phase') == 'collection' and r['value']['outcome'] == 'error' for r in rows)
    assert rows[-1]['value']['exitstatus'] == 2
    assert xprobe.pytest_receipt(rows)['exitstatus'] == result.returncode
    if junit:
        report = xprobe.cases_from_junit((tmp_path / 'junit.xml').read_text(encoding='utf-8'))
        assert not report['truncated']
        assert len(report['cases']) == 1 and report['cases'][0]['value']['kind'] == 'error'


def test_limit_marks_incomplete(tmp_path):
    result, rows = execute(tmp_path, 'def test_ok(): pass\n', '--xprobe-max-records=2',
                           '--junitxml=junit.xml')
    assert result.returncode == 0
    assert len(rows) == 4
    assert rows[-1]['value']['dropped'] == 1
    assert not rows[-1]['value']['complete']
    with pytest.raises(ValueError, match='incomplete'):
        xprobe.pytest_receipt(rows)
    assert xprobe.cases_from_junit((tmp_path / 'junit.xml').read_text(encoding='utf-8')) == {
        'cases': [], 'truncated': False}  # Empty JUnit cannot certify native completeness.


@pytest.mark.parametrize('junit', [False, True])
def test_green_exit_status_is_unchanged(tmp_path, junit):
    result, rows = execute(tmp_path, 'def test_ok(): pass\n',
                           *(['--junitxml=junit.xml'] if junit else []))
    assert result.returncode == xprobe.pytest_receipt(rows)['exitstatus'] == 0
    assert xprobe.pytest_receipt(rows)['phase_counts'] == {
        phase: {'passed': 1} for phase in ('setup', 'call', 'teardown')}
    if junit:
        assert xprobe.cases_from_junit((tmp_path / 'junit.xml').read_text(encoding='utf-8')) == {
            'cases': [], 'truncated': False}


def test_existing_evidence_is_preserved(tmp_path):
    evidence = tmp_path / 'events.jsonl'
    evidence.write_text('[]\n')
    result, _ = execute(tmp_path, 'def test_ok(): pass\n')
    assert result.returncode != 0
    assert evidence.read_text(encoding='utf-8') == '[]\n'


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


@pytest.mark.parametrize('junit', [False, True])
def test_abrupt_exit_leaves_partial_evidence_without_finish(tmp_path, junit):
    result, rows = execute(tmp_path, 'import os\ndef test_exit(): os._exit(17)\n',
                           *(['--junitxml=junit.xml'] if junit else []))
    assert result.returncode == 17 and rows
    assert rows[0]['value']['event'] == 'start'
    assert not any(row['value']['event'] == 'finish' for row in rows)
    with pytest.raises(ValueError):
        xprobe.pytest_receipt(rows)
    if junit:
        assert not (tmp_path / 'junit.xml').exists()
