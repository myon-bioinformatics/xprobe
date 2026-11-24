"""Stdlib-only runtime checks: the runtime-compatibility lane runs this file with `python -S -m unittest`.

Search, probes, copy-one-file import and text reading, with no pytest or other site-packages.
"""
import ast, json, re, shutil, sys, tempfile, unittest
from pathlib import Path; from unittest.mock import patch

import xprobe
from vendor.cli_args import Command, run_cli, run_command

ROOT = Path(__file__).resolve().parents[1]


class SearchTests(unittest.TestCase):
    def test_literal_coordinates_and_crlf(self):
        rows = xprobe.search_text("α.a .a\r\n日本.a\n", ".a")
        self.assertEqual([(r["line"], r["column"], r["end_column"]) for r in rows],
                         [(1, 2, 4), (1, 5, 7), (2, 3, 5)])

    def test_regex_case_and_zero_width(self):
        self.assertEqual(len(xprobe.search_text("ABC abc", "abc", ignore_case=True)), 2)
        self.assertEqual(xprobe.search_text("abc", "^", regex=True)[0]["match"], "")
        self.assertEqual(xprobe.search_text("a1 b22", r"\d+", regex=True)[1]["match"], "22")

    def test_validation_and_limit(self):
        for limit in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                xprobe.search_text("aaa", "a", max_matches=limit)
        with self.assertRaises(ValueError):
            xprobe.search_text("a", "")
        with self.assertRaises(re.error):
            xprobe.search_text("a", "[", regex=True)
        self.assertEqual(len(xprobe.search_text("aaa", "a", max_matches=2)), 2)

    def test_files_skips_hidden_and_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, data in [("b.txt", b"hit"), ("a.txt", b"hit"),
                               (".secret", b"hit"), ("binary", b"hit\0"),
                               ("bad", b"\xff"), ("large", b"hit" * 10)]:
                (root / name).write_bytes(data)
            (root / ".hidden").mkdir()
            (root / ".hidden" / "file").write_text("hit")
            report = xprobe.search_files(root, "hit", max_bytes=10)
            self.assertEqual([r["path"] for r in report["matches"]], ["a.txt", "b.txt"])
            self.assertEqual({r["reason"] for r in report["skipped"]},
                             {"binary", "decode_error", "too_large"})
            self.assertEqual(report["errors"], [])
            self.assertEqual(len(xprobe.search_files(root, "hit", include_hidden=True,
                                                     max_bytes=10)["matches"]), 4)

    def test_exact_limit_is_not_truncated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a"
            path.write_text("hit hit")
            self.assertFalse(xprobe.search_files(path, "hit", max_matches=2)["truncated"])
            self.assertTrue(xprobe.search_files(path, "hit", max_matches=1)["truncated"])
            self.assertEqual(xprobe.search_files(path, "absent")["matches"], [])

    def test_missing_and_read_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(FileNotFoundError):
                xprobe.search_files(root / "missing", "hit")
            (root / "a").write_text("hit")
            with patch.object(Path, "open", side_effect=PermissionError):
                report = xprobe.search_files(root, "hit")
            self.assertEqual(report["errors"], [{"path": "a", "reason": "PermissionError"}])

    def test_symlink_not_followed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target"
            target.write_text("hit")
            link = root / "link"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("symlink creation unavailable")
            report = xprobe.search_files(root, "hit")
            self.assertEqual([r["path"] for r in report["matches"]], ["target"])
            self.assertEqual(report["skipped"], [{"path": "link", "reason": "non_regular"}])
            with self.assertRaises(ValueError):
                xprobe.search_files(link, "hit")


class ProbeTests(unittest.TestCase):
    def test_presets_fresh_and_explicit(self):
        first = xprobe.boundary_cases()
        first[0]["value"] = "changed"
        self.assertEqual(xprobe.boundary_cases()[0]["value"], "")
        self.assertIn("nul", [r["name"] for r in first])
        self.assertEqual(xprobe.boundary_cases("number")[3]["value"], 2 ** 63)
        with self.assertRaises(ValueError):
            xprobe.boundary_cases("unknown")

    def test_success_failure_and_expected_exception(self):
        report = xprobe.run_cases(int, [
            {"name": "valid", "value": "1", "expected": 1},
            {"name": "wrong", "value": "2", "expected": 1},
            {"name": "invalid", "value": "x", "raises": ValueError},
            {"name": "unexpected", "value": None, "expected": 0},
            {"name": "missing_exception", "value": "1", "raises": ValueError}])
        self.assertFalse(report["passed"])
        self.assertEqual([r["passed"] for r in report["results"]],
                         [True, False, True, False, False])
        self.assertEqual(report["results"][3]["error_type"], "TypeError")

    def test_all_cases_validated_before_execution(self):
        calls = []
        with self.assertRaises(ValueError):
            xprobe.run_cases(calls.append, [{"name": "ok", "value": 1, "expected": None},
                                           {"name": "bad", "value": 1}])
        self.assertEqual(calls, [])
        for case in ({"name": "a", "value": 1, "raises": SystemExit},
                     {"name": "a", "value": 1, "raises": "ValueError"},
                     {"name": "", "value": 1, "expected": 1}):
            with self.assertRaises(ValueError):
                xprobe.run_cases(int, [case])

    def test_base_exception_propagates(self):
        def stop(value):
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            xprobe.run_cases(stop, [{"name": "stop", "value": 1, "expected": None}])


