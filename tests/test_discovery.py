import json
import random
import subprocess
import sys
from pathlib import Path

import pytest
import xprobe

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('text,category,key', [
    ('Authorization: Bearer sentinel-secret', 'header', 'Authorization'),
    ('API_TOKEN=sentinel-secret', 'secret_like', 'API_TOKEN'),
    ('"password": "sentinel-secret"', 'secret_like', 'password'),
    ('DOCKER_HOST=tcp://host:2375', 'configuration', 'DOCKER_HOST'),
    ('goma_dir=/tools/goma', 'configuration', 'goma_dir'),
    ('url=https://user:sentinel-secret@host/a?token=sentinel-secret', 'url', 'https://'),
    ('Cookie: sid=sentinel-secret', 'header', 'Cookie'),
])
def test_builtin_discovery_never_echoes_values(text, category, key):
    report = xprobe.inspect_text(text)
    assert any(row['category'] == category and row['key'] == key for row in report['findings'])
    assert 'sentinel-secret' not in json.dumps(report)
    assert all(row['value'] == '<redacted>' for row in report['findings'])
    assert not any('text' in row or 'match' in row for row in report['findings'])


def test_coordinates_unrecognized_and_exact_limit():
    text = 'ordinary words\r\nport=8080\nHOST=localhost'
    assert [row['line'] for row in xprobe.inspect_text(text)['findings']] == [2, 3]
    assert not xprobe.inspect_text(text, max_findings=2)['truncated']
    assert xprobe.inspect_text(text, max_findings=1)['truncated']
    assert xprobe.inspect_text('a=1')['findings'] == []
    with pytest.raises(TypeError):
        xprobe.inspect_text(b'raw')
    with pytest.raises(ValueError):
        xprobe.inspect_text(text, max_findings=0)


def test_environment_explicit_and_redacted(monkeypatch):
    monkeypatch.setenv('UNRELATED_SENTINEL', 'do-not-read')
    rows = xprobe.inspect_environment({'PORT': '8080', 'TOKEN': 'secret', 'EMPTY': '', 'ordinary': 'x'})
    assert [r['key'] for r in rows] == ['EMPTY', 'PORT', 'TOKEN']
    assert rows[0]['present'] is False
    assert 'secret' not in json.dumps([r['value'] for r in rows])
    assert 'UNRELATED_SENTINEL' not in json.dumps(rows)
    with pytest.raises(TypeError):
        xprobe.inspect_environment({'PORT': 1})


def test_config_pipeline_filters_hidden_bounds_and_errors(tmp_path):
    (tmp_path / '.env').write_text('TOKEN=sentinel-secret\nPORT=8080', encoding='utf-8')
    (tmp_path / 'z.yaml').write_text('url: https://user:sentinel-secret@host', encoding='utf-8')
    (tmp_path / 'binary.env').write_bytes(b'TOKEN=x\0')
    (tmp_path / 'node_modules').mkdir()
    (tmp_path / 'node_modules' / 'bad.env').write_text('TOKEN=excluded', encoding='utf-8')
    report = xprobe.scan_config(tmp_path)
    assert {r['source'] for r in report['findings']} == {'.env', 'z.yaml'}
    assert report['skipped'] == [{'path': 'binary.env', 'reason': 'binary'}]
    assert not report['errors']
    assert 'sentinel-secret' not in json.dumps(report)
    assert not report['truncated']
    assert xprobe.scan_config(tmp_path, max_findings=1)['truncated']
    yaml = xprobe.scan_config(tmp_path, include=('*.yaml',))
    assert {r['source'] for r in yaml['findings']} == {'z.yaml'}
    assert not yaml['skipped']


def test_glob_validation_and_raw_search_filters(tmp_path):
    (tmp_path / 'a.py').write_text('hit', encoding='utf-8')
    (tmp_path / 'b.md').write_text('hit', encoding='utf-8')
    assert [r['path'] for r in xprobe.search_files(tmp_path, 'hit', include=('*.py',))['matches']] == ['a.py']
    for include in ('*.py', [1], ['']):
        with pytest.raises((TypeError, ValueError)):
            xprobe.scan_config(tmp_path, include=include)


