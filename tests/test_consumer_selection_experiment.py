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


def test_saved_evidence_consistent_with_exact_replay():
    import gzip
    import json
    data = json.loads(gzip.decompress((ROOT/'docs/experiments/consumer-selection.json.gz').read_bytes()))
    assert len(data['rows']) == 500
    assert len({(r['size'],r['method'],r['budget'],r['seed']) for r in data['rows']}) == 500
    for filename, digest in data['source_sha256'].items():
        # Historical timing provenance is frozen, not relabeled after runtime changes.
        source_path = ('tests/fixtures/xprobe-consumer-selection-measured.py'
                       if filename == 'xprobe.py' else filename)
        source = (ROOT/source_path).read_bytes()
        # Permit Git's LF/CRLF checkout translation for code, not fixture bytes.
        if not source_path.startswith('tests/fixtures/'):
            source = source.replace(b'\r\n', b'\n')
        assert hashlib.sha256(source).hexdigest() == digest
    for size in (128, 512):
        cases, matrix = experiment.population(size)
        by_id = {c['id']:c for c in cases}
        historical = {r['id']:r for r in data['replay'][str(size)]}
        # Re-execute full pinned modules rather than trusting recorded outcomes.
        for current in experiment.replay(cases):
            recorded = historical[current['id']]
            assert current['value'] == recorded['value']
            for kind in ('old', 'fixed'):
                assert current[kind]['matches_expected'] == recorded[kind]['matches_expected']
                assert current[kind].get('output') == recorded[kind].get('output')
                # re.error was renamed PatternError in newer Python releases.
                assert ('error' in current[kind]) == ('error' in recorded[kind])
        for row in (r for r in data['rows'] if r['size'] == size):
            ids = row['selected_ids']
            assert len(set(ids)) == len(ids) == row['budget']
            assert set(ids) <= by_id.keys()
            detected = [i for i in ids if not historical[i]['old']['matches_expected']]
            assert row['detecting_ids'] == detected
            assert row['failing_input_count'] == len(detected)
            assert row['historical_defects_detected'] == int(bool(detected))
            assert row['historical_defects_total'] == 1
            assert row['budget_excluded'] == size-len(ids)
            assert row['exact_eligibility_excluded'] == row['approximation_prepruned'] == 0
            omitted = set(by_id)-set(ids) if row['method'].startswith('binary') else set()
            assert set(row['approximation_omitted_ids']) == omitted
            pairs = set()
            for i in ids:
                bits = by_id[i]['factor_bits']
                pairs.update(itertools.combinations([j for j in range(22) if bits & (1 << j)],2))
            assert row['covered_pairs'] == len(pairs)
            assert row['target_pairs'] == len(matrix['uncovered_pairs'])


def test_archived_measurement_bytes_remain_frozen():
    archive = (ROOT / 'docs/experiments/consumer-selection.json.gz').read_bytes()
    # Original f30e025 measurement, before the later hash-only relabeling.
    assert hashlib.sha256(archive).hexdigest() == '7d9b6a3149b162898f6e290a90d79dc3d1ad3e06336c0a4832c88cfb450a1818'


def test_saved_provenance_rejects_mutated_historical_source(monkeypatch):
    original = Path.read_bytes
    def altered(path):
        data = original(path)
        if path.name == 'xprobe-consumer-selection-measured.py':
            return data + b'\n# mutation: not the measured source\n'
        return data
    monkeypatch.setattr(Path, 'read_bytes', altered)
    with pytest.raises(AssertionError):
        test_saved_evidence_consistent_with_exact_replay()
