import json
import random
import subprocess
import sys
from pathlib import Path

import pytest

import xprobe


def test_matrix_preserves_source_identity_and_bit_order():
    matrix = xprobe.case_factor_matrix()
    names = matrix['factor_names']
    assert len(names) == len(set(names)) == 13
    assert len(matrix['rows']) == 25
    assert {row['id'] for row in matrix['rows']} == {
        case['id'] for case in xprobe.known_bad_cases()
    } | {'boundary-' + kind + '-' + case['name']
         for kind in ('text', 'number') for case in xprobe.boundary_cases(kind)}
    rows = {row['id']: row['bits'] for row in matrix['rows']}

    def factors(ident):
        return {name for index, name in enumerate(names)
                if rows[ident] & (1 << index)}

    assert factors('nul_fenced_code') == {'ascii', 'nul', 'newline'}
    assert factors('boundary-text-unicode') == {'unicode'}
    assert factors('boundary-text-long') == {'ascii', 'long'}
    assert factors('boundary-text-empty') == {'ascii', 'empty'}
    assert factors('boundary-text-space') == {'ascii', 'whitespace'}
    assert factors('boundary-text-newline') == {'ascii', 'whitespace', 'newline'}
    assert factors('null_not_measured') == {'missing'}
    assert factors('boundary-number-wrong_type') == {'wrong_type'}
    assert factors('boundary-number-large') == {'large'}
    assert len(matrix['uncovered_pairs']) == 42
    for pair in matrix['uncovered_pairs']:
        assert pair['bits'] == sum(1 << names.index(n) for n in pair['factors'])
        assert not any(row['bits'] & pair['bits'] == pair['bits']
                       for row in matrix['rows'])


def test_full_generation_is_new_cartesian_product_without_expectations():
    report = xprobe.generate_factor_cases(seed=7, count=10000)
    cases = report['cases']
    assert report['candidate_total'] == report['selected_count'] == len(cases) == 36
    assert report['excluded_count'] == 0
    assert len({case['id'] for case in cases}) == 36
    assert {(case['value']['text'], case['value']['number']) for case in cases} == {
        (text['value'], number['value'])
        for text in xprobe.boundary_cases('text')
        for number in xprobe.boundary_cases('number')}
    unicode_large = next(case for case in cases if case['id'] == 'factor-v1-unicode-large')
    assert unicode_large['value'] == {'text': '日本語🙂', 'number': 2**63}
    for case in cases:
        assert not {'expected', 'raises', 'passed'} & case.keys()
        assert any(case['factor_bits'] & pair['bits'] == pair['bits']
                   for pair in report['matrix']['uncovered_pairs'])
    assert all(any(case['factor_bits'] & pair['bits'] == pair['bits']
                   for case in cases)
               for pair in report['matrix']['uncovered_pairs'])
    # Generated records compose with existing persistence; order is canonicalized.
    assert xprobe.corpus_from_json(xprobe.corpus_to_json(cases)) == xprobe.merge_cases(cases)
    assert json.loads(json.dumps(report)) == report


@pytest.mark.parametrize('count,selected', [(0, 0), (1, 1), (20, 20), (36, 36), (37, 36)])
def test_caps_and_accounting(count, selected):
    report = xprobe.generate_factor_cases(seed=-7, count=count)
    assert report['seed'] == -7 and report['limit'] == count
    assert report['selected_count'] == selected
    assert report['excluded_count'] == 36 - selected
    assert sum(report['exclusions'].values()) == report['excluded_count']
    assert report['selected_count'] + report['excluded_count'] == report['candidate_total']


def test_seed_replay_freshness_and_rng_isolation():
    before = random.getstate()
    first = xprobe.generate_factor_cases(seed=42, count=5)
    assert first == xprobe.generate_factor_cases(seed=42, count=5)
    assert first != xprobe.generate_factor_cases(seed=43, count=5)
    assert first['cases'] == xprobe.generate_factor_cases(seed=42, count=6)['cases'][:5]
    assert random.getstate() == before
    first['cases'][0]['value']['text'] = 'mutated'
    first['matrix']['factor_names'].clear()
    first['matrix']['rows'].clear()
    assert len(xprobe.case_factor_matrix()['rows']) == 25
    assert all(case['value']['text'] != 'mutated'
               for case in xprobe.generate_factor_cases(seed=42)['cases'])


@pytest.mark.parametrize('args', [
    {'seed': True}, {'seed': None}, {'seed': '1'}, {'seed': 1.5},
    {'count': True}, {'count': None}, {'count': '1'}, {'count': 1.5},
    {'count': -1}, {'count': 10001},
])
def test_invalid_options(args):
    with pytest.raises(ValueError):
        xprobe.generate_factor_cases(**args)


def test_covered_candidates_are_excluded(monkeypatch):
    original = xprobe.case_factor_matrix()
    original['uncovered_pairs'] = []
    monkeypatch.setattr(xprobe, 'case_factor_matrix', lambda: original)
    report = xprobe.generate_factor_cases()
    assert report['cases'] == []
    assert report['exclusions'] == {'already_covered': 36, 'limit': 0}
    assert report['excluded_count'] == 36


def test_generation_never_executes_targets(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('generation executed a target or performed I/O')
    monkeypatch.setattr(xprobe, 'run_cases', forbidden)
    monkeypatch.setattr(Path, 'open', forbidden)
    monkeypatch.setattr(subprocess, 'run', forbidden)
    assert xprobe.generate_factor_cases()['selected_count'] == 20


def test_legacy_seeded_sampling_unchanged():
    cases = xprobe.generate_cases(seed=42, count=5)
    assert [case['origin_id'] for case in cases] == [
        'data_comma', 'short_sha', 'invalid_sha', 'escaped_sql_name', 'crlf']
    source = {case['id']: case for case in xprobe.known_bad_cases()}
    for index, case in enumerate(cases):
        origin = case['origin_id']
        assert case == {**source[origin], 'id': f'generated-{index}-{origin}',
                        'origin_id': origin}
    assert len(xprobe.boundary_cases('text')) == len(xprobe.boundary_cases('number')) == 6


def test_single_file_stdlib_replay_in_separate_process(tmp_path):
    (tmp_path / 'xprobe.py').write_bytes((Path(xprobe.__file__)).read_bytes())
    code = ('import json, xprobe; '
            'print(json.dumps(xprobe.generate_factor_cases(seed=42, count=3), sort_keys=True))')
    result = subprocess.run([sys.executable, '-S', '-c', code], cwd=tmp_path,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == xprobe.generate_factor_cases(seed=42, count=3)
