#!/usr/bin/env python3
"""Stdlib-only experimental binary rank-one residual model; no public API changes."""
import argparse
import hashlib
import json
import math
import platform
import random
import statistics
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import xprobe
from benchmark_factor_selection import pair_coverage, consumer_check

BUDGETS = (0, 1, 6, 10, 12, 18, 24, 30, 36)
SEEDS = (0, 1, 7, 42, 99)
METHODS = ('seeded', 'greedy') + tuple(
    'binary-%d-%s' % (rank, scale) for rank in (1, 2, 4, 8)
    for scale in ('none', 'frequency'))


def approximate(candidates, matrix, rank, seed, scale):
    """Fit signed binary outer products to weighted case x target-pair incidence.

    Alternating sign updates (16 fixed sweeps) followed by least-squares scalar
    calibration and residual deflation. This is a heuristic, not SVD/LittleBit.
    Zero residual components are harmless; fitted rank can be lower than rank.
    """
    pairs = matrix['uncovered_pairs']
    exact = [[float(c['factor_bits'] & p['bits'] == p['bits']) for p in pairs]
             for c in candidates]
    if not candidates or not pairs:
        return exact, [], 0.0
    weights = [1 / math.sqrt(max(1, sum(row[j] for row in exact)))
               if scale == 'frequency' else 1.0 for j in range(len(pairs))]
    residual = [[v * weights[j] for j, v in enumerate(row)] for row in exact]
    fitted = [[0.0] * len(pairs) for _ in candidates]
    rng = random.Random(seed)
    coefficients = []
    for _ in range(rank):
        right = [rng.choice((-1, 1)) for _ in pairs]
        for _ in range(16):
            left = [1 if sum(a*b for a, b in zip(row, right)) >= 0 else -1
                    for row in residual]
            right = [1 if sum(residual[i][j] * left[i] for i in range(len(left))) >= 0
                     else -1 for j in range(len(pairs))]
        alpha = sum(residual[i][j] * left[i] * right[j]
                    for i in range(len(left)) for j in range(len(right))) / (len(left)*len(right))
        coefficients.append(alpha)
        for i in range(len(left)):
            for j in range(len(right)):
                value = alpha * left[i] * right[j]
                residual[i][j] -= value
                fitted[i][j] += value
    error = sum(v*v for row in residual for v in row)
    # Undo column scaling; clip only ranking weights, never oracle values.
    scores = [[max(0.0, min(1.0, v / weights[j])) for j, v in enumerate(row)]
              for row in fitted]
    return scores, coefficients, error


def generate(method, budget, seed):
    if method in ('seeded', 'greedy'):
        return xprobe.generate_factor_cases(selection=method, count=budget, seed=seed)
    _, rank, scale = method.split('-')
    # Reuse the exact candidate generator and matrix schema; stable IDs remove
    # the source shuffle before fitting. No new values or target expectations.
    report = xprobe.generate_factor_cases(count=10000, seed=seed)
    candidates = sorted(report['cases'], key=lambda c: c['id'])
    scores, coefficients, error = approximate(candidates, report['matrix'], int(rank), seed, scale)
    pairs = report['matrix']['uncovered_pairs']
    remaining, selected, covered = list(range(len(candidates))), [], set()
    while remaining and len(selected) < budget:
        best = max(remaining, key=lambda i: sum(value for j, value in enumerate(scores[i]) if j not in covered))
        remaining.remove(best)
        selected.append(candidates[best])
        covered.update(j for j, p in enumerate(pairs)
                       if candidates[best]['factor_bits'] & p['bits'] == p['bits'])
    report.update(cases=selected, selected_count=len(selected),
                  excluded_count=report['candidate_total']-len(selected))
    report['exclusions']['limit'] = len(candidates)-len(selected)
    report['selection'] = dict(method=method, rank=int(rank), seed=seed,
        scale=scale, sweeps=16, coefficients=coefficients, weighted_squared_error=error,
        approximation_excluded=len(remaining), tie_break='stable_id')
    # approximation_excluded describes the SAME omitted eligible candidates as
    # exclusions.limit (not additive). Ranking prunes only at the final budget.
    return report


def historical(cases):
    """External Ironmate base64_chars float-ceil regression adapter.

    Exact source bodies/provenance and standalone old/fixed replay are retained
    in consumer-base64.json. The byte-length metadata argument maps to number;
    text is intentionally irrelevant for this API. No image allocation.
    """
    ids = []
    checked = []
    for c in cases:
        n = c['value']['number']
        if type(n) is not int or n < 0:
            continue
        expected = 4 * ((n + 2) // 3)
        observed = 4 * math.ceil(n / 3)
        checked.append(c['id'])
        if observed != expected:
            ids.append(c['id'])
    return dict(target='Ironmate size_estimate.base64_chars', adapter='number -> byte length; text unused',
                valid_checked_ids=checked, detecting_ids=ids, detected=bool(ids))


def worker(method, budget, seed):
    generate(method, budget, seed)
    wall, cpu = [], []
    for _ in range(3):
        w, c = time.perf_counter_ns(), time.process_time_ns()
        generate(method, budget, seed)
        cpu.append(time.process_time_ns()-c)
        wall.append(time.perf_counter_ns()-w)
    tracemalloc.start()
    report = generate(method, budget, seed)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    import resource
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return dict(method=method, budget=budget, seed=seed,
        candidate_total=report['candidate_total'], selected_count=len(report['cases']),
        excluded_count=report['excluded_count'], exclusions=report['exclusions'],
        approximation_excluded=report.get('selection', {}).get('approximation_excluded', 0),
        selection=report.get('selection'), selected_ids=[c['id'] for c in report['cases']],
        covered_pairs=pair_coverage(report), target_pairs=len(report['matrix']['uncovered_pairs']),
        wall_ns_samples=wall, cpu_ns_samples=cpu,
        wall_ns_median=statistics.median(wall), cpu_ns_median=statistics.median(cpu),
        tracemalloc_peak_bytes=peak, process_peak_rss_bytes=rss*(1 if sys.platform=='darwin' else 1024),
        consumer=consumer_check(report['cases']), historical=historical(report['cases']))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--worker', nargs=3)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    if a.worker:
        m, b, s = a.worker
        print(json.dumps(worker(m, int(b), int(s))))
        return
    if a.output is None:
        p.error('--output required')
    rows = []
    for b in BUDGETS:
        for s in SEEDS:
            methods = list(METHODS)
            random.Random(s+b).shuffle(methods)
            for m in methods:
                result = subprocess.run([sys.executable, '-S', __file__, '--worker', m, str(b), str(s)],
                                        capture_output=True, text=True, check=True, timeout=60)
                rows.append(json.loads(result.stdout))
    root = Path(__file__).resolve().parents[1]
    report = dict(schema='xprobe.low-rank-experiment.v1', python=sys.version,
        platform=platform.platform(), base_revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        memory_notes='Separate traced generation; RSS is whole-worker high-water, not incremental ranking RSS.',
        timings='3 individual warmed full-generation calls; excludes imports, tracing and oracles',
        rows=rows)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')

if __name__ == '__main__':
    main()
