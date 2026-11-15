"""Reading legacy text: decode_text / readable_text, and mojibake detection, restoration, scan and CLI."""
import json, subprocess, sys
from pathlib import Path

import pytest

import xprobe
from xprobe import decode_text


@pytest.mark.parametrize("encoding", ["utf-8", "cp932", "euc_jp", "iso2022_jp"])
def test_japanese_csv_without_settings(encoding):
    text = "名前,金額\nこんにちは,123\nカタカナ,456\n"
    result = decode_text(text.encode(encoding))
    assert result["text"] == text
    assert result["encoding"] == encoding
    assert result["status"] == "decoded"


def test_utf8_multilingual_emoji():
    text = "日本語 English Français العربية 😀"
    result = decode_text(text.encode())
    assert result["text"] == text
    assert result["encoding"] == "utf-8"


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "utf-32"])
def test_bom_precedence_and_preserved_content(encoding):
    text = '<meta charset="cp932">こんにちは😀'
    result = decode_text(text.encode(encoding))
    assert result["text"] == text
    assert result["source"] == "bom"


@pytest.mark.parametrize("prefix", [b'<meta charset="Shift_JIS">',
    b'<meta http-equiv="content-type" content="text/html; charset=windows-31j">',
    b'<?xml version="1.0" encoding="cp932"?>'])
def test_declaration(prefix):
    raw = prefix + "文字".encode("cp932")
    result = decode_text(raw)
    assert result["text"] == prefix.decode("ascii") + "文字"
    assert result["source"] == "declared"
    assert result["encoding"] == "cp932"


def test_unknown_declaration_falls_through():
    raw = b'<meta charset="made-up">' + "文字".encode()
    result = decode_text(raw)
    assert result["text"] == raw.decode()
    assert "unsupported encoding declaration" in result["warnings"][0]


def test_not_an_encoding_declaration():
    raw = b'plain charset="cp932" ' + "こんにちは".encode()
    assert decode_text(raw)["text"] == raw.decode()


def test_partially_valid_utf8_and_invalid_suffix():
    raw = "こんにちは😀".encode() + b"\xffEND"
    result = decode_text(raw)
    assert result["encoding"] == "utf-8"
    assert result["status"] == "partial"
    assert result["text"] == "こんにちは😀\\xffEND"


def test_truncated_utf8():
    raw = "こんにちは".encode() + b"\xe3\x81"
    result = decode_text(raw)
    assert result["text"] == "こんにちは\\xe3\\x81"
    assert result["status"] == "partial"


def test_declared_encoding_partial_keeps_body():
    raw = b'<meta charset="cp932">' + "こんにちは".encode("cp932") + b"\x81"
    result = decode_text(raw)
    assert result["encoding"] == "cp932"
    assert result["text"] == '<meta charset="cp932">こんにちは\\x81'
    assert result["source"] == "declared"
    assert result["status"] == "partial"


@pytest.mark.parametrize("body", ["日本語", "こんにちは", "日本", "東京都"])
def test_wrong_cp932_declaration_yields_to_readable_utf8(body):
    raw = b'<meta charset="cp932">' + body.encode()
    result = decode_text(raw)
    assert result["text"] == raw.decode()
    assert result["encoding"] == "utf-8"
    assert result["source"] == "fallback"
    assert "declaration conflicts" in result["warnings"][0]
    assert [item["encoding"] for item in result["candidates"]] == ["cp932", "utf-8"]


def test_false_iso2022_escape_hint_keeps_utf8_body():
    raw = b"escape example: \x1b$B " + "こんにちは".encode()
    result = decode_text(raw)
    assert result["encoding"] == "utf-8"
    assert result["text"] == raw.decode()
    assert "escape hint conflicts" in result["warnings"][0]


@pytest.mark.parametrize("declared", ["utf-8", "ascii"])
@pytest.mark.parametrize("actual", ["cp932", "euc_jp"])
def test_wrong_unicode_or_ascii_declaration_tries_legacy_candidates(declared, actual):
    prefix = ('<meta charset="' + declared + '">').encode()
    raw = prefix + "こんにちは".encode(actual)
    result = decode_text(raw)
    assert result["text"] == prefix.decode() + "こんにちは"
    assert result["encoding"] == actual
    assert result["source"] == "fallback"
    assert result["status"] == "decoded"
    assert "declaration conflicts" in result["warnings"][0]


@pytest.mark.parametrize("declared", ["utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"])
def test_wide_declaration_without_bom_does_not_reinterpret_ascii(declared):
    raw = ('<meta charset="' + declared + '">hello').encode()
    result = decode_text(raw)
    assert result["text"] == raw.decode()
    assert result["encoding"] == "utf-8"
    assert "unsupported encoding declaration" in result["warnings"][0]


