"""Emoji sequences, names, reverse lookup and inventory; mirrored against Node's Unicode regex."""
import json
import shutil
import subprocess
import unicodedata
from pathlib import Path

import pytest

import xprobe

ROOT = Path(__file__).resolve().parent
CORPUS = (ROOT / "fixtures" / "emoji_corpus.txt").read_text(encoding="utf-8")


def _node(script, data):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    probe = subprocess.run([node, "-e", "new RegExp('\\\\p{RGI_Emoji}', 'v')"], capture_output=True)
    if probe.returncode:
        pytest.skip("this Node has no RegExp v flag (Node 20+)")
    done = subprocess.run([node, "-e", script], input=data, capture_output=True, text=True, encoding="utf-8",
                          check=True)
    return json.loads(done.stdout)


def test_sequences_kinds_and_names():
    rows = xprobe.emoji_sequences(CORPUS)
    kinds = {row["emoji"]: row["kind"] for row in rows}
    assert kinds["\U0001F468\u200d\U0001F469\u200d\U0001F467\u200d\U0001F466"] == "zwj"
    assert kinds["\U0001F44D\U0001F3FB"] == "modified"
    assert kinds["\U0001F1EF\U0001F1F5"] == "flag" and kinds["\U0001F1FA\U0001F1F8"] == "flag"
    assert kinds["#\ufe0f\u20e3"] == "keycap"
    assert kinds["\U0001F3F4\U000E0067\U000E0062\U000E0073\U000E0063\U000E0074\U000E007F"] == "tag"
    assert "\u00a9" not in kinds and "\u00a9\ufe0f" in kinds  # (c) is text unless VS16 follows
    assert "1" not in kinds and "#" not in kinds
    names = {row["emoji"]: row["name"] for row in rows}
    assert names["\U0001F469\U0001F3FD\u200d\U0001F4BB"].startswith("WOMAN + EMOJI MODIFIER FITZPATRICK TYPE-4")
    assert names["\U0001F1EF\U0001F1F5"] == "FLAG JP" and names["#\ufe0f\u20e3"] == "KEYCAP #"
    assert names["\U0001F3F4\U000E0067\U000E0062\U000E0073\U000E0063\U000E0074\U000E007F"] == "FLAG gbsct"
    hearts = [row for row in rows if row["identity"] == "\u2764"]
    assert [h["emoji"] for h in hearts] == ["\u2764\ufe0f", "\u2764"]
    first = rows[0]
    assert CORPUS[first["start"]:first["end"]] == first["emoji"] == "\U0001F3E0"
    assert xprobe.emoji_identity("\u2764\ufe0f") == "\u2764"
    with pytest.raises(TypeError):
        xprobe.emoji_sequences(b"x")


def test_find_by_name_and_flag():
    found = [row["emoji"] for row in xprobe.emoji_find("house")]
    assert found[:3] == ["\U0001F3E0", "\U0001F3D8", "\U0001F3E1"]
    assert xprobe.emoji_find("flag jp") == [{"emoji": "\U0001F1EF\U0001F1F5", "name": "FLAG JP",
                                             "codepoints": ["U+1F1EF", "U+1F1F5"]}]
    assert len(xprobe.emoji_find("face", limit=5)) == 5
    assert xprobe.emoji_find("zzzz-no-such") == []
    assert all(unicodedata.name(row["emoji"]) == row["name"] for row in xprobe.emoji_find("cat"))
    for bad in ("", "  "):
        with pytest.raises(ValueError):
            xprobe.emoji_find(bad)


def test_extended_pictographic_table_against_node_for_every_code_point():
    node = _node("""
      const re=/\\p{Extended_Pictographic}/u, out=[];
      for (let c=0;c<=0x10FFFF;c++) if ((c<0xD800||c>0xDFFF) && re.test(String.fromCodePoint(c))) out.push(c);
      process.stdout.write(JSON.stringify({unicode: process.versions.unicode, points: out}));""", "")
    ours = [c for c in range(0x110000) if not 0xD800 <= c <= 0xDFFF and xprobe._PICT_RE.match(chr(c))]
    if node["unicode"].startswith(xprobe._EXT_PICT_UNICODE):
        assert ours == node["points"]
    else:
        # The property changes between versions (Unicode 17 narrowed it); the table must
        # still contain every code point any newer Node treats as pictographic.
        assert set(node["points"]) <= set(ours), sorted(set(node["points"]) - set(ours))[:10]


