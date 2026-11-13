from scripts.measure_factor_triples import compare


def test_triples_are_measured_against_finite_pool():
    names = ['a', 'b', 'c', 'd']
    pool = [{'factor_bits': 0b0111}, {'factor_bits': 0b1110}]
    report = compare(pool, pool[:1], names)
    assert report == {'candidate_triples': 2, 'covered_triples': 1,
                      'uncovered_triples': [('b', 'c', 'd')]}
    assert compare(pool, pool, names)['uncovered_triples'] == []


def test_empty_selection_and_impossible_triple():
    import pytest
    names = ['a', 'b', 'c', 'd']
    pool = [{'factor_bits': 0b0111}]
    assert compare(pool, [], names)['covered_triples'] == 0
    with pytest.raises(ValueError):
        compare(pool, [{'factor_bits': 0b1110}], names)


def test_real_generated_selection_against_complete_candidate_pool():
    import xprobe
    full = xprobe.generate_factor_cases(count=10000)
    chosen = xprobe.generate_factor_cases(count=10, selection='greedy')
    report = compare(full['cases'], chosen['cases'], full['matrix']['factor_names'])
    assert report['candidate_triples'] > 0
    assert report['covered_triples'] <= report['candidate_triples']
    assert report['covered_triples'] + len(report['uncovered_triples']) == report['candidate_triples']
    assert compare(full['cases'], full['cases'], full['matrix']['factor_names'])['uncovered_triples'] == []
