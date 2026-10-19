"""Regenerate xprobe.cjs's embedded tables with CPython 3.12 (Unicode 15.0).

Runtime remains Node-only. Python's hidden-text rules classify Unicode *names*,
not Script properties; IDNA uses the frozen Unicode 3.2 stringprep database.
"""
import json
from pathlib import Path
import stringprep as sp
import unicodedata as ud


def ranges(points):
    result = []
    for n in points:
        if result and n == result[-1][1] + 1:
            result[-1][1] = n
        else:
            result.append([n, n])
    return " ".join(f"{a:x}" if a == b else f"{a:x}-{b:x}" for a, b in result)


def generate():
    if ud.unidata_version != "15.0.0":
        raise SystemExit("regenerate with CPython 3.12 / Unicode 15.0.0")
    names = "LATIN CYRILLIC GREEK ARMENIAN CHEROKEE CJK HIRAGANA KATAKANA HANGUL DIGIT".split()
    groups = {name: [] for name in names}
    categories = {k: [] for k in ("LETTER", "LETTER_MARK", "WORD", "ALNUM", "NONBASE", "FORMAT", "PRIVATE", "NONPRINT")}
    tables = {k: [] for k in ("B1", "PROHIBITED", "RANDAL", "LCAT", "UNASSIGNED32")}
    mapping, corrections = {}, {}
    for n in range(0x110000):
        c = chr(n)
        category = ud.category(c)
        flags = {"LETTER": category[0] == "L", "LETTER_MARK": category[0] in "LM",
                 "WORD": category[0] == "L" or category in ("Nl", "No"),
                 "ALNUM": category[0] in "LN", "NONBASE": category[0] in "ZC",
                 "FORMAT": category == "Cf", "PRIVATE": category == "Co",
                 "NONPRINT": not c.isprintable()}
        for name, flag in flags.items():
            if flag:
                categories[name].append(n)
        words = ud.name(c, "").split()
        while words and words[0] in ("FULLWIDTH", "HALFWIDTH"):
            words.pop(0)
        if words and words[0] in groups:
            groups[words[0]].append(n)
        if sp.in_table_b1(c):
            tables["B1"].append(n)
        b2 = sp.map_table_b2(c)
        if b2 != c:
            mapping[f"{n:x}"] = b2
        if any(getattr(sp, "in_table_c" + k)(c) for k in ("12", "22", "3", "4", "5", "6", "7", "8", "9")):
            tables["PROHIBITED"].append(n)
        if sp.in_table_d1(c):
            tables["RANDAL"].append(n)
        if sp.in_table_d2(c):
            tables["LCAT"].append(n)
        if ud.ucd_3_2_0.category(c) == "Cn":
            tables["UNASSIGNED32"].append(n)
        elif ud.normalize("NFKC", c) != ud.ucd_3_2_0.normalize("NFKC", c):
            corrections[f"{n:x}"] = ud.ucd_3_2_0.normalize("NFKC", c)
    dump = lambda v: json.dumps(v, ensure_ascii=True, separators=(",", ":"))
    lines = ["// BEGIN GENERATED UNICODE TABLES (scripts/generate_hidden_unicode.py)",
             "const NAME_SCRIPTS = {"]
    lines += [f"  {name}: rangeRE({dump(ranges(points))})," for name, points in groups.items()]
    lines += ["};"]
    lines += [f"const CAT_{name} = rangeRE({dump(ranges(points))});" for name, points in categories.items()]
    lines += [f"const IDNA_{name} = rangeRE({dump(ranges(points))});" for name, points in tables.items()]
    lines += ["const IDNA_B2 = " + dump(mapping) + ";", "const NFKC32_CORRECTIONS = " + dump(corrections) + ";",
              "// END GENERATED UNICODE TABLES"]
    return "\n".join(lines)


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "xprobe.cjs"
    source = target.read_text(encoding="utf-8")
    start = source.index("// BEGIN GENERATED UNICODE TABLES")
    end = source.index("// END GENERATED UNICODE TABLES", start) + len("// END GENERATED UNICODE TABLES")
    target.write_text(source[:start] + generate() + source[end:], encoding="utf-8")
