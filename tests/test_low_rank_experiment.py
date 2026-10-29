"""Experiment controls: exact oracles and compatibility, no timing thresholds."""
import base64
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import experiment_low_rank_selection as experiment
import xprobe


def test_binary_reconstruction_and_least_squares_calibration():
    # One all-positive outer product is exact for a constant incidence matrix.
    matrix = {'uncovered_pairs': [{'bits': 3}]}
    candidates = [{'factor_bits': 3}, {'factor_bits': 3}]
    for scale in ('none', 'frequency'):
        scores, coefficients, error = experiment.approximate(candidates, matrix, 1, 7, scale)
        assert all(abs(row[0]-1) < 1e-12 for row in scores)
        assert error < 1e-24
        assert len(coefficients) == 1


def test_same_population_budget_exact_counts_and_replay():
    full = xprobe.generate_factor_cases(count=10000)
    population = {c['id'] for c in full['cases']}
    for method in experiment.METHODS:
        for budget in (0, 10, 36):
            report = experiment.generate(method, budget, 7)
            assert report == experiment.generate(method, budget, 7)
            assert len(report['cases']) == budget
            assert len({c['id'] for c in report['cases']}) == budget
            assert {c['id'] for c in report['cases']} <= population
            assert report['candidate_total'] == budget + report['excluded_count']
            assert report['excluded_count'] == sum(report['exclusions'].values())
            pairs = {tuple(p['factors']) for p in report['matrix']['uncovered_pairs']}
            names = report['matrix']['factor_names']
            observed = set()
            for c in report['cases']:
                factors = {name for i, name in enumerate(names) if c['factor_bits'] & (1 << i)}
                observed.update(p for p in pairs if set(p) <= factors)
            assert experiment.pair_coverage(report) == len(observed)
            if method.startswith('binary'):
                assert report['selection']['approximation_excluded'] == 36-budget


def test_historical_bug_exact_oracle_and_fixed_source():
    evidence = json.loads((ROOT/'docs/experiments/consumer-base64.json').read_text())
    # Execute only reviewed, checked-in function snapshots, not downloaded code.
    modules = []
    for row in evidence['rows']:
        scope = {'math': math, 'DATA_URI_PREFIX': 22}
        exec(row['function_source'], scope)
        modules.append(scope['base64_chars'])
    for n in range(80):
        assert modules[1](n) == len(base64.b64encode(bytes(n)))
    full = experiment.generate('seeded', 36, 7)
    detected = []
    for case in full['cases']:
        n = case['value']['number']
        if type(n) is not int or n < 0:
            continue
        groups, rest = divmod(n, 3)
        expected = 4*(groups+bool(rest))
        assert modules[1](n) == expected
        if modules[0](n) != expected:
            detected.append(case['id'])
    assert detected == experiment.historical(full['cases'])['detecting_ids']
    assert len(detected) == 6
    assert {c['value']['number'] for c in full['cases'] if c['id'] in detected} == {2**63}


def test_default_api_stays_seeded_and_synthetic_is_distinct():
    assert xprobe.generate_factor_cases(seed=42,count=10) == experiment.generate('seeded',10,42)
    seeded = experiment.generate('seeded',10,42)
    greedy = experiment.generate('greedy',10,42)
    assert experiment.pair_coverage(greedy) > experiment.pair_coverage(seeded)
    assert experiment.consumer_check(seeded['cases'])['injected_fault']['detected']
    assert not experiment.consumer_check(greedy['cases'])['injected_fault']['detected']
