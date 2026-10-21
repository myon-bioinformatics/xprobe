import json
from pathlib import Path
import subprocess
import sys
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
