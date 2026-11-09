"""Benchmark ID checks must run even with Python optimization enabled."""
import json, subprocess, sys, unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark_factor_popcount.py"


class BenchmarkParityTests(unittest.TestCase):
    def run_benchmark(self, optimized, mismatch):
        selection = (
            "side_effect=cycle([[{'id': 'expected'}], [{'id': 'different'}]])"
            if mismatch else "return_value=[{'id': 'expected'}]"
        )
        source = f"""
from itertools import cycle
import runpy
from unittest.mock import patch

benchmark = runpy.run_path({str(SCRIPT)!r})
report = {{'cases': [], 'matrix': {{'uncovered_pairs': []}}}}
with patch.object(benchmark['xprobe'], 'generate_factor_cases', return_value=report), \\
     patch.object(benchmark['xprobe'], '_greedy_factor_cases', {selection}):
    benchmark['main']()
"""
        return subprocess.run(
            [sys.executable, "-S", *(["-O"] if optimized else []), "-c", source],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )

    def test_mismatch_exits_without_publishing_measurements(self):
        for optimized in (False, True):
            with self.subTest(optimized=optimized):
                result = self.run_benchmark(optimized, mismatch=True)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertIn("Factor selection ID mismatch: binary_string", result.stderr)
                self.assertIn("repetition=0", result.stderr)

    def test_matching_results_still_publish_measurements(self):
        for optimized in (False, True):
            with self.subTest(optimized=optimized):
                result = self.run_benchmark(optimized, mismatch=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual(report["selected_ids"], ["expected"])
                for samples in report["samples_ns"].values():
                    self.assertEqual(len(samples), 21)


if __name__ == "__main__":
    unittest.main()
