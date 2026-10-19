"""xprobe.cjs (Node, CommonJS) finds exactly what xprobe.py finds on a shared corpus."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

import xprobe
import test_xprobe_hidden_text as cases

ROOT = Path(__file__).resolve().parents[1]
# Every field except `detail`, which Python spells with Unicode names that JavaScript lacks.
FIELDS = ("kind", "severity", "start", "end", "length", "codepoints", "decoded", "word", "odd")


def corpus():
    texts = []
    for test in (cases.test_rule_matches, cases.test_ordinary_text_is_quiet, cases.test_legitimate_idn_unicode_and_punycode,
                 cases.test_unicode_outside_authority_is_not_a_host_attack, cases.test_non_idn_authorities_and_malformed_ace_do_not_crash):
        for mark in getattr(test, "pytestmark", []):
            if mark.name == "parametrize":
                texts += [v[0] if isinstance(v, (tuple, list)) else v for v in mark.args[1]]
    texts += [
        "a\u202eb\u202c c\u2066d\nx\u2067y\u2069 z\u202b",
        "say p\u0430yp\u0430l now \\tp\u0430y",
        "\U0001F600" + "".join(chr(0xE0100 + b - 16) if b >= 16 else chr(0xFE00 + b) for b in b"\x0frun!"),
        "x" + "".join(chr(0xE0100 + b - 16) if b >= 16 else chr(0xFE00 + b) for b in b"\xff\xfe\x00\x01"),
        "\U0001F642" + "".join(chr(0xE0100 + b - 16) for b in "\u3053\u3093 curl".encode("utf-8")),
        "\ufeffstart \ufeff mid", "https://xn--pple-43d.com/login and www.\u0440\u0430\u0443\u0440\u0430l.com",
        "https://google.com\u2044@evil.example", "pay\uff0eexample.com", "\U0001F3F4\U000E0067\U000E0062\U000E007F",
    ]
    return [t for t in texts if isinstance(t, str)]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_node_twin_matches_python_on_the_corpus():
    texts = corpus()
    assert len(texts) > 40
    script = ("const x=require(process.argv[1]);let s='';process.stdin.on('data',d=>s+=d).on('end',()=>"
              "process.stdout.write(JSON.stringify(JSON.parse(s).map(t=>[x.hiddenText(t),x.stripHidden(t)]))))")
    run = subprocess.run(["node", "-e", script, str(ROOT / "xprobe.cjs")], input=json.dumps(texts),
                         capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert run.returncode == 0, run.stderr
    results = json.loads(run.stdout)
    assert len(results) == len(texts)
    for text, (node_rows, node_stripped) in zip(texts, results):
        py_rows = xprobe.hidden_text(text)
        project = lambda rows: [{k: r.get(k) for k in FIELDS} for r in rows]
        assert project(node_rows) == project(py_rows), ascii(text)
        assert node_stripped == xprobe.strip_hidden(text), ascii(text)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_node_twin_rules_options_and_cli(tmp_path):
    script = ("const x=require(process.argv[1]);const out={rules:x.hiddenTextRules(),"
              "medium:x.hiddenText('a\\u200bb\\u00ad',{minSeverity:'medium'}).map(r=>r.kind),"
              "only:x.hiddenText('a\\u200bb\\u202e',{kinds:'zero_width'}).map(r=>r.kind)};"
              "try{x.hiddenText('a',{kinds:['nope']})}catch(e){out.err=e.message};process.stdout.write(JSON.stringify(out))")
    out = json.loads(subprocess.run(["node", "-e", script, str(ROOT / "xprobe.cjs")], capture_output=True, text=True,
                                    encoding="utf-8", timeout=60, check=True).stdout)
    assert out["rules"] == xprobe.hidden_text_rules()
    assert out["medium"] == ["zero_width"] and out["only"] == ["zero_width"] and "unknown hidden-text kind" in out["err"]
    (tmp_path / "t.txt").write_text("ok \u202e x", encoding="utf-8")
    cli = subprocess.run(["node", str(ROOT / "xprobe.cjs"), "--hidden-text", str(tmp_path / "t.txt")],
                         capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert cli.returncode == 1 and cli.stdout.isascii() and '"bidi_control"' in cli.stdout
    strip = subprocess.run(["node", str(ROOT / "xprobe.cjs"), "--strip-hidden", "-"], input="a\u200bb",
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert strip.returncode == 0 and strip.stdout == "ab"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_declarations_match_exports():
    import re
    script = "process.stdout.write(JSON.stringify(Object.keys(require(process.argv[1]))))"
    names = json.loads(subprocess.run(["node", "-e", script, str(ROOT / "xprobe.cjs")], capture_output=True,
                                      text=True, timeout=60, check=True).stdout)
    declared = re.findall(r"^export (?:function|const) (\w+)", (ROOT / "xprobe.d.cts").read_text(encoding="utf-8"), re.M)
    assert sorted(set(declared)) == sorted(names)
