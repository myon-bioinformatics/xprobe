"""Independent-review regressions: Unicode scalar offsets, IDNA2003 and CLI."""
import itertools
import json
from pathlib import Path
import random
import shutil
import subprocess
import unicodedata as ud

import pytest
import xprobe

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def compare(texts, options=None):
    script = """
const x = require(process.argv[1]);
const {texts, options} = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(texts.map(t => [x.hiddenText(t, options), x.stripHidden(t, options)])));
"""
    run = subprocess.run([NODE, "-e", script, str(ROOT / "xprobe.cjs")],
                         input=json.dumps({"texts": texts, "options": options or {}}),
                         text=True, encoding="utf-8", capture_output=True, timeout=120, check=True)
    results = json.loads(run.stdout)
    assert len(results) == len(texts)  # zip alone can silently skip missing results
    py_options = {"min_severity" if k == "minSeverity" else k: v for k, v in (options or {}).items()}
    for text, (rows, stripped) in zip(texts, results):
        expected = xprobe.hidden_text(text, **py_options)
        assert len(rows) == len(expected), ascii(text)
        for row, py_row in zip(rows, expected):
            row, py_row = dict(row), dict(py_row)
            # The only permitted detail difference is Unicode names for Cf/fillers.
            if row["kind"] == "invisible_format":
                assert row.pop("detail") == "U+%04X" % ord(text[row["start"]])
                py_row.pop("detail")
            assert row == py_row, ascii(text)
        assert stripped == xprobe.strip_hidden(text, **py_options), ascii(text)


def selectors(data):
    return "".join(chr(0xfe00 + b) if b < 16 else chr(0xe0100 + b - 16) for b in data)


def test_unicode_boundaries_positions_emoji_and_controls():
    points = [0, 0x1c, 0x7f, 0x85, 0x9f, 0x300, 0x374, 0x5ff, 0x600,
              0x115f, 0x17b4, 0x180e, 0x200b, 0x202a, 0x202e, 0x2066, 0x2069,
              0xd7ff, 0xd800, 0xdbff, 0xdc00, 0xdfff, 0xe000, 0xf8ff,
              0xfdff, 0xfe00, 0xfe0f, 0xfe10, 0xfeff, 0xffff, 0x10000,
              0x1f3f4, 0x1f3fb, 0x1f600, 0xdffff, 0xe0000, 0xe001f, 0xe0020,
              0xe007e, 0xe007f, 0xe0080, 0xe00ff, 0xe0100, 0xe01ef, 0xe01f0,
              0xeffff, 0xf0000, 0xffffd, 0xffffe, 0xfffff, 0x100000, 0x10fffd, 0x10ffff]
    texts = [prefix + chr(p) + suffix for p in points
             for prefix, suffix in [("", "\ufe00"), ("\U0001f642a", "\u202ex\u202c"), ("\u0430", "a")]]
    texts += ["a\u0374", "\u0430\u00aa", "\u00aa\u200db", "\u3300\u200db",
              "\ud800x\udc00\u202e", "\udc00\ud800x\u200b", "\U00010000\u202e",
              "\U0001f469\u200d\U0001f4bb", "\U0001f469\ufe0f\u200d\U0001f4bb",
              "\U0001f3f4\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f",
              "\U0001f3f4\U000e0067\U000e007f", "\U0001f1ef\U0001f1f5", "1\ufe0f\u20e3"]
    controls = ["\u202e", "\u202c", "\u2066", "\u2069", "\n", "\r", "\x85", "\u2028", "\u2029", "\u200b", "\ufeff"]
    texts += ["\U0001f642" + "".join(t) + "x" for t in itertools.product(controls, repeat=2)]
    texts += ["\u202e\u2066x\u202c\u2069", "\u202e\u2066x\n\u2069", "\u202e\u2066x"]
    compare(texts)
    for options in [{"minSeverity": "high"}, {"minSeverity": "medium"},
                    {"kinds": []}, {"kinds": "bidi_control"}, {"kinds": ["zero_width", "variation_payload"]}]:
        compare(texts, options)


