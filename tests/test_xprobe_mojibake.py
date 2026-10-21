import json
import pytest
import xprobe


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
    assert findings_rep[0]["restored"] == "??"

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
