"""New reading contracts exercised under python -S on every runtime version."""
import unittest
import xprobe


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


if __name__ == '__main__':
    unittest.main()
