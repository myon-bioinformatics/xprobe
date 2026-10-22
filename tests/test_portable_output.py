import importlib.util
from pathlib import Path
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
        self.assertEqual(module.select_lines("1 passed\\n2 passed", "Error: root cause", limit=2),
                         ["1 passed", "Error: root cause"])
        self.assertEqual(module.select_lines("1 passed\\n2 passed", "Error: root cause", limit=1),
                         ["Error: root cause"])

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
