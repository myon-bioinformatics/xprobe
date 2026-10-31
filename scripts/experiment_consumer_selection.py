#!/usr/bin/env python3
"""Opt-in historical RuleBook replay and larger-product selection benchmark."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import itertools
import json
import platform
import random
import statistics
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import xprobe
from binary_selection_model import approximate

METHODS = ('seeded', 'greedy') + tuple(f'binary-{r}-{s}' for r in (1, 2, 4, 8) for s in ('none', 'frequency'))
SEEDS = (0, 1, 7, 42, 99)
REPLACEMENTS = ('code', r'\1', r'\g<0>', r'\t', r'\n', r'\q', '日本', 'r42')
CONTEXTS = ('{}', '({})', '{} {}', 'prefix {} suffix')


def population(size):
    """128/512 unique concrete inputs; no duplicated IDs or replicated rows."""
    if size not in (128, 512):
        raise ValueError("size must be 128 or 512")
    phrases = size // 64
    axes = (8, 4, 2, phrases)
    offsets = (0, 8, 12, 14)
    cases = []
    for r, c, d, p in itertools.product(*(range(n) for n in axes)):
        phrase = f'alpha{p} beta{p}'
        replacement = REPLACEMENTS[r]
        # Decode exercises literal long strings; encode exercises literal shorts.
        long, short = (phrase, replacement) if d == 0 else (replacement, phrase)
        source = long if d == 0 else short
        target = short if d == 0 else long
        template = CONTEXTS[c]
        cases.append(dict(id=f'r{r}-c{c}-d{d}-p{p:02}',
            factor_bits=sum(1 << (o+i) for o, i in zip(offsets, (r,c,d,p))),
            value=dict(long=long, short=short, direction=d,
                       text=template.format(source, source),
                       expected=template.format(target, target))))
    pairs = []
    for a, b in itertools.combinations(range(4), 2):
        for i in range(axes[a]):
            for j in range(axes[b]):
                pairs.append(dict(bits=(1 << (offsets[a]+i)) | (1 << (offsets[b]+j))))
    return sorted(cases, key=lambda c:c['id']), {'uncovered_pairs': pairs}


def select(cases, matrix, method, budget, seed):
    if method == 'seeded':
        shuffled = list(cases)
        random.Random(seed).shuffle(shuffled)
        return shuffled[:budget], {}
    if method == 'greedy':
        return xprobe._greedy_factor_cases(cases, matrix['uncovered_pairs'], budget), {}
    _, rank, scale = method.split('-')
    scores, coefficients, error = approximate(cases, matrix, int(rank), seed, scale)
    remaining, chosen, covered = list(range(len(cases))), [], set()
    while remaining and len(chosen) < budget:
        best = max(remaining, key=lambda i:sum(v for j,v in enumerate(scores[i]) if j not in covered))
        remaining.remove(best)
        chosen.append(cases[best])
        covered.update(j for j,p in enumerate(matrix['uncovered_pairs']) if cases[best]['factor_bits'] & p['bits'] == p['bits'])
    return chosen, dict(rank=int(rank), scale=scale, sweeps=16, coefficients=coefficients,
                        weighted_squared_error=error)


def load_consumer(kind):
    path = ROOT / 'tests' / 'fixtures' / f'rulebook-{kind}.py'
    name = f'historical_rulebook_{kind}'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def observe(module, value):
    book = module.RuleBook(rules=[module.Rule('fixture', value['long'], value['short'])])
    try:
        result = (book.encode_with_rules if value['direction'] == 0 else book.decode_with_rules)(value['text'])
        return dict(output=result, matches_expected=result == value['expected'])
    except Exception as error:
        return dict(error=type(error).__name__, message=str(error), matches_expected=False)


def replay(cases):
    old, fixed = load_consumer('old'), load_consumer('fixed')
    rows = []
    for case in cases:
        value = case['value']
        before, after = observe(old, value), observe(fixed, value)
        if not after['matches_expected']:
            raise AssertionError((case['id'], after, value))
        rows.append(dict(id=case['id'], value=value, old=before, fixed=after))
    return rows


def worker(size, method, budget, seed):
    cases, matrix = population(size)
    select(cases, matrix, method, budget, seed)
    samples = []
    for _ in range(3):
        start = time.process_time_ns()
        selected, metadata = select(cases, matrix, method, budget, seed)
        samples.append(time.process_time_ns()-start)
    tracemalloc.start()
    select(cases, matrix, method, budget, seed)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024)
    except ImportError:
        rss = None  # Windows: unavailable, never reported as zero
    observations = replay(selected)
    detecting = [r['id'] for r in observations if not r['old']['matches_expected']]
    covered = sum(any(c['factor_bits'] & p['bits'] == p['bits'] for c in selected) for p in matrix['uncovered_pairs'])
    return dict(size=size, method=method, budget=budget, seed=seed,
        selected_ids=[c['id'] for c in selected], detecting_ids=detecting,
        historical_defects_detected=int(bool(detecting)), historical_defects_total=1,
        failing_input_count=len(detecting), selected_input_count=len(selected),
        covered_pairs=covered, target_pairs=len(matrix['uncovered_pairs']),
        cpu_ns_samples=samples, cpu_ns_median=statistics.median(samples),
        tracemalloc_peak_bytes=peak, worker_peak_rss_bytes=rss,
        exact_eligibility_excluded=0, budget_excluded=size-len(selected),
        approximation_prepruned=0,
        approximation_omitted_ids=[c['id'] for c in cases if c not in selected] if method.startswith('binary') else [],
        approximation_metadata=metadata)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--jobs', type=int, default=1, choices=range(1, 9))
    p.add_argument('--worker', nargs=4)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    if a.worker:
        n,m,b,s = a.worker
        print(json.dumps(worker(int(n),m,int(b),int(s))))
        return
    if not a.output:
        p.error('--output required')
    jobs = []
    for n in (128,512):
        for b in (0,1,10,32,n):
            for s in SEEDS:
                methods = list(METHODS)
                random.Random(n+b+s).shuffle(methods)
                for m in methods:
                    jobs.append((n,m,b,s))
    def run(job):
        n,m,b,s = job
        r = subprocess.run([sys.executable,'-S',__file__,'--worker',str(n),m,str(b),str(s)], capture_output=True,text=True,check=True,timeout=180)
        return json.loads(r.stdout)
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        rows = list(pool.map(run, jobs))
    hashes = {str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in (Path(__file__), ROOT/'scripts/binary_selection_model.py', ROOT/'xprobe.py', ROOT/'tests/fixtures/rulebook-old.py', ROOT/'tests/fixtures/rulebook-fixed.py')}
    data = dict(schema='xprobe.consumer-selection.v1', concurrent_workers=a.jobs, python=sys.version, platform=platform.platform(), source_sha256=hashes,
        rows=rows, replay={str(n):replay(population(n)[0]) for n in (128,512)})
    a.output.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')

if __name__ == '__main__':
    main()