def test_variation_payload_utf8_boundaries_and_seeded_bytes():
    byte_cases = [b"\xef\xbb\xbfX", b"a\xef\xbb\xbfb", b"\xf4\x8f\xbf\xbf", b"\xf4\x90\x80\x80",
                  b"\xed\xa0\x80x", b"\xc0\xafxx", b"\xe0\x80\x80x", b"\xf0\x80\x80\x80",
                  b"\xf0\x9f\x99\x82", b"\xe3\x81\x82x", b"\xf0\x9f\x99", b"\xef\xbb", b"\xc2"]
    rng = random.Random(23)
    byte_cases += [bytes(rng.randrange(256) for _ in range(rng.randrange(4, 25))) for _ in range(1000)]
    texts = [prefix + selectors(data) for data in byte_cases for prefix in ["", "\U0001f642\ufe0f"]]
    texts += [selectors(bytes(range(256)))]
    compare(texts)


def test_idna2003_roundtrip_and_python_whitespace():
    labels = ["xn--zca", "xn--3xa", "xn--pple-43d", "xn--bcher-kva", "xn--r8jz45g", "xn--", "xn--a",
              "XN--PPLE-43D", "xn--abc-", "xn--a_", "xn--xn---83d", "xn--xn--a-8ve", "xn--xn---3u6f",
              "xn--" + "a" * 1025]
    # Encode raw Punycode so invalid IDNA2003 round trips are also exercised.
    labels += ["xn--" + t.encode("punycode").decode("ascii") for t in
               ["p\u0430y", "\u00df", "\u03c2", "a\u200db", "\u00a0", "\ufeff", "\u202e", "\ud800",
                "\u05d0a", "\u05d0", "\U0002f868", "\U0001f600", "a\u00adb", "\u0130", "\u212a"]]
    texts = [f"\U0001f642 https://{label}.p\u0430y.com/path" for label in labels]
    texts += [f"https://{label}\uff0ecom" for label in labels]
    texts += [f"https://p\u0430y{chr(c)}.com" for c in [0, 1, 9, 0x1c, 0x1f, 0x85, 0xa0, 0x200b, 0x202e, 0xfeff]]
    texts += ["https://p\u0430y.com" + chr(c) + "path" for c in [0x1c, 0x1d, 0x1e, 0x1f, 0x85, 0xfeff]]
    texts += ["https://\u4f8b\u3048.\u30c6\u30b9\u30c8/\u0440\u0430\u0443", "https://b\u00fccher.de", "https://[::1]/p\u0430y",
              "https://google.com\u2044@evil.example", "p\u0430y\uff0eexample.com", "https://user@p\u0430y.com?q=\u03c1"]
    compare(texts)


def test_unicode15_name_classification_exhaustively():
    if ud.unidata_version != "15.0.0":
        pytest.skip("Node name tables target the CPython 3.12 Unicode 15 database")
    # Every letter/number with a relevant name prefix, plus each side of a
    # classification boundary. Unlike Script properties this includes Greek
    # numerals and excludes modifier/ordinal characters without a Latin name.
    points = {0, 0x10ffff}
    previous = ""
    scripts = set(xprobe._UNJOINED_SCRIPTS)
    for n in range(0x110000):
        c = chr(n)
        current = xprobe._script(c)
        if current in scripts or previous in scripts:
            if current != previous:
                points.update([max(0, n - 1), n])
            if ud.category(c)[0] in "LN":
                points.add(n)
        previous = current
    # Keep requests bounded while covering all ~110k relevant code points.
    ordered = sorted(points)
    for i in range(0, len(ordered), 5000):
        compare(["a" + chr(n) + "\u0430" for n in ordered[i:i + 5000]])


def test_unicode15_category_boundaries():
    if ud.unidata_version != "15.0.0":
        pytest.skip("Node category tables target the CPython 3.12 Unicode 15 database")
    points, previous = {0, 0x10ffff}, ""
    for n in range(0x110000):
        current = ud.category(chr(n))
        if current != previous:
            points.update([max(0, n - 1), n])
        previous = current
    # Exercise visibility-before-selector, joining, word/URL character classes,
    # and printable representations at both sides of every category transition.
    # Never concatenate explicit surrogate halves into a pair in this transport.
    texts = [text for n in sorted(points) for text in
             [chr(n) + "\ufe00", chr(n) + "\u200da", "a" + chr(n) + "\u0430",
              "https://p\u0430y" + chr(n) + ".com"]]
    for i in range(0, len(texts), 5000):
        compare(texts[i:i + 5000])
