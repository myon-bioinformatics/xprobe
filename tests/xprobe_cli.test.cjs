"use strict";
// Node-side smoke test for the xprobe.cjs launcher (runs xprobe.py through vendor/py_launch.cjs).
// Needs Node 24+ and Python 3.9+ on PATH (or XPROBE_PYTHON); no npm dependencies.
const test = require("node:test");
const assert = require("node:assert/strict");
const {spawnSync} = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const modulePath = path.resolve(__dirname, "..", "xprobe.cjs");
const cli = (args, input = "") => spawnSync(process.execPath, [modulePath, ...args], {
  input, encoding: "utf8", timeout: 60000,
});

test("exports only the launcher configuration", () => {
  const x = require(modulePath);
  assert.deepEqual(Object.keys(x).sort(), ["PY_LAUNCH", "PY_SCRIPT"]);
  assert.equal(path.basename(x.PY_SCRIPT), "xprobe.py");
  assert.deepEqual(x.PY_LAUNCH, {envVar: "XPROBE_PYTHON", noSite: true});
});

test("--help exits 0 and documents the modes", () => {
  const r = cli(["--help"]);
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /--hidden-text/);
  assert.match(r.stdout, /--strip-hidden/);
});

test("--strip-hidden - removes hidden characters and keeps a leading BOM", () => {
  const r = cli(["--strip-hidden", "-"], "\ufeffa\u200bb\n");
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.stdout, "\ufeffab\n");
});

test("--hidden-text reports findings with exit 1", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "xprobe-"));
  fs.writeFileSync(path.join(dir, "h.txt"), "a\u202eb\n");
  const r = cli(["--hidden-text", "--root", dir]);
  assert.equal(r.status, 1, r.stderr);
  const report = JSON.parse(r.stdout);
  assert.equal(report.schema, "xprobe.hidden-text.v1");
  assert.deepEqual(report.findings.map(f => f.kind), ["bidi_control"]);
});

test("argparse errors pass through with exit 2", () => {
  const r = cli(["--bogus"]);
  assert.equal(r.status, 2);
  assert.equal(r.stdout, "");
});
