#!/usr/bin/env python3
"""Reproduce the finite factor-selection experiment using only the stdlib.

Each method/budget/seed runs in a fresh process. Timings exclude imports, JSON,
coverage/oracles and tracemalloc. Memory is measured separately in that worker.
"""
import argparse
import json
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import xprobe

BUDGETS = (0, 1, 6, 10, 12, 18, 24, 30, 36)
SEEDS = (0, 1, 7, 42, 99)


def pair_coverage(report):
    return sum(any(case['factor_bits'] & pair['bits'] == pair['bits']
                   for case in report['cases'])
               for pair in report['matrix']['uncovered_pairs'])


def search_oracle(value):
    """Independent literal-x count oracle for the real search_text consumer."""
    limit = value['number']
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        return ('error', 'ValueError')
    return ('count', min(limit, sum(line.count('x')
                                    for line in value['text'].splitlines())))


def search_observation(value):
    try:
        return ('count', len(xprobe.search_text(value['text'], 'x',
                                               max_matches=value['number'])))
    except ValueError:
        return ('error', 'ValueError')


def injected_fault_detection(cases):
    """Controlled off-by-one cap mutation of a real API, not a historical bug."""
    detected = []
    for case in cases:
        value = case['value']
        limit = value['number']
        mutated = dict(value)
        if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0:
            mutated['number'] = limit + 1
        if search_observation(mutated) != search_oracle(value):
            detected.append(case['id'])
    return {'mutation': 'positive max_matches passed as max_matches + 1',
            'detected': bool(detected), 'detecting_ids': detected}


def consumer_check(cases):
    # These are actual consumer checks, not historical bug detection claims.
    mismatches = [case['id'] for case in cases
                  if search_observation(case['value']) != search_oracle(case['value'])]
    return {'target': 'xprobe.search_text(literal x, max_matches=number)',
            'checks': len(cases), 'mismatches': mismatches,
            'historical_regressions_detected': None,
            'injected_fault': injected_fault_detection(cases)}


def measure(method, budget, seed, repeats, batch):
    def generate():
        return xprobe.generate_factor_cases(selection=method, count=budget, seed=seed)

    generate()  # warm-up; timed samples measure complete report generation
    wall, cpu = [], []
    for _ in range(repeats):
        start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
        for _ in range(batch):
            generate()
        cpu.append((time.process_time_ns() - start_cpu) / batch)
        wall.append((time.perf_counter_ns() - start_wall) / batch)
    tracemalloc.start()
    report = generate()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss_bytes = rss if sys.platform == 'darwin' else rss * 1024
    except ImportError:
        rss_bytes = None
    covered = pair_coverage(report)
    total = len(report['matrix']['uncovered_pairs'])
    return {'method': method, 'budget': budget, 'seed': seed,
            'selected_ids': [case['id'] for case in report['cases']],
            'candidate_total': report['candidate_total'],
            'selected_count': report['selected_count'],
            'exclusions': {**report['exclusions'], 'approximation': 0},
            'covered_pairs': covered, 'target_pairs': total,
            'pair_coverage': covered / total if total else 1.0,
            'wall_ns_per_call_samples': wall, 'cpu_ns_per_call_samples': cpu,
            'wall_ns_per_call_median': statistics.median(wall),
            'cpu_ns_per_call_median': statistics.median(cpu),
            'tracemalloc_peak_bytes': peak, 'process_peak_rss_bytes': rss_bytes,
            'consumer': consumer_check(report['cases'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--batch', type=int, default=25)
    parser.add_argument('--worker', nargs=3, metavar=('METHOD', 'BUDGET', 'SEED'))
    args = parser.parse_args()
    if args.repeats < 1 or args.batch < 1:
        parser.error('repeats and batch must be positive')
    if args.worker:
        method, budget, seed = args.worker
        print(json.dumps(measure(method, int(budget), int(seed), args.repeats, args.batch)))
        return
    if args.output is None:
        parser.error('--output is required')
    rows = []
    for budget in BUDGETS:
        for seed in SEEDS:
            # Alternate execution order to reduce systematic order effects.
            methods = ('seeded', 'greedy') if seed % 2 else ('greedy', 'seeded')
            for method in methods:
                result = subprocess.run(
                    [sys.executable, '-S', str(Path(__file__).resolve()),
                     '--worker', method, str(budget), str(seed),
                     '--repeats', str(args.repeats), '--batch', str(args.batch)],
                    capture_output=True, text=True, check=True, timeout=60)
                rows.append(json.loads(result.stdout))
    root = Path(__file__).resolve().parents[1]
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root,
                              capture_output=True, text=True, check=True).stdout.strip()
    dirty = bool(subprocess.run(['git', 'status', '--porcelain'], cwd=root,
                                capture_output=True, text=True, check=True).stdout)
    report = {'schema': 'xprobe.factor-selection-benchmark.v1',
              'producer_revision': revision, 'worktree_dirty': dirty,
              'python': sys.version, 'platform': platform.platform(),
              'repeats': args.repeats, 'batch': args.batch,
              'memory_notes': 'tracemalloc: separate generation; RSS: whole worker high-water including imports and traced generation; not incremental selection RSS',
              'rows': rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # One JSON row per line keeps the checked-in raw experiment compact.
    header = json.dumps({k: v for k, v in report.items() if k != 'rows'}, indent=2)
    encoded = header[:-2] + ',\n  \"rows\": [\n'
    encoded += ',\n'.join('    ' + json.dumps(row) for row in rows) + '\n  ]\n}\n'
    args.output.write_text(encoded, encoding='utf-8')


if __name__ == '__main__':
    main()
