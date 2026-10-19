"""xgrep: normalized views with original coordinates, named presets, CLI."""
import pytest

import xprobe


def test_spaces_gap_tolerant_with_original_coordinates():
    rows = xprobe.search_text("seq: AC G\tT x\n", "acgt", normalize=["spaces", "casefold"])
    assert rows == [{"line": 1, "column": 6, "end_column": 12, "match": "AC G\tT",
                     "normalized": "acgt", "text": "seq: AC G\tT x"}]


def test_nfkc_fullwidth_halfwidth_kana_and_casefold():
    text = "ＡＢＣ123 と ｶﾞｲﾄﾞ と Straße"
    rows = xprobe.search_text(text, "abc123", normalize=("nfkc", "casefold"))
    assert rows[0]["match"] == "ＡＢＣ123" and rows[0]["column"] == 1
    kana = xprobe.search_text(text, "ガイド", normalize=("nfkc",))
    assert kana[0]["match"] == "ｶﾞｲﾄﾞ"
    assert xprobe.search_text(text, "STRASSE", normalize=("casefold",))[0]["match"] == "Straße"


def test_vs16_and_zwj_are_ignored_for_emoji_routes():
    rows = xprobe.search_text("route 🏝️ → 🗺", "🏝→🗺", normalize=("vs16", "spaces"))
    assert rows[0]["match"] == "🏝️ → 🗺"


def test_ansi_is_removed_before_matching():
    line = "\x1b[31mFAILED\x1b[0m tests/test_a.py"
    rows = xprobe.search_text(line, "FAILED tests", normalize=("ansi",))
    assert rows[0]["match"] == "FAILED\x1b[0m tests" and rows[0]["normalized"] == "FAILED tests"
    assert xprobe.search_text(line, "FAILED tests") == []


def test_regex_runs_on_the_view_and_empty_matches_map_to_original_positions():
    rows = xprobe.search_text("A C\n", r"^|$", regex=True, normalize=("spaces",))
    assert [(r["column"], r["match"]) for r in rows] == [(1, ""), (4, "")]
    assert xprobe.normalize_text("Ａ B\x1b[1m\nｶﾞ") == "ab\nガ"


@pytest.mark.parametrize("preset,text,expected", [
    ("git-sha", "at " + "a" * 40 + " ok", "a" * 40),
    ("iso-timestamp", "t=2026-10-14T08:00:00Z;", "2026-10-14T08:00:00Z"),
    ("python-frame", '  File "x.py", line 3, in f', '  File "x.py", line 3, in f'),
    ("python-exception", "ValueError: bad", "ValueError: bad"),
    ("python-exception", "E       AssertionError: assert 1 == 2", "E       AssertionError: assert 1 == 2"),
    ("node-error", "TypeError: x is undefined", "TypeError: x is undefined"),
    ("npm-error", "npm ERR! code E404", "npm ERR! code E404"),
    ("compiler-error", "error[E0425]: cannot find value", "error[E0425]: cannot find value"),
    ("credential", "token ghp_" + "A" * 36, "ghp_" + "A" * 36),
    ("ci-path", "/home/runner/work/repo/repo/x.py", "/home/runner/work/repo/repo"),
    ("hex-address", "at 0x7ffd1234abcd", "0x7ffd1234abcd"),
    ("url", "see https://example.com/a?b=1.", "https://example.com/a?b=1."),
    ("sha256", "f" * 64, "f" * 64),
    ("ansi", "\x1b[0m", "\x1b[0m"),
])
def test_presets_match_their_examples(preset, text, expected):
    assert xprobe.search_text(text, preset=preset)[0]["match"] == expected


def test_presets_do_not_match_ordinary_prose():
    prose = "The result was an Error in judgment, not a bug. See section 3."
    for name in ("python-exception", "node-error", "compiler-error", "credential", "git-sha"):
        assert xprobe.search_text(prose, preset=name) == [], name
    assert set(xprobe.pattern_presets()) >= {"credential", "python-frame", "ansi"}


def test_invalid_combinations():
    with pytest.raises(ValueError):
        xprobe.search_text("x", "x", preset="git-sha")
    with pytest.raises(ValueError):
        xprobe.search_text("x", preset="nope")
    with pytest.raises(ValueError):
        xprobe.search_text("x", "x", normalize=("bogus",))
    with pytest.raises(ValueError):
        xprobe.search_text("x", "  ", normalize="spaces")
    with pytest.raises(ValueError):
        xprobe.search_text("x")


def test_search_files_and_cli(tmp_path, capsys):
    (tmp_path / "log.txt").write_text("\x1b[31mValueError\x1b[0m: boom\nＶａｌｕｅＥｒｒｏｒ: wide\n", encoding="utf-8")
    report = xprobe.search_files(tmp_path, preset="python-exception", normalize=("ansi", "nfkc"))
    assert [m["line"] for m in report["matches"]] == [1, 2]
    assert xprobe.main(["--root", str(tmp_path), "--preset", "python-exception",
                        "--normalize", "ansi,nfkc", "--brief"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("log.txt:1:6: ") and len(out) == 2
    assert xprobe.main(["--root", str(tmp_path), "--search", "v.lue", "--regex", "--brief",
                        "--normalize", "nfkc,casefold"]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 2
    assert xprobe.main(["--root", str(tmp_path), "--search", "absent", "--brief"]) == 1
    assert xprobe.main(["--presets"]) == 0
    assert "credential:" in capsys.readouterr().out
    assert xprobe.main(["--root", str(tmp_path), "--search", "x", "--normalize", "bogus"]) == 2
    (tmp_path / "bin.dat").write_bytes(b"\x00x")
    assert xprobe.main(["--root", str(tmp_path), "--search", "boom", "--brief", "--max-matches", "1"]) == 2
    assert "skipped: bin.dat (binary)" in capsys.readouterr().out


def test_cli_factor_cases(tmp_path, capsys):
    import json
    from scripts import xprobe_cli

    # Test default --factor-cases run
    assert xprobe_cli.main(["--factor-cases"]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["schema"] == "xprobe.factor-generation.v1"
    assert len(data["cases"]) == 20

    # Test custom seed, count, and json format
    assert xprobe_cli.main(["--factor-cases", "--seed", "7", "--count", "5", "--format", "json"]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert len(data["cases"]) == 5

    # Test jsonl format
    assert xprobe_cli.main(["--factor-cases", "--seed", "7", "--count", "5", "--format", "jsonl"]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert len(data["cases"]) == 5

    # Test error when passing search pattern with --factor-cases
    with pytest.raises(SystemExit):
        xprobe_cli.main(["pattern", "--factor-cases"])
    capsys.readouterr()
