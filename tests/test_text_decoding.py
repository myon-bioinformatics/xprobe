import pytest

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
