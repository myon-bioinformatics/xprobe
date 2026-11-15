"""Fleet contracts through the parent's shared checks (vendor/fleet_check.py): locks, pins, Node entry,
the Python runtime floor and the benchmark guard."""
import json, tomllib, unittest

import pytest
import yaml

from vendor import fleet_check as fleet

ROOT = fleet.repo_root(__file__)
PARENT_WORKFLOW_PIN = "9e3da7ae1846e9604ebc24bb5178f7de094a4e77"
ACCEPTED = {
    "vendor/py_launch.cjs": "384f5dd532076062f7833038764e9a62322c387c",
    "vendor/fleet_check.py": "6c29503cf17eda856766ddfdf4d66a5b0965a8b1",
}
TOOL, ENV_VAR = "xprobe.py", "XPROBE_PYTHON"
CASES = [{"id": "help", "args": ["--help"], "rc": 0}, {"id": "bogus", "args": ["--bogus"], "rc": 2}, {"id": "hidden-rules", "args": ["--hidden-rules"], "rc": 0}, {"id": "hidden-text", "args": ["--hidden-text", "--root", "LICENSE"], "rc": 0}, {"id": "strip-missing", "args": ["--strip-hidden", "no-such-file"], "rc": 2}]
needs_node = pytest.mark.skipif(fleet.node() is None, reason="Node 26+ not available (set NODE)")


def test_vendor_lock_matches_checked_in_bytes_and_accepted_commits():
    rows = fleet.check_lock(ROOT, commits=ACCEPTED)
    launcher = rows["vendor/py_launch.cjs"]
    assert (launcher["repository"], launcher["source"]) == (fleet.PARENT, "py_launch.cjs")


def test_parent_workflow_references_use_reviewed_rollout_commit():
    assert set(fleet.parent_refs(ROOT, skip=(".vendor-sync-tools",))) == {PARENT_WORKFLOW_PIN}


def test_no_per_tool_wrapper_and_readme_documents_the_direct_command():
    assert not (ROOT / "xprobe.cjs").exists()
    assert not (ROOT / "xprobe.d.cts").exists()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"node vendor/py_launch.cjs --env-var {ENV_VAR} -- {TOOL}" in readme
    pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert pkg["engines"]["node"] == ">=26"


@needs_node
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_node_matches_python(case):
    via_node, via_python = fleet.node_parity(ROOT, TOOL, ENV_VAR, *case["args"])
    assert via_python[0] == case["rc"]
    assert via_node == via_python


@needs_node
def test_vendored_launcher_keeps_its_contract():
    fleet.launcher_contract(ROOT, ENV_VAR)


# The runtime floor: pyproject, uv.lock and the stdlib runtime-compatibility lane agree.
def test_runtime_metadata_and_lock_agree():
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    lock = tomllib.loads((ROOT / 'uv.lock').read_text(encoding='utf-8'))
    assert project['project']['requires-python'] == '>=3.11'
    assert lock['requires-python'] == project['project']['requires-python']


def test_stdlib_runtime_matrix_covers_supported_versions():
    workflow = yaml.safe_load((ROOT / '.github/workflows/runtime-compatibility.yml').read_text(encoding='utf-8'))
    job = workflow['jobs']['runtime']
    assert job['strategy']['matrix']['python'] == ['3.11', '3.12', '3.13', '3.14', '3.15']
    commands = '\n'.join(step.get('run', '') for step in job['steps'])
    assert 'python -S -m unittest discover -s tests -p test_xprobe.py -v' in commands


class BenchmarkParityTests(unittest.TestCase):
    """Benchmark ID checks must run even with Python optimization enabled."""

    def run_benchmark(self, optimized, mismatch):
        selection = ("side_effect=itertools.cycle([[{'id': 'expected'}], [{'id': 'different'}]])"
                     if mismatch else "return_value=[{'id': 'expected'}]")
        patch = ("import itertools\n"
                 "g['xprobe'].generate_factor_cases = mock.Mock(return_value={'cases': [], 'matrix': {'uncovered_pairs': []}})\n"
                 f"g['xprobe']._greedy_factor_cases = mock.Mock({selection})")
        return fleet.run_main(ROOT, "scripts/benchmark_factor_popcount.py", patch, optimized=optimized, timeout=30)

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
