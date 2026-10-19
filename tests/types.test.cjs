"use strict";
// xprobe.cjs ships xprobe.d.cts whose exported names and rule kinds match the runtime.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const root = path.join(__dirname, "..");
const types = fs.readFileSync(path.join(root, "xprobe.d.cts"), "utf8");
const xprobe = require(path.join(root, "xprobe.cjs"));
test("declared names match runtime exports", () => {
  const declared = [...types.matchAll(/^export (?:function|const) ([A-Za-z_$][\w$]*)/gm)].map((m) => m[1]);
  assert.deepEqual([...new Set(declared)].sort(), Object.keys(xprobe).sort());
});
test("declared kinds match the rule table", () => {
  const block = /export type HiddenTextKind =([^;]*);/.exec(types)[1];
  assert.deepEqual([...block.matchAll(/"([a-z_]+)"/g)].map((m) => m[1]).sort(), Object.keys(xprobe.hiddenTextRules()).sort());
});