def test_declared_partial_utf8_keeps_known_japanese():
    raw = b'<meta charset="utf-8">' + "こんにちは".encode() + b"\xff"
    result = decode_text(raw)
    assert result["encoding"] == "utf-8"
    assert result["text"] == '<meta charset="utf-8">こんにちは\\xff'
    assert result["status"] == "partial"


def test_truncated_ascii_iso2022_keeps_readable_japanese():
    raw = "こんにちは".encode("iso2022_jp") + b"\x1b$"
    result = decode_text(raw)
    assert result["encoding"] == "iso2022_jp"
    assert result["text"] == "こんにちは\\x1b\\x24"
    assert result["status"] == "partial"


def test_bom_corruption_keeps_visible_byte():
    result = decode_text(b"\xff\xfe" + "日本".encode("utf-16-le") + b"\x41")
    assert result["text"] == "日本\\x41"
    assert result["status"] == "partial"


def test_unknown_bytes_do_not_become_private_use_glyphs():
    result = decode_text(b"ASCII\xffEND")
    assert result["text"] == "ASCII\\xffEND"
    assert result["status"] == "partial"


def test_short_ambiguous_text_exposes_candidates():
    result = decode_text(b"\xa4\xa2")
    assert result["text"] == "あ"
    assert {item["encoding"] for item in result["candidates"]} == {"utf-8", "cp932", "euc_jp"}
    assert "heuristically" in result["warnings"][0]


def test_replacement_character_is_not_deleted():
    result = decode_text("before�after".encode())
    assert result["text"] == "before�after"
    assert result["status"] == "partial"


