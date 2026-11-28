"""Factor generation and selection: the public API, scripts/measure_factor_triples.py, and offline
checks of the archived consumer-selection replay (no performance thresholds)."""
import importlib.util
import hashlib, itertools, json, random, subprocess, sys
from pathlib import Path

import pytest

import xprobe
from scripts.measure_factor_triples import compare


def load_vendored(name, relpath):
    """Load a vendored file by path under a repo-unique name (cli_args README: Loading a vendored copy)."""
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / relpath)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


_cli_args = load_vendored("xprobe_cli_args", "vendor/cli_args.py")
Command = _cli_args.Command
run_command = _cli_args.run_command

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import experiment_consumer_selection as experiment


def test_matrix_preserves_source_identity_and_bit_order():
    matrix = xprobe.case_factor_matrix()
    names = matrix['factor_names']
    assert matrix['schema'] == 'xprobe.factors.v1'
    assert names == ['ascii', 'unicode', 'empty', 'whitespace', 'newline', 'nul',
                     'long', 'negative', 'zero', 'positive', 'large', 'missing',
                     'wrong_type']
    assert len(matrix['rows']) == 29
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
    assert report['schema'] == 'xprobe.factor-generation.v1'
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
    for jsonl in (False, True):
        encoded = xprobe.corpus_to_json(cases, jsonl=jsonl)
        assert xprobe.corpus_from_json(encoded, jsonl=jsonl) == xprobe.merge_cases(cases)
    assert json.loads(json.dumps(report)) == report


@pytest.mark.parametrize('count,selected', [(0, 0), (1, 1), (20, 20), (36, 36), (37, 36)])
def test_caps_and_accounting(count, selected):
    report = xprobe.generate_factor_cases(seed=-7, count=count)
    assert report['seed'] == -7 and report['limit'] == count
    assert report['selected_count'] == selected
    assert report['excluded_count'] == 36 - selected
    assert sum(report['exclusions'].values()) == report['excluded_count']
    assert report['selected_count'] + report['excluded_count'] == report['candidate_total']


@pytest.mark.parametrize('preset,total,mixed_eligible', [
    ('expanded', 42, 5), ('reduced', 12, 4),
    ('empty_text', 0, 0), ('empty_number', 0, 0),
])
@pytest.mark.parametrize('coverage', ['uncovered', 'mixed', 'covered'])
@pytest.mark.parametrize('count', [0, 2, 10000])
@pytest.mark.parametrize('selection', ['seeded', 'greedy'])
def test_accounting_tracks_changed_boundary_sets(
        monkeypatch, preset, total, mixed_eligible, coverage, count, selection):
    boundaries = {kind: xprobe.boundary_cases(kind) for kind in ('text', 'number')}
    if preset == 'expanded':
        boundaries['text'].append({'name': 'unicode_newline', 'value': 'Ω\n'})
    elif preset == 'reduced':
        boundaries['text'] = boundaries['text'][:4]
        boundaries['number'] = boundaries['number'][:3]
    elif preset == 'empty_text':
        boundaries['text'] = []
    else:
        boundaries['number'] = []
    monkeypatch.setattr(xprobe, 'boundary_cases',
                        lambda kind: [dict(case) for case in boundaries[kind]])
    matrix = xprobe.case_factor_matrix()
    eligible = total
    if coverage == 'mixed':
        matrix['uncovered_pairs'] = [pair for pair in matrix['uncovered_pairs']
                                     if pair['factors'] == ['ascii', 'zero']]
        eligible = mixed_eligible
    elif coverage == 'covered':
        matrix['uncovered_pairs'] = []
        eligible = 0
    monkeypatch.setattr(xprobe, 'case_factor_matrix', lambda: matrix)

    report = xprobe.generate_factor_cases(seed=17, count=count, selection=selection)
    selected = min(count, eligible)
    assert report['candidate_total'] == total
    assert report['selected_count'] == len(report['cases']) == selected
    assert len({case['id'] for case in report['cases']}) == selected
    assert report['exclusions'] == {'already_covered': total - eligible,
                                     'limit': eligible - selected}
    assert report['excluded_count'] == sum(report['exclusions'].values())
    assert report['selected_count'] + report['excluded_count'] == total
    assert report == xprobe.generate_factor_cases(seed=17, count=count, selection=selection)


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
    assert len(xprobe.case_factor_matrix()['rows']) == 29
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


