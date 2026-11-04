"""Compare exact greedy popcount implementations on the built-in factor corpus."""
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import xprobe


def main():
    report = xprobe.generate_factor_cases(count=10000)
    candidates = report['cases']
    pairs = report['matrix']['uncovered_pairs']
    counters = {'binary_string': lambda v: bin(v).count('1'), 'integer': xprobe._factor_popcount}
    samples = {name: [] for name in counters}
    reference = None
    for repetition in range(22):
        order = list(counters) if repetition % 2 else list(reversed(counters))
        for name in order:
            with patch.object(xprobe, '_factor_popcount', counters[name]):
                start = time.perf_counter_ns()
                result = xprobe._greedy_factor_cases(candidates, pairs, 20)
                elapsed = time.perf_counter_ns() - start
            ids = [case['id'] for case in result]
            if reference is None:
                reference = ids
            assert ids == reference
            if repetition:
                samples[name].append(elapsed)
    print(json.dumps({'python': sys.version, 'platform': platform.platform(),
        'candidate_count': len(candidates), 'pair_count': len(pairs), 'budget': 20,
        'input_sha256': hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest(),
        'selected_ids': reference, 'samples_ns': samples,
        'median_ns': {name: statistics.median(values) for name, values in samples.items()},
        'dependencies_added': 0, 'build_time_improvement': None}, indent=2))


if __name__ == '__main__':
    main()
