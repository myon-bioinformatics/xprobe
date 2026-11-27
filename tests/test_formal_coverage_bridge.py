"""Observe production marginal masks; do not implement another greedy selector."""
import itertools
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import xprobe


def positions(bits):
    """Interpret a nonnegative bitset as a set, independently of pair masks."""
    return {index for index in range(bits.bit_length()) if (bits >> index) % 2}


class FormalCoverageBridgeTests(unittest.TestCase):
    def check_scored_marginals(self, candidates, pairs, count, *, public=False):
        # Keep the real popcount's return value: only observe its actual argument.
        real_popcount = xprobe._factor_popcount
        scored = []

        def observe(mask):
            score = real_popcount(mask)
            scored.append((mask, score))
            return score

        with patch.object(xprobe, '_factor_popcount', observe):
            if public:
                selected = xprobe.generate_factor_cases(
                    count=count, selection='greedy')['cases']
            else:
                selected = xprobe._greedy_factor_cases(candidates, pairs, count)

        # Source factor positions and enumerated pair positions are different
        # universes. A pair is present only when all its source factors occur.
        pair_factors = [positions(pair['bits']) for pair in pairs]
        represented = {
            case['id']: {index for index, factors in enumerate(pair_factors)
                         if factors <= positions(case['factor_bits'])}
            for case in candidates
        }
        remaining = sorted(candidates, key=lambda case: case['id'])
        chosen_coverage = set()
        cursor = 0
        self.assertEqual(len(selected), min(count, len(candidates)))
        for chosen in selected:
            # Python max evaluates every remaining candidate exactly once. We
            # consume that observed batch without computing who should win.
            for case in remaining:
                mask, score = scored[cursor]
                cursor += 1
                expected = represented[case['id']] - chosen_coverage
                self.assertGreaterEqual(mask, 0)
                self.assertLess(mask, 1 << len(pairs))
                self.assertEqual(positions(mask), expected)
                self.assertEqual(score, len(expected))
            self.assertIn(chosen, remaining)
            remaining.remove(chosen)
            chosen_coverage.update(represented[chosen['id']])
        self.assertEqual(cursor, len(scored))

    def test_all_three_pair_states_match_every_scored_marginal(self):
        # All 8^3 candidate-coverage assignments, five budgets. High source
        # positions make accidental confusion with pair indices observable.
        pair_bits = (3, 3 << 64, 3 << 128)
        pairs = [{'bits': bits} for bits in pair_bits]
        for assignment in itertools.product(range(8), repeat=3):
            candidates = [
                {'id': ident,
                 'factor_bits': sum(bits for index, bits in enumerate(pair_bits)
                                    if state & (1 << index))}
                for ident, state in zip(('z', 'a', 'm'), assignment)
            ]
            for count in range(5):
                with self.subTest(assignment=assignment, count=count):
                    self.check_scored_marginals(candidates, pairs, count)

    def test_partial_pairs_duplicates_wide_masks_and_zero_gain_fill(self):
        # Duplicate pair descriptions still occupy distinct enumerated indices.
        # A lone source factor must not satisfy a two-factor pair. The full case
        # wins first, after which every remaining scored mask must be zero.
        source_pairs = (3, 3 << 64, 3 << 128)
        candidates = [
            {'id': 'z-partial', 'factor_bits': 1 | (1 << 64) | (1 << 128)},
            {'id': 'a-full', 'factor_bits': sum(source_pairs)},
            {'id': 'm-one', 'factor_bits': source_pairs[1]},
            {'id': 'q-irrelevant', 'factor_bits': 1 << 512},
        ]
        for width in (0, 1, 63, 64, 65, 129, 257):
            pairs = [{'bits': source_pairs[index % 3]} for index in range(width)]
            for count in (0, 1, 2, 4, 5):
                with self.subTest(width=width, count=count):
                    self.check_scored_marginals(candidates, pairs, count)
        self.check_scored_marginals([], [{'bits': 3}], 5)

    def test_public_generator_scores_real_candidate_pairs(self):
        full = xprobe.generate_factor_cases(count=10000)
        for count in (0, 1, 6, 10, 30, 36, 37):
            with self.subTest(count=count):
                self.check_scored_marginals(
                    full['cases'], full['matrix']['uncovered_pairs'], count,
                    public=True)


if __name__ == '__main__':
    unittest.main()