def test_discovery_cli_and_corpus_cli(tmp_path):
    (tmp_path / '.env').write_text('PASSWORD=sentinel-secret', encoding='utf-8')
    cli = str(ROOT / 'scripts/xprobe_cli.py')
    proc = subprocess.run([sys.executable, cli, '--scan-config', '--root', str(tmp_path)],
                          capture_output=True, text=True, timeout=20)
    assert proc.returncode == 0, proc.stderr
    assert 'sentinel-secret' not in proc.stdout + proc.stderr
    assert json.loads(proc.stdout)['findings'][0]['key'] == 'PASSWORD'
    corpus = subprocess.run([sys.executable, cli, '--corpus', '--count', '3', '--seed', '7', '--format', 'jsonl'],
                            capture_output=True, text=True, timeout=20)
    assert corpus.returncode == 0
    assert len(xprobe.corpus_from_json(corpus.stdout, jsonl=True)) == 3


def test_recorded_regressions_round_trip_dedupe_and_independence():
    rows = xprobe.known_bad_cases()
    assert {'invalid_sha', 'nul_placeholder', 'nul_fenced_code', 'windows_device'} <= {r['id'] for r in rows}
    extra = {'id': 'pytest-repro-17', 'category': 'regression', 'value': {'input': [None, '\0']},
             'reason': 'Recorded target failure; expectations stay with its regression test.'}
    merged = xprobe.merge_cases(rows, [extra], [extra])
    assert len(merged) == len(rows) + 1
    extra['value']['input'].append('changed')
    assert len(next(r for r in merged if r['id'] == extra['id'])['value']['input']) == 2
    for jsonl in (False, True):
        encoded = xprobe.corpus_to_json(merged, jsonl=jsonl)
        assert '\0' not in encoded
        assert xprobe.corpus_from_json(encoded, jsonl=jsonl) == merged
    rows[0]['reason'] = 'changed'
    assert xprobe.known_bad_cases()[0]['reason'] != 'changed'


def test_generation_determinism_and_no_global_rng():
    state = random.getstate()
    first = xprobe.generate_cases(seed=42, count=25)
    assert first == xprobe.generate_cases(seed=42, count=25)
    assert first != xprobe.generate_cases(seed=43, count=25)
    assert random.getstate() == state
    assert len({r['id'] for r in first}) == 25
    assert all(r['category'] == 'git' for r in xprobe.generate_cases(category='git'))
    assert xprobe.generate_cases(count=0) == []


@pytest.mark.parametrize('case', [None, {}, {'id': '', 'category': 'x', 'value': 1, 'reason': 'x'},
    {'id': 'a', 'category': 'x', 'value': float('nan'), 'reason': 'x'},
    {'id': 'a', 'category': 'x', 'value': (1, 2), 'reason': 'x'},
    {'id': 'a', 'category': 'x', 'value': {1: 2}, 'reason': 'x'}])
def test_bad_recorded_cases(case):
    with pytest.raises(ValueError):
        xprobe.merge_cases([case])


def test_corpus_conflicts_categories_and_nonfinite_json():
    case = xprobe.known_bad_cases()[0]
    with pytest.raises(ValueError):
        xprobe.merge_cases([case], [{**case, 'reason': 'different'}])
    for text in ('{}', '[NaN]', '[{"id":"a","id":"b"}]', '[{"id":"x","category":"x","reason":"x","value":1e999}]'):
        with pytest.raises(ValueError):
            xprobe.corpus_from_json(text)
    with pytest.raises(ValueError):
        xprobe.known_bad_cases('missing')
    for args in ({'seed': True}, {'count': -1}, {'count': True}, {'count': 10001}):
        with pytest.raises(ValueError):
            xprobe.generate_cases(**args)


def test_junit_failure_import_omits_logs_parameter_values_and_entities():
    xml = '''<testsuites><testsuite><testcase name="pass" />
    <testcase name="test_config[sentinel-secret]" classname="tests.config">
      <failure message="sentinel-secret">traceback sentinel-secret</failure>
      <system-out>sentinel-secret</system-out></testcase>
    <testcase name="test_error"><error /></testcase>
    <testcase name="skip"><skipped /></testcase></testsuite></testsuites>'''
    report = xprobe.cases_from_junit(xml)
    assert len(report['cases']) == 2 and not report['truncated']
    assert 'sentinel-secret' not in xprobe.corpus_to_json(report['cases'])
    assert report['cases'][0]['value']['test'] == 'test_config'
    assert xprobe.cases_from_junit(xml, max_cases=1)['truncated']
    assert not xprobe.cases_from_junit('<testsuite/>')['cases']
    for text in ('<!DOCTYPE testsuite [<!ENTITY x "secret">]><testsuite/>', '<other/>'):
        with pytest.raises(ValueError):
            xprobe.cases_from_junit(text)
    with pytest.raises(ValueError):
        xprobe.cases_from_junit(xml, max_bytes=1)
    with pytest.raises(TypeError):
        xprobe.cases_from_junit(b'xml')


