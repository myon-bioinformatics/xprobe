"""Exact greedy parity, including ties and the Python 3.9 fallback."""
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import xprobe


def reference(candidates, pairs, count):
    remaining = sorted(candidates, key=lambda c: c['id'])
    covered = set()
    selected = []
    while remaining and len(selected) < count:
        gains = [{i for i, pair in enumerate(pairs)
                  if case['factor_bits'] & pair['bits'] == pair['bits']} - covered
                 for case in remaining]
        best = max(range(len(remaining)), key=lambda i: len(gains[i]))
        covered.update(gains[best])
        selected.append(remaining.pop(best))
    return selected


class PopcountTests(unittest.TestCase):
    def test_randomized_selection_matches_set_oracle(self):
        rng = random.Random(20261104)
        for width in (0, 1, 8, 64, 256):
            pairs = [{'bits': rng.getrandbits(12)} for _ in range(width)]
            candidates = [{'id': str(i), 'factor_bits': rng.getrandbits(12)} for i in range(40)]
            for count in (0, 1, 10, 40, 45):
                expected = reference(candidates, pairs, count)
                self.assertEqual(xprobe._greedy_factor_cases(candidates, pairs, count), expected)
                with patch.object(xprobe, '_factor_popcount', lambda v: bin(v).count('1')):
                    self.assertEqual(xprobe._greedy_factor_cases(candidates, pairs, count), expected)

    def test_real_corpus_and_ties_are_stable(self):
        report = xprobe.generate_factor_cases(count=10000)
        candidates = report['cases']
        pairs = report['matrix']['uncovered_pairs']
        before = [dict(case) for case in candidates]
        self.assertEqual(xprobe._greedy_factor_cases(candidates, pairs, 20), reference(candidates, pairs, 20))
        self.assertEqual(candidates, before)
        self.assertEqual(xprobe._greedy_factor_cases([], pairs, 10), [])
        tied = [{'id': 'z', 'factor_bits': 0}, {'id': 'a', 'factor_bits': 0}]
        self.assertEqual([c['id'] for c in xprobe._greedy_factor_cases(tied, pairs, 2)], ['a', 'z'])


if __name__ == '__main__':
    unittest.main()