class IntegrationTests(unittest.TestCase):
    def test_copy_one_file_import_and_no_cli_on_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vendor_probe.py"
            shutil.copy(ROOT / "xprobe.py", path)
            proc = run_command(Command((sys.executable, "-B", "-c",
                "import vendor_probe as p; assert p.search_text('hit', 'hit'); "
                "assert p.run_cases(int, [{'name':'n','value':'1','expected':1}])['passed']")),
                cwd=tmp, timeout=20)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout, "")

    @unittest.skipUnless(hasattr(sys, "stdlib_module_names"), "stdlib inventory requires Python 3.10+")
    def test_stdlib_imports(self):
        tree = ast.parse((ROOT / "xprobe.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(alias.name.split(".")[0], sys.stdlib_module_names)
            elif isinstance(node, ast.ImportFrom):
                self.assertIn(node.module.split(".")[0], sys.stdlib_module_names)

    def test_cli_match_no_match_and_invalid_regex(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a"
            path.write_text("hit")
            def run(pattern, *extra):
                return run_cli(ROOT / "scripts/xprobe_cli.py", pattern, path, *extra, cwd=tmp, timeout=20)
            hit = run("hit")
            self.assertEqual(hit.returncode, 0, hit.stderr)
            self.assertEqual(json.loads(hit.stdout)["matches"][0]["path"], "a")
            self.assertEqual(run("absent").returncode, 1)
            invalid = run("[", "--regex")
            self.assertEqual(invalid.returncode, 2)
            self.assertEqual(invalid.stdout, "")
            failure = json.loads(invalid.stderr)
            self.assertEqual(failure["code"], "regex")
            self.assertFalse(failure["ok"])
            self.assertNotIn("[", failure.get("message", ""))


# ──── text reading: readable_text, mojibake restoration, decode_text ────

class TextRuntimeTests(unittest.TestCase):
    def test_supported_encodings(self):
        text = '名前,金額\nこんにちは,123\nカタカナ,456\n'
        for encoding in ('utf-8', 'cp932', 'euc_jp', 'iso2022_jp', 'utf-16', 'utf-32'):
            with self.subTest(encoding=encoding):
                report = xprobe.readable_text(text.encode(encoding))
                self.assertEqual(report['text'], text)

    def test_partial_and_mixed_reading(self):
        broken = '縺薙ｓ縺ｫ縺｡縺ｯ'
        raw = ('正常' + broken + '正常�').encode() + b'\xff'
        report = xprobe.readable_text(raw)
        self.assertEqual(report['text'], '正常こんにちは正常�\\xff')
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(bytes.fromhex(report['source_hex']), raw)
        self.assertEqual(report['decoded_text'], '正常' + broken + '正常�\\xff')

    def test_partial_mojibake_has_original_span(self):
        for broken, expected in (('ãƒ†ã‚¹ãƒˆã', 'テストã'),
                                 ('縺薙ｓ縺ｫ縺｡縺ｯ縺', 'こんにちは縺'),
                                 ('ƒeƒXƒg\x81', 'テスト\x81')):
            with self.subTest(broken=broken):
                report = xprobe.readable_text(broken.encode())
                self.assertEqual(report['text'], expected)
                self.assertEqual(report['restoration_status'], 'partial')
                self.assertEqual(report['status'], 'partial')
                pending = [f for f in report['findings'] if f['status'] == 'unresolved']
                self.assertTrue(pending)
                for finding in pending:
                    self.assertEqual(finding['text'], broken[finding['start']:finding['end']])
                    self.assertEqual(finding['text'], finding['restored'])

    def test_roundtrip_and_false_positives(self):
        original = '一日'
        broken = original.encode().decode('cp1252')
        self.assertEqual(xprobe.restore_mojibake(broken), original)
        for text in ('正常な日本語', 'étude élève São Paulo café', '繧カタカナ'):
            self.assertEqual(xprobe.restore_mojibake(text), text)
            self.assertEqual(xprobe.mojibake_text(text), [])
        # CP932 has duplicate encodings; canonical direction varies by runtime.
        raw = next(raw for raw in (b'\xed\x40', b'\xfa\x5c')
                   if raw.decode('cp932').encode('cp932') != raw)
        report = xprobe.decode_text(raw)
        self.assertFalse(report['roundtrip'])
        self.assertEqual(bytes.fromhex(report['source_hex']), raw)
        self.assertTrue(report['warnings'])