def test_discovery_candidate_limit_and_case_key_validation(tmp_path):
    (tmp_path / 'many.env').write_text('a=1\na=2\na=3\nTOKEN=hidden', encoding='utf-8')
    report = xprobe.scan_config(tmp_path, max_findings=1)
    assert report['truncated'] and report['truncation_reason'] == 'candidate_limit'
    assert report['findings'] == []  # Incomplete is explicitly reported.
    case = xprobe.known_bad_cases()[0]
    with pytest.raises(ValueError):
        xprobe.merge_cases([{**case, 1: 'bad key'}])


def test_discovery_read_errors_do_not_emit_source_lines(monkeypatch, tmp_path):
    (tmp_path / 'config.env').write_text('TOKEN=sentinel-secret', encoding='utf-8')
    def denied(*args, **kwargs):
        raise PermissionError('sentinel-secret')
    monkeypatch.setattr(Path, 'open', denied)
    result = xprobe.scan_config(tmp_path)
    assert result['errors'] == [{'path': 'config.env', 'reason': 'PermissionError'}]
    assert 'sentinel-secret' not in json.dumps(result)
    assert result['findings'] == []


def test_new_apis_standalone_vendor(tmp_path):
    import shutil
    shutil.copy(ROOT / 'xprobe.py', tmp_path / 'standalone.py')
    proc = subprocess.run([sys.executable, '-B', '-c',
        "import standalone as p; assert p.inspect_text('PORT=80')['findings']; "
        "assert p.corpus_from_json(p.corpus_to_json(p.known_bad_cases())); "
        "assert p.cases_from_junit('<testsuite/>')['cases'] == []"],
        cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ''


def test_junit_cli_invalid_xml_reports_no_contents(tmp_path):
    path = tmp_path / 'result.xml'
    path.write_text('<testsuite>sentinel-secret', encoding='utf-8')
    proc = subprocess.run([sys.executable, str(ROOT / 'scripts/xprobe_cli.py'), '--junit', str(path)],
                          capture_output=True, text=True, timeout=20)
    assert proc.returncode == 2 and proc.stdout == ''
    assert 'sentinel-secret' not in proc.stderr


def test_cross_repository_junit_sources_do_not_collide():
    xml = '<testsuite><testcase name="test_shared"><failure/></testcase></testsuite>'
    first = xprobe.cases_from_junit(xml, repository='myon-bioinformatics/markdown',
                                   commit_sha='A' * 40, report_id='linux-py310')['cases']
    second = xprobe.cases_from_junit(xml, repository='myon-bioinformatics/ascii_artist',
                                    commit_sha='b' * 40, report_id='linux-py310')['cases']
    other_job = xprobe.cases_from_junit(xml, repository='myon-bioinformatics/markdown',
                                       commit_sha='a' * 40, report_id='windows-py312')['cases']
    merged = xprobe.merge_cases(first, second, other_job, first)
    assert len(merged) == 3
    assert first[0]['context']['commit_sha'] == 'a' * 40
    assert {r['context']['repository'] for r in merged} == {
        'myon-bioinformatics/markdown', 'myon-bioinformatics/ascii_artist'}
    assert xprobe.corpus_from_json(xprobe.corpus_to_json(merged, jsonl=True), jsonl=True) == merged
    unmeasured = xprobe.cases_from_junit(xml, repository='owner/repo')['cases'][0]
    assert unmeasured['context']['commit_sha'] is None


@pytest.mark.parametrize('options', [
    {'repository': 'not-a-repository'}, {'repository': 'owner/repo\nsecret'},
    {'commit_sha': 'a' * 40}, {'repository': 'owner/repo', 'commit_sha': 'short'},
    {'repository': 'owner/repo', 'commit_sha': 'G' * 40},
    {'report_id': '../escape'}, {'report_id': ''},
])
def test_junit_provenance_validation(options):
    with pytest.raises(ValueError):
        xprobe.cases_from_junit('<testsuite/>', **options)
