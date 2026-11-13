"""Measure positive three-factor coverage over xprobe-generated candidates.

This measures only triples present in the finite candidate pool. It does not
claim binary covering-array coverage, consumer behavior, or fault detection.
"""
from itertools import combinations


def positive_triples(cases, factor_names):
    triples = set()
    for case in cases:
        bits = case['factor_bits']
        present = [name for index, name in enumerate(factor_names) if bits & (1 << index)]
        triples.update(combinations(present, 3))
    return triples


def compare(pool, selected, factor_names):
    possible = positive_triples(pool, factor_names)
    observed = positive_triples(selected, factor_names)
    if not observed <= possible:
        raise ValueError('selected triples must be present in the candidate pool')
    return {'candidate_triples': len(possible), 'covered_triples': len(observed),
            'uncovered_triples': sorted(possible - observed)}


def main():
    import json
    import xprobe
    pool = xprobe.generate_factor_cases(count=10000)
    result = {}
    for method in ('seeded', 'greedy'):
        chosen = xprobe.generate_factor_cases(seed=7, count=10, selection=method)
        result[method] = compare(pool['cases'], chosen['cases'], pool['matrix']['factor_names'])
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))


if __name__ == '__main__':
    main()
