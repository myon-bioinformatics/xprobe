"""Offline follow-up to the pinned two-consumer protocol, with local Git object stores."""
import argparse
import hashlib
import json
import platform
import random
import statistics
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path

from experiment_low_rank_selection import rank_binary_report, xprobe

SEEDS = (0, 1, 7, 42, 99)
METHODS = ("seeded", "greedy", "binary-1-none", "binary-1-frequency", "binary-4-none", "binary-4-frequency")
REVISIONS = {
    "Ironmate": ("size_estimate.py", "f633cd7c37490e5e7958f1393c79a0fa53d4ab97", "1792f7bc97ed7cfa43345212575ddfc09fb577bf"),
    "BrowserTestKit": ("scripts/interaction.py", "89bb12888f7b27926938a2af3e2c9427a40a3d55", "1f3884bc59c86f678d349ab90400f2ac9ee4550a"),
}


def population():
    numbers = [*range(-1, 17), *(2**power + offset for power in (53, 63) for offset in range(-2, 3)), None, "x"]
    cases = []
    for text in xprobe.boundary_cases("text"):
        for n in numbers:
            if n is None:
                factor = "missing"
            elif isinstance(n, str):
                factor = "wrong_type"
            elif n == 2**63:
                factor = "large"
            else:
                factor = "positive" if n > 0 else "negative" if n < 0 else "zero"
            bits = xprobe._factor_bits([*xprobe._text_factors(text["value"]), factor])
            cases.append({"id": f"{text['name']}:{n}", "factor_bits": bits, "number": n})
    return cases, xprobe.case_factor_matrix()


def historical_functions(paths):
    functions, sources = {}, {}
    for name, (path, *revisions) in REVISIONS.items():
        functions[name], sources[name] = [], []
        for revision in revisions:
            source = subprocess.check_output(["git", "-C", str(paths[name]), "show", f"{revision}:{path}"])
            ns = {"__name__": "pinned_consumer", "__file__": path}
            exec(compile(source, path, "exec"), ns)
            functions[name].append(ns["base64_chars" if name == "Ironmate" else "press_point"])
            sources[name].append({"revision": revision, "path": path, "sha256": hashlib.sha256(source).hexdigest()})
    return functions, sources


def defect_inputs(functions, cases):
    failures = {name: set() for name in functions}
    for n in {c["number"] for c in cases if type(c["number"]) is int and c["number"] >= 0}:
        groups, tail = divmod(n, 3)
        probes = [("Ironmate", (n,), 4 * (groups + bool(tail)))]
        if 1 <= n <= 16:
            probes.append(("BrowserTestKit", ({"x": 0, "y": 0, "width": 16, "height": 1},
                                              {"width": n, "height": 1}, 1/16),
                           {"x": 8, "y": 0, "visible_ratio": ((1000*n + 8)//16)/1000}))
        for name, args, expected in probes:
            old, fixed = functions[name]
            if fixed(*args) != expected:
                raise ValueError(f"{name} fixed version disagrees with independent oracle at {n}")
            if old(*args) != expected:
                failures[name].add(n)
    if not all(failures.values()):
        raise ValueError("expected both historical regressions to reproduce")
    return failures


def select(cases, matrix, method, budget, seed):
    if method == "seeded":
        shuffled = list(cases)
        random.Random(seed).shuffle(shuffled)
        return shuffled[:budget], {}
    if method == "greedy":
        return xprobe._greedy_factor_cases(cases, matrix["uncovered_pairs"], budget), {}
    report = {"matrix": matrix, "cases": cases, "candidate_total": len(cases), "exclusions": {}}
    ranked = rank_binary_report(report, method, budget, seed)
    return ranked["cases"], ranked["selection"]


def measure(cases, matrix, bugs, method, budget, seed):
    args = cases, matrix, method, budget, seed
    select(*args)
    cpu, wall = [], []
    for _ in range(3):
        start, cpu_start = time.perf_counter_ns(), time.process_time_ns()
        selected, settings = select(*args)
        cpu.append(time.process_time_ns() - cpu_start)
        wall.append(time.perf_counter_ns() - start)
    tracemalloc.start()
    traced, _ = select(*args)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    ids = [c["id"] for c in selected]
    assert selected == traced and len(set(ids)) == budget
    return {"method": method, "budget": budget, "seed": seed, "ids": ids, "excluded": len(cases)-budget,
            "settings": settings, "covered_pairs": sum(any(c["factor_bits"] & p["bits"] == p["bits"] for c in selected)
                                                      for p in matrix["uncovered_pairs"]),
            "detects": {name: any(c["number"] in values for c in selected) for name, values in bugs.items()},
            "cpu_ns": cpu, "wall_ns": wall, "peak_python_bytes": peak}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ironmate", type=Path)
    parser.add_argument("browser_test_kit", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    cases, matrix = population()
    funcs, sources = historical_functions({"Ironmate": args.ironmate, "BrowserTestKit": args.browser_test_kit})
    bugs = defect_inputs(funcs, cases)
    rows, summary = [], []
    for budget in (10, 30):
        for seed in SEEDS:
            methods = list(METHODS)
            random.Random(budget + seed).shuffle(methods)
            rows.extend(measure(cases, matrix, bugs, m, budget, seed) for m in methods)
        for method in METHODS:
            group = [r for r in rows if r["budget"] == budget and r["method"] == method]
            summary.append({"method": method, "budget": budget,
                            "detections": {name: sum(r["detects"][name] for r in group) for name in bugs},
                            "pair_range": [min(r["covered_pairs"] for r in group), max(r["covered_pairs"] for r in group)],
                            "median_cpu_ns": statistics.median(statistics.median(r["cpu_ns"]) for r in group),
                            "median_peak_bytes": statistics.median(r["peak_python_bytes"] for r in group)})
    args.output.write_text(json.dumps({"protocol_commit": "4ac812aeafa3489d24235453df168593d218fe22",
        "python": sys.version, "platform": platform.platform(), "candidate_count": len(cases),
        "pair_count": len(matrix["uncovered_pairs"]), "sources": sources,
        "defect_triggering_numbers": {k: sorted(v) for k, v in bugs.items()},
        "summary": summary, "rows": rows}, indent=2) + "\n")


if __name__ == "__main__":
    main()
