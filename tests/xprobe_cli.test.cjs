"use strict";
// Node-only regression gate: no Python process and no npm dependencies.
const test = require("node:test");
const assert = require("node:assert/strict");
const {spawnSync} = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const modulePath = path.resolve(__dirname, "..", "xprobe.cjs");
const x = require(modulePath);
const cli = (args, input = "") => spawnSync(process.execPath, [modulePath, ...args], {
  input, encoding: "utf8", timeout: 10000,
});
function success(result, status) {
  assert.equal(result.error, undefined);
  assert.equal(result.status, status);
  assert.equal(result.stderr, "");
}

test("stdin: empty/ordinary Unicode are clean JSON, status 0", () => {
  for (const input of ["", "hello", "\u65e5\u672c\u8a9e \ud83d\ude42", "\ufeffok"]) {
    const result = cli(["--hidden-text", "-"], input);
    success(result, 0);
    assert.deepEqual(JSON.parse(result.stdout), []);
  }
});

test("stdin: findings use scalar offsets and ASCII JSON, status 1", () => {
  const result = cli(["--hidden-text", "-"], "\ud83d\ude42a\u202e\udb40\udc41");
  success(result, 1);
  assert.match(result.stdout, /^[\x00-\x7f]*$/);
  const rows = JSON.parse(result.stdout);
  assert.deepEqual(rows.map(r => [r.kind, r.start, r.end, r.length]),
    [["bidi_control", 2, 3, 1], ["tag_text", 3, 4, 1]]);
  assert.equal(rows[1].decoded, "A");
  assert.deepEqual(rows[1].codepoints, ["U+E0041"]);
});

test("strip stdin preserves bytes of visible text and leading BOM", () => {
  for (const [input, expected] of [["", ""], ["\ufeff\ud83d\ude42a\u200bb\n", "\ufeff\ud83d\ude42ab\n"],
                                  ["https://p\u0430y.com", "https://p\u0430y.com"]]) {
    const result = cli(["--strip-hidden", "-"], input);
    success(result, 0);
    assert.equal(result.stdout, expected);
  }
});

test("files: Unicode filename, JSON and strip output", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "xprobe-cli-"));
  try {
    const file = path.join(dir, "\u691c\u67fb file.txt");
    fs.writeFileSync(file, "\ufeff\ud83d\ude42a\u200bb");
    const found = cli(["--hidden-text", file]);
    success(found, 1);
    assert.deepEqual(JSON.parse(found.stdout).map(r => [r.kind, r.start, r.end]), [["zero_width", 3, 4]]);
    const stripped = cli(["--strip-hidden", file]);
    success(stripped, 0);
    assert.equal(stripped.stdout, "\ufeff\ud83d\ude42ab");
    fs.writeFileSync(file, Buffer.from([0xed, 0xa0, 0x80]));
    for (const mode of ["--hidden-text", "--strip-hidden"]) {
      const invalid = cli([mode, file]);
      assert.equal(invalid.status, 2);
      assert.equal(invalid.stdout, "");
      assert.match(invalid.stderr, /^xprobe: /);
    }
  } finally { fs.rmSync(dir, {recursive: true, force: true}); }
});

test("invalid UTF-8 stdin is an error, never silently replaced", () => {
  for (const mode of ["--hidden-text", "--strip-hidden"]) {
    for (const bytes of [[0xff], [0xe3, 0x81], [0xc0, 0xaf], [0xf4, 0x90, 0x80, 0x80]]) {
      const result = cli([mode, "-"], Buffer.from(bytes));
      assert.equal(result.status, 2);
      assert.equal(result.stdout, "");
      assert.match(result.stderr, /^xprobe: /);
    }
  }
});

test("usage, missing files and surplus arguments: status 2, stderr only", () => {
  for (const args of [[], ["--hidden-text"], ["--unknown", "-"], ["--hidden-text", "-", "extra"],
                      ["--strip-hidden", "-", "extra"], ["--hidden-text", path.join(os.tmpdir(), "xprobe-missing-" + process.pid)]]) {
    const result = cli(args);
    assert.equal(result.status, 2);
    assert.equal(result.stdout, "");
    assert.match(result.stderr, /^xprobe: /);
  }
});

test("API rejects prototype rule names and invalid inputs", () => {
  for (const kind of ["constructor", "__proto__", "toString", "hasOwnProperty", "nope"]) {
    assert.throws(() => x.hiddenText("x", {kinds: kind}), /unknown hidden-text kind/);
    assert.throws(() => x.stripHidden("x", {kinds: [kind]}), /unknown hidden-text kind/);
  }
  for (const text of [null, 1, {}, [], Buffer.from("x")]) assert.throws(() => x.hiddenText(text), TypeError);
  assert.throws(() => x.hiddenText("x", {minSeverity: "critical"}), /min_severity/);
  assert.deepEqual(x.hiddenText("\u200b", {kinds: []}), []);
  const rules = x.hiddenTextRules(); rules.tag_text.severity = "low";
  assert.equal(x.hiddenTextRules().tag_text.severity, "high");
});