@pytest.mark.parametrize('selection', ['seeded', 'greedy'])
def test_single_file_stdlib_replay_in_separate_process(tmp_path, selection):
    (tmp_path / 'xprobe.py').write_bytes((Path(xprobe.__file__)).read_bytes())
    code = ('import json, xprobe; '
            f'print(json.dumps(xprobe.generate_factor_cases(seed=42, count=3, selection={selection!r}), sort_keys=True))')
    result = run_command(Command((sys.executable, '-S', '-c', code)), cwd=tmp_path, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == xprobe.generate_factor_cases(seed=42, count=3, selection=selection)


@pytest.mark.parametrize('selection', ['seeded', 'greedy'])
@pytest.mark.parametrize('count', [0, 1, 6, 10, 30, 36, 10000])
def test_selection_exact_coverage_budget_and_consumer(selection, count):
    from scripts.benchmark_factor_selection import consumer_check, pair_coverage

    before = random.getstate()
    report = xprobe.generate_factor_cases(seed=7, count=count, selection=selection)
    assert random.getstate() == before
    assert len(report['cases']) == min(count, 36)
    assert report['candidate_total'] == report['selected_count'] + report['excluded_count']
    assert report['excluded_count'] == sum(report['exclusions'].values())
    assert consumer_check(report['cases'])['mismatches'] == []
    if selection == 'greedy':
        expected = {0: 0, 1: 3, 6: 18, 10: 22, 30: 42, 36: 42, 10000: 42}
        assert pair_coverage(report) == expected[count]
        assert report['selection']['approximation_excluded'] == 0
        assert report['cases'] == xprobe.generate_factor_cases(
            seed=-1, count=count, selection=selection)['cases']


def test_greedy_ties_prefixes_and_legacy_contract():
    legacy = xprobe.generate_factor_cases(seed=7, count=10)
    assert legacy == xprobe.generate_factor_cases(seed=7, count=10, selection='seeded')
    assert 'selection' not in legacy
    candidates = xprobe.generate_factor_cases(seed=0, count=36, selection='greedy')['cases']
    texts = [case['name'] for case in xprobe.boundary_cases('text')]
    numbers = [case['name'] for case in xprobe.boundary_cases('number')]
    by_id = {case['id']: case for case in candidates}
    ordered = [by_id[f'factor-v1-{text}-{number}'] for text in texts for number in numbers]
    random.Random(7).shuffle(ordered)
    assert legacy['cases'] == ordered[:10]
    for count in range(37):
        report = xprobe.generate_factor_cases(count=count, selection='greedy')
        assert report['cases'] == candidates[:count]
    with pytest.raises(ValueError, match='selection'):
        xprobe.generate_factor_cases(selection='low_rank')


@pytest.mark.parametrize('coverage', ['none', 'one', 'all'])
@pytest.mark.parametrize('count', [0, 2, 10000])
def test_greedy_partial_empty_and_already_covered(monkeypatch, coverage, count):
    matrix = xprobe.case_factor_matrix()
    if coverage == 'none':
        matrix['uncovered_pairs'] = []
    elif coverage == 'one':
        matrix['uncovered_pairs'] = [p for p in matrix['uncovered_pairs']
                                     if p['factors'] == ['ascii', 'zero']]
    monkeypatch.setattr(xprobe, 'case_factor_matrix', lambda: matrix)
    report = xprobe.generate_factor_cases(count=count, selection='greedy')
    eligible = {'none': 0, 'one': 5, 'all': 36}[coverage]
    assert report['selected_count'] == min(count, eligible)
    assert report['exclusions'] == {'already_covered': 36 - eligible,
                                     'limit': max(0, eligible - count)}
    monkeypatch.setattr(xprobe, 'boundary_cases', lambda kind: [])
    assert xprobe.generate_factor_cases(selection='greedy')['candidate_total'] == 0


def test_consumer_oracle_detects_injected_limit_fault(monkeypatch):
    from scripts.benchmark_factor_selection import consumer_check

    cases = xprobe.generate_factor_cases(count=36)['cases']
    assert consumer_check(cases)['mismatches'] == []
    real_search = xprobe.search_text

    def wrong_limit(text, pattern, *, max_matches):
        # Controlled mutation, not a discovered or historical consumer defect.
        return real_search(text, pattern, max_matches=1000)

    monkeypatch.setattr(xprobe, 'search_text', wrong_limit)
    failures = consumer_check(cases)['mismatches']
    assert 'factor-v1-long-positive' in failures
    assert 'factor-v1-empty-zero' in failures


def test_pair_coverage_is_not_fault_detection():
    from scripts.benchmark_factor_selection import consumer_check, pair_coverage

    seeded = xprobe.generate_factor_cases(seed=42, count=10)
    greedy = xprobe.generate_factor_cases(seed=42, count=10, selection='greedy')
    assert pair_coverage(greedy) > pair_coverage(seeded)
    assert consumer_check(seeded['cases'])['injected_fault']['detected']
    assert not consumer_check(greedy['cases'])['injected_fault']['detected']


# ──── scripts/measure_factor_triples.py: three-factor coverage of a finite pool ────

def test_triples_are_measured_against_finite_pool():
    names = ['a', 'b', 'c', 'd']
    pool = [{'factor_bits': 0b0111}, {'factor_bits': 0b1110}]
    report = compare(pool, pool[:1], names)
    assert report == {'candidate_triples': 2, 'covered_triples': 1,
                      'uncovered_triples': [('b', 'c', 'd')]}
    assert compare(pool, pool, names)['uncovered_triples'] == []


def test_empty_selection_and_impossible_triple():
    names = ['a', 'b', 'c', 'd']
    pool = [{'factor_bits': 0b0111}]
    assert compare(pool, [], names)['covered_triples'] == 0
    with pytest.raises(ValueError):
        compare(pool, [{'factor_bits': 0b1110}], names)


def test_real_generated_selection_against_complete_candidate_pool():
    full = xprobe.generate_factor_cases(count=10000)
    chosen = xprobe.generate_factor_cases(count=10, selection='greedy')
    report = compare(full['cases'], chosen['cases'], full['matrix']['factor_names'])
    assert report['candidate_triples'] > 0
    assert report['covered_triples'] <= report['candidate_triples']
    assert report['covered_triples'] + len(report['uncovered_triples']) == report['candidate_triples']
    assert compare(full['cases'], full['cases'], full['matrix']['factor_names'])['uncovered_triples'] == []


# ──── scripts/experiment_consumer_selection.py: archived replay, offline ────

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