@pytest.mark.parametrize("data", [b"\x00\x01", b"PK\x03\x04binary", b"PK\x05\x06", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1data"])
def test_binary_container_is_identified(data):
    with pytest.raises(ValueError, match="format parser"):
        decode_text(data)


def test_ascii_empty_byteslike_and_type():
    assert decode_text(b"")["text"] == ""
    assert decode_text(bytearray(b"hello"))["text"] == "hello"
    assert decode_text(memoryview(b"hello"))["text"] == "hello"
    with pytest.raises(TypeError):
        decode_text("hello")


def test_sniffing_budget():
    raw = b" " * 4096 + b'<meta charset="cp932">' + "こんにちは".encode()
    result = decode_text(raw)
    assert result["encoding"] == "utf-8"
    assert result["source"] == "heuristic"


# ──── mojibake: detection, restoration, scan, search and CLI ────

def test_mojibake_text_detection_and_hints():
    # CP932 -> CP1252
    findings = xprobe.mojibake_text("Hello \x82±\x82ñ\x82É\x82¿\x82Í World")
    assert len(findings) == 1
    assert findings[0]["kind"] == "cp932_as_cp1252"
    assert findings[0]["hint"] == "hiragana"
    assert findings[0]["restored"] == "こんにちは"

    # CP932 -> CP1252 Katakana
    findings_kat = xprobe.mojibake_text("Msg: ƒeƒXƒg")
    assert len(findings_kat) == 1
    assert findings_kat[0]["kind"] == "cp932_as_cp1252"
    assert findings_kat[0]["hint"] == "katakana"
    assert findings_kat[0]["restored"] == "テスト"

    # UTF-8 -> CP932 Hiragana
    findings_u_sjis = xprobe.mojibake_text("Data: 縺薙ｓ縺ｫ縺｡縺ｯ OK")
    assert len(findings_u_sjis) == 1
    assert findings_u_sjis[0]["kind"] == "utf8_as_cp932"
    assert findings_u_sjis[0]["hint"] == "hiragana"
    assert findings_u_sjis[0]["restored"] == "こんにちは"

    # UTF-8 -> CP1252 Katakana & Kanji
    findings_u_1252 = xprobe.mojibake_text("Info: ãƒ†ã‚¹ãƒˆ File: æ—¥æœ¬èªž")
    assert len(findings_u_1252) == 2
    assert findings_u_1252[0]["kind"] == "utf8_as_cp1252"
    assert findings_u_1252[0]["hint"] == "katakana"
    assert findings_u_1252[0]["restored"] == "テスト"
    assert findings_u_1252[1]["kind"] == "utf8_as_cp1252"
    assert findings_u_1252[1]["hint"] == "kanji"
    assert findings_u_1252[1]["restored"] == "日本語"

    # Replacement character
    findings_rep = xprobe.mojibake_text("Bad \ufffd\ufffd")
    assert len(findings_rep) == 1
    assert findings_rep[0]["kind"] == "replacement_char"
    assert findings_rep[0]["hint"] == "replacement"
    assert findings_rep[0]["restored"] == "\ufffd\ufffd"
    assert findings_rep[0]["status"] == "unrecoverable"

    # Clean text
    assert xprobe.mojibake_text("Clean text") == []


def test_mojibake_text_type_error():
    with pytest.raises(TypeError):
        xprobe.mojibake_text(123)


def test_restore_mojibake():
    text = "Status: 縺薙ｓ縺ｫ縺｡縺ｯ OK, Msg: ƒeƒXƒg"
    restored = xprobe.restore_mojibake(text)
    assert restored == "Status: こんにちは OK, Msg: テスト"

    # Clean text unchanged
    assert xprobe.restore_mojibake("Clean") == "Clean"


def test_restore_mojibake_type_error():
    with pytest.raises(TypeError):
        xprobe.restore_mojibake(None)


def test_mojibake_scan(tmp_path):
    p1 = tmp_path / "a.txt"
    p1.write_text("Line 1: 縺薙ｓ縺ｫ縺｡縺ｯ\nLine 2: Normal\n", encoding="utf-8")
    p2 = tmp_path / "b.txt"
    p2.write_text("Info: ãƒ†ã‚¹ãƒˆ\n", encoding="utf-8")

    report = xprobe.mojibake_scan([tmp_path])
    assert report["schema"] == "xprobe.mojibake.v1"
    assert report["files"] == 2
    assert report["skipped"] == 0
    assert len(report["findings"]) == 2
    assert report["counts"]["utf8_as_cp932"] == 1
    assert report["counts"]["utf8_as_cp1252"] == 1


def test_mojibake_scan_skips(tmp_path):
    # Binary file
    bfile = tmp_path / "binary.bin"
    bfile.write_bytes(b"\x00\x01\x02\x03\x04")

    report = xprobe.mojibake_scan([tmp_path])
    assert report["skipped"] == 1


def test_search_with_mojibake_normalization():
    text = "Line 1: Hello\nLine 2: 縺薙ｓ縺ｫ縺｡縺ｯ\nLine 3: ãƒ†ã‚¹ãƒˆ\n"
    matches = xprobe.search_text(text, "こんにちは", normalize="mojibake")
    assert len(matches) == 1
    assert matches[0]["line"] == 2
    assert matches[0]["match"] == "縺薙ｓ縺ｫ縺｡縺ｯ"
    assert matches[0]["normalized"] == "こんにちは"

    matches_kat = xprobe.search_text(text, "テスト", normalize=["mojibake"])
    assert len(matches_kat) == 1
    assert matches_kat[0]["line"] == 3
    assert matches_kat[0]["match"] == "ãƒ†ã‚¹ãƒˆ"
    assert matches_kat[0]["normalized"] == "テスト"


def test_cli_mojibake_modes(tmp_path, capsys, monkeypatch):
    p = tmp_path / "data.txt"
    p.write_text("Status: 縺薙ｓ縺ｫ縺｡縺ｯ OK\n", encoding="utf-8")

    # Mode 1: --mojibake
    code1 = xprobe.main(["--mojibake", "--root", str(tmp_path)])
    assert code1 == 1
    out1 = capsys.readouterr().out
    data1 = json.loads(out1)
    assert len(data1["findings"]) == 1
    assert data1["findings"][0]["restored"] == "こんにちは"

    # Mode 2: --mojibake --brief
    code2 = xprobe.main(["--mojibake", "--brief", "--root", str(tmp_path)])
    assert code2 == 1
    out2 = capsys.readouterr().out
    assert "utf8_as_cp932 (hiragana)" in out2

    # Mode 3: --restore-mojibake file
    code3 = xprobe.main(["--restore-mojibake", str(p)])
    assert code3 == 0
    out3 = capsys.readouterr().out.replace("\r\n", "\n")
    assert out3 == "Status: こんにちは OK\n"

    # Mode 4: --search --normalize mojibake --brief
    code4 = xprobe.main(["--search", "こんにちは", "--normalize", "mojibake", "--brief", "--root", str(tmp_path)])
    assert code4 == 0
    out4 = capsys.readouterr().out.replace("\r\n", "\n")
    assert "data.txt:1:9: '縺薙ｓ縺ｫ縺｡縺ｯ'" in out4


@pytest.mark.parametrize("suffix", ["正常な文章", "ａｂ", "😀", "\ufffd", "\ufffd\ufffd", "Ā", "①", "漢字"])
def test_readable_suffix_survives_partial_repair(suffix):
    broken = "縺薙ｓ縺ｫ縺｡縺ｯ"
    original = broken + suffix
    assert xprobe.restore_mojibake(original) == "こんにちは" + suffix
    assert xprobe.normalize_text(original, "mojibake") == "こんにちは" + suffix


@pytest.mark.parametrize("text,expected", [
    ("ƒeƒXƒgé", "テストé"),
    ("étudeƒeƒXƒg", "étudeテスト"),
    ("ƒeƒXƒgétude", "テストétude"),
    ("繧カタカナ", "繧カタカナ"),
    ("étude élève São Paulo", "étude élève São Paulo"),
    ("\ufffd\ufffd", "\ufffd\ufffd"),
    ("縺薙ｓ縺ｫ縺｡縺ｯ正常縺薙ｓ縺ｫ縺｡縺ｯ", "こんにちは正常こんにちは"),
])
def test_no_silent_loss_or_repair_of_clean_words(text, expected):
    assert xprobe.restore_mojibake(text) == expected


def test_overlap_has_one_consistent_reading_and_original_search_coordinates():
    correct = "をかかナは"
    broken = correct.encode("utf-8").decode("latin1")
    assert xprobe.restore_mojibake(broken) == correct
    assert xprobe.normalize_text(broken, "mojibake") == correct
    findings = xprobe.mojibake_text(broken)
    assert len(findings) == 1
    assert findings[0]["roundtrip"] is True
    matches = xprobe.search_text("Before " + broken + " After", correct, normalize="mojibake")
    assert matches[0]["match"] == broken
    assert matches[0]["column"] == 8
    assert matches[0]["end_column"] == 8 + len(broken)


def test_cp1252_utf8_kanji_outside_old_lead_patterns():
    original = "中"
    broken = original.encode("utf-8").decode("cp1252")
    assert xprobe.restore_mojibake(broken) == original


def test_partial_reading_retains_decoding_and_repair_evidence():
    broken = "縺薙ｓ縺ｫ縺｡縺ｯ正常"
    report = xprobe.readable_text(broken.encode("utf-8") + b"\xff")
    assert report["status"] == "partial"
    assert report["text"] == "こんにちは正常\\xff"
    assert report["decoded_text"] == broken + "\\xff"
    assert report["findings"][0]["text"] == "縺薙ｓ縺ｫ縺｡縺ｯ"


@pytest.mark.parametrize("encoding", ["cp932", "euc_jp", "utf-16"])
def test_scan_and_search_auto_decode_without_settings(tmp_path, encoding):
    path = tmp_path / "excel-export.csv"
    path.write_bytes("挨拶,金額\nこんにちは,123\n".encode(encoding))
    scan = xprobe.mojibake_scan(path)
    assert scan["files"] == 1
    assert scan["skipped"] == 0
    assert scan["decodings"][0]["status"] == "decoded"
    search = xprobe.search_files(path, "こんにちは", normalize="mojibake")
    assert search["matches"][0]["match"] == "こんにちは"
    assert search["matches"][0]["line"] == 2
    assert search["decodings"][0]["status"] == "decoded"
    if encoding == "cp932":
        strict = xprobe.search_files(path, "こんにちは", normalize="mojibake", encoding="utf-8")
        assert strict["skipped"][0]["reason"] == "decode_error"


def test_read_cli_partial_is_usable_with_report_and_limits(tmp_path, capsys):
    path = tmp_path / "broken.csv"
    original = "こんにちは".encode() + b"\xff"
    path.write_bytes(original)
    assert xprobe.main(["--read-text", str(path)]) == 0
    captured = capsys.readouterr()
    assert captured.out == "こんにちは\\xff"
    assert "partial" in captured.err
    assert path.read_bytes() == original
    assert xprobe.main(["--read-text", str(path), "--text-report"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "partial"
    assert report["text"] == "こんにちは\\xff"
    assert xprobe.main(["--read-text", str(path), "--max-bytes", "1"]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "max-bytes" in captured.err


def test_stdin_read_without_site_packages():
    script = Path(xprobe.__file__).resolve()
    completed = subprocess.run([sys.executable, "-S", str(script), "--read-text", "-"],
                               input="こんにちは".encode("cp932"), capture_output=True, timeout=10)
    assert completed.returncode == 0
    assert completed.stdout.decode("utf-8") == "こんにちは"
    assert b"cp932" in completed.stderr


def test_search_cli_propagates_decoding_diagnostics(tmp_path, capsys):
    path = tmp_path / "example.csv"
    path.write_bytes("こんにちは".encode("cp932"))
    assert xprobe.main(["--root", str(path), "--search", "こんにちは", "--normalize", "mojibake"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["matches"][0]["match"] == "こんにちは"
    assert report["decodings"][0]["encoding"] == "cp932"


def test_readable_public_exports():
    assert {"mojibake_text", "restore_mojibake", "mojibake_scan", "decode_text", "readable_text"} <= set(xprobe.__all__)
