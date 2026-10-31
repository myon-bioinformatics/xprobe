"""Offline checks for historical replay; no performance thresholds."""
import hashlib
import importlib.util
import itertools
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import experiment_consumer_selection as experiment


@pytest.mark.parametrize('size', [128, 512])
def test_concrete_population_and_independent_pair_oracle(size):
    cases, matrix = experiment.population(size)
    assert len(cases) == len({c['id'] for c in cases}) == size
    assert len({tuple(c['value'].values()) for c in cases}) == size
    represented = set()
    for c in cases:
        positions = [i for i in range(22) if c['factor_bits'] & (1 << i)]
        assert len(positions) == 4
        represented.update(itertools.combinations(positions, 2))
    reported = {tuple(i for i in range(22) if p['bits'] & (1 << i)) for p in matrix['uncovered_pairs']}
    assert represented == reported


@pytest.mark.parametrize('size', [128, 512])
def test_full_modules_old_fails_fixed_matches_literal_oracle(size):
    rows = experiment.replay(experiment.population(size)[0])
    # Five unsafe replacement strings out of eight, both directions/all contexts.
    assert sum(not r['old']['matches_expected'] for r in rows) == size * 5 // 8
    assert all(r['fixed']['matches_expected'] for r in rows)
    assert any('error' in r['old'] for r in rows)
    assert any('output' in r['old'] for r in rows)


@pytest.mark.parametrize('method', experiment.METHODS)
def test_replay_budget_and_complete_coverage(method):
    cases, matrix = experiment.population(128)
    first, _ = experiment.select(cases, matrix, method, 10, 42)
    again, _ = experiment.select(cases, matrix, method, 10, 42)
    assert first == again
    assert len({c['id'] for c in first}) == 10
    empty, _ = experiment.select(cases, matrix, method, 0, 42)
    assert empty == []
    full, _ = experiment.select(cases, matrix, method, 128, 42)
    assert {c['id'] for c in full} == {c['id'] for c in cases}


def test_seeded_and_greedy_reuse_existing_rules():
    cases, matrix = experiment.population(128)
    shuffled = list(cases)
    random.Random(7).shuffle(shuffled)
    assert experiment.select(cases, matrix, 'seeded', 10, 7)[0] == shuffled[:10]
    assert experiment.select(cases, matrix, 'greedy', 10, 7)[0] == experiment.xprobe._greedy_factor_cases(cases,matrix['uncovered_pairs'],10)
    # Production API still exposes only the existing modes.
    with pytest.raises(ValueError):
        experiment.xprobe.generate_factor_cases(selection='binary-1-none')


def test_worker_separates_exclusions_and_actual_defect():
    row = experiment.worker(128, 'binary-1-none', 10, 7)
    assert row['selected_input_count'] + row['budget_excluded'] == 128
    assert len(row['approximation_omitted_ids']) == row['budget_excluded']
    assert row['approximation_prepruned'] == row['exact_eligibility_excluded'] == 0
    assert row['historical_defects_total'] == 1
    assert row['historical_defects_detected'] == bool(row['detecting_ids'])
    assert len(row['cpu_ns_samples']) == 3


@pytest.mark.parametrize('kind,blob', [
    ('old', 'edc3e4bfdfcac197c171a0173c7b4a666e3ffa0a'),
    ('fixed', 'ecde76e000e32f98ee3a3f3c5a722bb462e73f26')])
def test_upstream_module_bytes(kind, blob):
    data = (ROOT/'tests/fixtures'/f'rulebook-{kind}.py').read_bytes()
    assert hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest() == blob