def test_sequences_mirror_node_rgi_emoji():
    node = _node("""
      let s=''; process.stdin.setEncoding('utf8').on('data',c=>s+=c).on('end',()=>{
        process.stdout.write(JSON.stringify([...s.matchAll(/\\p{RGI_Emoji}/gv)].map(m=>m[0])));});""", CORPUS)
    ours = [row["emoji"] for row in xprobe.emoji_sequences(CORPUS)]
    extras = [e for e in ours if e not in node]
    # Every RGI sequence is found whole; extras are only text-default single symbols without VS16.
    assert [e for e in ours if e in node] == node
    assert all(len(e) == 1 and ord(e) < 0x1F000 for e in extras), extras


def test_inventory_counts_forms_and_cli(tmp_path, capsys):
    (tmp_path / "a.md").write_text("# \u2764\ufe0f Title\n\u2764 again \U0001F3E0\n", encoding="utf-8")
    (tmp_path / "b.bin").write_bytes(b"\0\1\2")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.md").write_text("\U0001F3E0", encoding="utf-8")
    report = xprobe.emoji_inventory(tmp_path)
    assert report["files"] == 1 and report["skipped"] == 1 and not report["truncated"]
    heart = report["emoji"][0]
    assert heart["identity"] == "\u2764" and heart["count"] == 2
    assert heart["forms"] == {"\u2764\ufe0f": 1, "\u2764": 1} and heart["examples"] == ["a.md:1", "a.md:2"]
    two = xprobe.emoji_inventory([tmp_path, tmp_path / "a.md"], max_files=1)
    assert two["truncated"] and two["files"] == 1
    assert xprobe.main(["--emoji", "--root", str(tmp_path), "--brief"]) == 0
    out = capsys.readouterr().out
    assert "forms: \u2764\ufe0fx1 \u2764x1" in out and "emoji: 2 distinct in 1 file(s)" in out
    assert xprobe.main(["--emoji", "--root", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["schema"] == "xprobe.emoji-inventory.v1"
    assert xprobe.main(["--emoji-find", "house", "--max-matches", "2"]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 2
    assert xprobe.main(["--emoji-explain", "a \U0001F1EF\U0001F1F5"]) == 0
    assert capsys.readouterr().out == "\U0001F1EF\U0001F1F5\tU+1F1EF U+1F1F5\tFLAG JP\n"
    assert xprobe.main(["--emoji-explain", "plain"]) == 1


def test_names_table_from_queryu_is_preferred(tmp_path, capsys):
    table = tmp_path / "emoji_names.json"
    table.write_text(json.dumps({"schema": "queryu.emoji-names/1", "sources": [],
                                 "names": {"\U0001F469\u200d\U0001F4BB": "woman technologist",
                                           "\U0001F5FA\ufe0f": "world map"}}), encoding="utf-8")
    names = xprobe.load_emoji_names(table)
    assert names == {"\U0001F469\u200d\U0001F4BB": "woman technologist", "\U0001F5FA": "world map"}
    assert xprobe.emoji_name("\U0001F5FA\ufe0f", names) == "world map"
    assert xprobe.emoji_name("\U0001F469\U0001F3FD\u200d\U0001F4BB", names) == "woman technologist: medium skin tone"
    assert xprobe.emoji_name("\U0001F3E0", names) == "HOUSE BUILDING"  # not in the table: unicodedata
    plain = tmp_path / "plain.json"
    plain.write_text(json.dumps({"\U0001F3E0": "house"}), encoding="utf-8")
    assert xprobe.emoji_sequences("a \U0001F3E0", xprobe.load_emoji_names(plain))[0]["name"] == "house"
    bad = tmp_path / "bad.json"
    bad.write_text("[1]", encoding="utf-8")
    with pytest.raises(ValueError):
        xprobe.load_emoji_names(bad)
    assert xprobe.main(["--emoji-explain", "\U0001F5FA", "--emoji-names", str(table)]) == 0
    assert capsys.readouterr().out == "\U0001F5FA\tU+1F5FA\tworld map\n"
    (tmp_path / "r").mkdir()
    (tmp_path / "r" / "a.md").write_text("\U0001F5FA\n", encoding="utf-8")
    assert xprobe.main(["--emoji", "--root", str(tmp_path / "r"), "--brief", "--emoji-names", str(table)]) == 0
    assert "\tworld map" in capsys.readouterr().out
