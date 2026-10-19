// Compile-only check (tsc --noEmit): the declarations accept real calls and reject wrong ones.
import xprobe = require("../xprobe.cjs");
const rows: xprobe.HiddenTextFinding[] = xprobe.hiddenText("a\u200bb", {kinds: ["zero_width"], minSeverity: "medium"});
const clean: string = xprobe.stripHidden("a\u200bb");
const about: string = xprobe.hiddenTextRules().bidi_control.about;
// @ts-expect-error unknown kind
xprobe.hiddenText("x", {kinds: "zero-width"});
// @ts-expect-error unknown severity
xprobe.hiddenText("x", {minSeverity: "critical"});
void [rows[0]?.start, clean, about];
