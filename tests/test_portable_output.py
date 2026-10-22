import importlib.util
from pathlib import Path
import re
import unittest

spec = importlib.util.spec_from_file_location("portable_output", Path(__file__).resolve().parents[1] / "portable_output.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class PortableOutputTests(unittest.TestCase):
    def test_default_pattern(self):
        self.assertEqual(module.select_lines("hello\n1 passed\n2 skipped", "Error: bad"), ["1 passed", "2 skipped", "Error: bad"])
    def test_limit(self):
        self.assertEqual(module.select_lines("1 passed\n2 passed", limit=1), ["1 passed"])
        self.assertEqual(module.select_lines("1 passed\n2 passed", limit=0), ["1 passed", "2 passed"])
    def test_stderr_not_starved_by_stdout(self):
        self.assertEqual(module.select_lines("1 passed\n2 passed", "Error: root cause", limit=2),
                         ["1 passed", "Error: root cause"])
        self.assertEqual(module.select_lines("1 passed\n2 passed", "Error: root cause", limit=1),
                         ["Error: root cause"])

    def test_stderr_error_after_summary_survives_truncation(self):
        for count, limit in ((25, 20), (19, 20), (0, 1), (25, 1)):
            with self.subTest(stdout_lines=count, limit=limit):
                stdout = "\n".join(f"{number} passed" for number in range(count))
                lines = module.select_lines(stdout, "1 passed\nError: root cause", limit=limit)
                self.assertIn("Error: root cause", lines)
                self.assertLessEqual(len(lines), limit)

    def test_diagnostics_precede_failure_and_success_summaries_in_budget(self):
        stdout = "1 passed\n2 failed\nError: stdout cause"
        stderr = "3 failed\nError: stderr cause\nError: later cause"
        self.assertEqual(module.select_lines(stdout, stderr, limit=2),
                         ["Error: stdout cause", "Error: stderr cause"])
        self.assertEqual(module.select_lines("1 passed\n2 failed\n3 skipped", limit=1),
                         ["2 failed"])
        self.assertEqual(module.select_lines("1 passed\n  1) assertion failed", limit=1),
                         ["  1) assertion failed"])

    def test_non_failure_stderr_keeps_reserved_slot(self):
        self.assertEqual(module.select_lines("1 passed\n2 passed", "3 skipped\n4 skipped", limit=2),
                         ["1 passed", "3 skipped"])

    def test_filter_and_flags_still_control_eligible_lines(self):
        self.assertEqual(module.select_lines("1 passed\n2 passed", "Error: excluded", pattern="passed", limit=1),
                         ["1 passed"])
        self.assertEqual(module.select_lines("1 passed", "error: cause", limit=1, flags=re.IGNORECASE),
                         ["error: cause"])

    def test_unlimited_and_untruncated_output_preserve_order_and_duplicates(self):
        stdout = "1 passed\nError: duplicate"
        stderr = "2 passed\nError: duplicate"
        expected = ["1 passed", "Error: duplicate", "2 passed", "Error: duplicate"]
        self.assertEqual(module.select_lines(stdout, stderr, limit=0), expected)
        self.assertEqual(module.select_lines(stdout, stderr, limit=4), expected)
        self.assertEqual(module.select_lines(stdout, stderr, limit=2),
                         ["Error: duplicate", "Error: duplicate"])

    def test_receipt_keeps_exit_and_timeout_while_selecting_cause(self):
        self.assertEqual(module.result_receipt(124, "1 passed\n2 passed", "1 passed\nError: timeout",
                                               timed_out=True, limit=1),
                         {"exit_code": 124, "timed_out": True, "lines": ["Error: timeout"]})

    def test_exit_code(self):
        self.assertEqual(module.result_receipt(7, "1 failed")["exit_code"], 7)
    def test_invalid(self):
        with self.assertRaises(ValueError):
            module.select_lines(limit=-1)
        with self.assertRaises(ValueError):
            module.select_lines(limit=True)
        with self.assertRaises(TypeError):
            module.result_receipt(True)

if __name__ == "__main__":
    unittest.main()
