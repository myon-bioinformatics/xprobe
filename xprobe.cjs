"use strict";
/**
 * Node twin of xprobe.py's hidden-text rules (CommonJS, standard library only).
 *
 * hiddenText(text) returns the same findings as xprobe.hidden_text: kind, severity,
 * start/end/length (code-point offsets, like Python str indices), codepoints, and
 * decoded / word / odd where Python has them. Only `detail` differs where Python
 * spells a Unicode character name (JavaScript has no unicodedata.name): there the
 * twin writes the code point (U+202E) instead. tests/test_xprobe_cjs_twin.py keeps
 * the two in step on a shared corpus.
 *
 *   node xprobe.cjs --hidden-text FILE|-    # JSON findings
 *   node xprobe.cjs --strip-hidden FILE|-   # text without hidden characters
 */
const {domainToUnicode} = require("node:url");

const LEVELS = ["low", "medium", "high"];
const RULES = {
  tag_text: ["high", "Unicode tag characters outside an emoji subdivision flag; they spell invisible ASCII"],
  variation_payload: ["high", "four or more variation selectors in a row; decoded as one byte per selector"],
  bidi_control: ["high", "bidirectional embedding, override or isolate control (Trojan Source reordering)"],
  homograph_url: ["high", "URL or domain name with IDN punycode homoglyph, mixed-script label or confusable character spoofing"],
  zero_width: ["medium", "zero-width space, joiner, word joiner or BOM outside emoji and joining scripts"],
  variation_selector: ["medium", "variation selector with no visible base, or repeated"],
  invisible_format: ["medium", "other invisible format character or blank-looking filler letter"],
  mixed_script: ["medium", "one word mixing Latin, Cyrillic, Greek, Armenian or Cherokee letters (homoglyphs)"],
  bidi_mark: ["low", "LRM/RLM/ALM direction mark; normal inside right-to-left text"],
  soft_hyphen: ["low", "soft hyphen: invisible unless the line breaks there; splits keywords"],
  private_use: ["low", "private-use code point (icon fonts, or text only some fonts show)"],
};
const BIDI_OPEN = {"\u202a": "pdf", "\u202b": "pdf", "\u202d": "pdf", "\u202e": "pdf",
  "\u2066": "pdi", "\u2067": "pdi", "\u2068": "pdi"};
const BIDI_CLOSE = {"\u202c": "pdf", "\u2069": "pdi"};
const BIDI_NAMES = {"\u202a": "LEFT-TO-RIGHT EMBEDDING", "\u202b": "RIGHT-TO-LEFT EMBEDDING",
  "\u202c": "POP DIRECTIONAL FORMATTING", "\u202d": "LEFT-TO-RIGHT OVERRIDE", "\u202e": "RIGHT-TO-LEFT OVERRIDE",
  "\u2066": "LEFT-TO-RIGHT ISOLATE", "\u2067": "RIGHT-TO-LEFT ISOLATE", "\u2068": "FIRST STRONG ISOLATE",
  "\u2069": "POP DIRECTIONAL ISOLATE", "\u200e": "LEFT-TO-RIGHT MARK", "\u200f": "RIGHT-TO-LEFT MARK",
  "\u061c": "ARABIC LETTER MARK"};
const ZERO_WIDTH_NAMES = {"\u200b": "ZERO WIDTH SPACE", "\u200c": "ZERO WIDTH NON-JOINER", "\u200d": "ZERO WIDTH JOINER",
  "\u2060": "WORD JOINER", "\ufeff": "ZERO WIDTH NO-BREAK SPACE", "\u180e": "MONGOLIAN VOWEL SEPARATOR"};
const BIDI_MARKS = "\u200e\u200f\u061c";
const ZERO_WIDTH = "\u200b\u200c\u200d\u2060\ufeff\u180e";
const JOINERS = "\u200c\u200d";
const FILLERS = "\u115f\u1160\u3164\uffa0\u2800\u034f\u17b4\u17b5";
const SHOWN_FORMAT = new Set(Array.from("\u0600\u0601\u0602\u0603\u0604\u0605\u06dd\u070f\u0890\u0891\u08e2\u{110bd}\u{110cd}"));
const HOMOGLYPH_SCRIPTS = ["LATIN", "CYRILLIC", "GREEK", "ARMENIAN", "CHEROKEE"];
const SCRIPT_RE = {LATIN: /\p{Script=Latin}/u, CYRILLIC: /\p{Script=Cyrillic}/u, GREEK: /\p{Script=Greek}/u,
  ARMENIAN: /\p{Script=Armenian}/u, CHEROKEE: /\p{Script=Cherokee}/u, CJK: /\p{Script=Han}/u,
  HIRAGANA: /\p{Script=Hiragana}/u, KATAKANA: /\p{Script=Katakana}/u, HANGUL: /\p{Script=Hangul}/u, DIGIT: /[0-9\uff10-\uff19]/u};
const UNJOINED_SCRIPTS = new Set([...HOMOGLYPH_SCRIPTS, "CJK", "HIRAGANA", "KATAKANA", "HANGUL", "DIGIT"]);
const CONFUSABLE_URL_CHARS = {"\uff0e": "FULLWIDTH FULL STOP", "\u3002": "IDEOGRAPHIC FULL STOP",
  "\uff61": "HALFWIDTH IDEOGRAPHIC FULL STOP", "\u2044": "FRACTION SLASH", "\u2215": "DIVISION SLASH",
  "\uff0f": "FULLWIDTH SOLIDUS", "\uff20": "FULLWIDTH COMMERCIAL AT", "\uff1a": "FULLWIDTH COLON",
  "\u037e": "GREEK QUESTION MARK"};
const ASCII_CONFUSABLE_LETTERS = new Set(Array.from("\u0430\u0435\u043e\u0440\u0441\u0445\u0443\u0456\u0458\u0455\u04cf\u03b1\u03b9\u03bf\u03c1\u03f2"));
// Same Extended_Pictographic table as xprobe.py (_EXT_PICT, Unicode 16.0).
const EXT_PICT = ("a9 ae 203c 2049 2122 2139 2194-2199 21a9-21aa 231a-231b 2328 2388 23cf 23e9-23f3 " +
  "23f8-23fa 24c2 25aa-25ab 25b6 25c0 25fb-25fe 2600-2605 2607-2612 2614-2685 2690-2705 " +
  "2708-2712 2714 2716 271d 2721 2728 2733-2734 2744 2747 274c 274e 2753-2755 2757 " +
  "2763-2767 2795-2797 27a1 27b0 27bf 2934-2935 2b05-2b07 2b1b-2b1c 2b50 2b55 3030 303d " +
  "3297 3299 1f000-1f0ff 1f10d-1f10f 1f12f 1f16c-1f171 1f17e-1f17f 1f18e 1f191-1f19a " +
  "1f1ad-1f1e5 1f201-1f20f 1f21a 1f22f 1f232-1f23a 1f23c-1f23f 1f249-1f3fa 1f400-1f53d " +
  "1f546-1f64f 1f680-1f6ff 1f774-1f77f 1f7d5-1f7ff 1f80c-1f80f 1f848-1f84f 1f85a-1f85f " +
  "1f888-1f88f 1f8ae-1f8ff 1f90c-1f93a 1f93c-1f945 1f947-1faff 1fc00-1fffd");
const PICT = "[" + EXT_PICT.split(" ").map((item) => item.split("-").map((h) => `\\u{${h}}`).join("-")).join("") + "]";
const ELEMENT = PICT + "(?:\\uFE0F|[\\u{1F3FB}-\\u{1F3FF}])?";
const EMOJI_RE = new RegExp("[\\u{1F1E6}-\\u{1F1FF}]{2}|[0-9#*]\\uFE0F?\\u20E3|\\u{1F3F4}[\\u{E0020}-\\u{E007E}]+\\u{E007F}|" +
  ELEMENT + "(?:\\u200D" + ELEMENT + ")*", "gu");
const TAG_FLAG_RE = /\u{1F3F4}[\u{E0030}-\u{E0039}\u{E0061}-\u{E007A}]{3,7}\u{E007F}/gu;
const WORD_RE = /[\p{L}\p{Nl}\p{No}]+/gu;
const URL_CANDIDATE_RE = /(?:[A-Za-z][A-Za-z0-9+.-]*:\/\/|(?<![\p{L}\p{N}_.-])[\p{L}\p{N}_-]+(?:[.\uff0e\u3002\uff61][\p{L}\p{N}_-]+)+)[^\s<>"']*/gu;

const cpHex = (c) => "U+" + c.codePointAt(0).toString(16).toUpperCase().padStart(4, "0");
const isSelector = (c) => { const n = c.codePointAt(0); return (n >= 0xfe00 && n <= 0xfe0f) || (n >= 0xe0100 && n <= 0xe01ef); };
function script(c) {
  for (const [name, re] of Object.entries(SCRIPT_RE)) if (re.test(c)) return name;
  return "";
}

function hiddenTextRules() {
  return Object.fromEntries(Object.entries(RULES).map(([k, [severity, about]]) => [k, {severity, about}]));
}

function selectRules(kinds, minSeverity) {
  if (!LEVELS.includes(minSeverity)) throw new Error("min_severity must be one of " + LEVELS.join(", "));
  const list = kinds === undefined || kinds === null ? Object.keys(RULES) : (typeof kinds === "string" ? [kinds] : [...kinds]);
  const unknown = list.filter((k) => !(k in RULES)).sort();
  if (unknown.length) throw new Error("unknown hidden-text kind(s): " + unknown.join(", "));
  const floor = LEVELS.indexOf(minSeverity);
  return new Set(list.filter((k) => LEVELS.indexOf(RULES[k][0]) >= floor));
}

// Python's bytes.decode("utf-8", "backslashreplace").
function decodeBackslash(bytes) {
  let out = "", i = 0;
  while (i < bytes.length) {
    const b = bytes[i];
    const need = b < 0x80 ? 0 : (b >= 0xc2 && b <= 0xdf) ? 1 : (b >= 0xe0 && b <= 0xef) ? 2 : (b >= 0xf0 && b <= 0xf4) ? 3 : -1;
    if (need === 0) { out += String.fromCharCode(b); i++; continue; }
    let ok = need > 0 && i + need < bytes.length + 0 && i + need <= bytes.length - 1 + 1;
    if (ok) {
      const seq = bytes.slice(i, i + need + 1);
      if (seq.length !== need + 1) ok = false;
      else {
        try { out += new TextDecoder("utf-8", {fatal: true}).decode(Uint8Array.from(seq)); i += need + 1; continue; } catch { ok = false; }
      }
    }
    out += "\\x" + b.toString(16).padStart(2, "0");
    i++;
  }
  return out;
}

function findings(text, rules, minSeverity, bom = true, endName = "text") {
  const chars = Array.from(text), n = chars.length, found = [];
  const cpIndex = new Map();  // UTF-16 index -> code-point index
  for (let i = 0, u = 0; i <= n; i++) { cpIndex.set(u, i); if (i < n) u += chars[i].length; }
  const add = (kind, start, end, detail, extra = {}) => {
    const severity = extra.severity || RULES[kind][0];
    delete extra.severity;
    if (rules.has(kind) && LEVELS.indexOf(severity) >= LEVELS.indexOf(minSeverity)) {
      found.push({kind, severity, start, end, codepoints: chars.slice(start, end).slice(0, 16).map(cpHex),
        length: end - start, detail, ...extra});
    }
  };
  const emoji = new Set();
  for (const m of text.matchAll(EMOJI_RE)) {
    if (m[0].endsWith("\u{E007F}")) continue;
    const s = cpIndex.get(m.index), e = cpIndex.get(m.index + m[0].length);
    for (let k = s; k < e; k++) emoji.add(k);
  }
  for (const m of text.matchAll(TAG_FLAG_RE)) {
    const s = cpIndex.get(m.index), e = cpIndex.get(m.index + m[0].length);
    for (let k = s; k < e; k++) emoji.add(k);
  }
  let stack = [], i = 0;
  const isTag = (c) => { const v = c.codePointAt(0); return v >= 0xe0000 && v <= 0xe007f; };
  while (i < n) {
    const c = chars[i], code = c.codePointAt(0);
    if (isTag(c) && !emoji.has(i)) {
      let j = i;
      while (j < n && isTag(chars[j]) && !emoji.has(j)) j++;
      const hidden = chars.slice(i, j).map((t) => t.codePointAt(0)).filter((v) => v >= 0xe0020 && v <= 0xe007e)
        .map((v) => String.fromCodePoint(v - 0xe0000)).join("");
      add("tag_text", i, j, `${j - i} tag character(s)`, {decoded: hidden});
      i = j;
      continue;
    }
    if (isSelector(c)) {
      if (emoji.has(i) && i + 1 < n && isSelector(chars[i + 1])) i++;
      let j = i;
      while (j < n && isSelector(chars[j])) j++;
      if (j - i >= 4) {
        const bytes = chars.slice(i, j).map((s) => { const v = s.codePointAt(0); return v <= 0xfe0f ? v - 0xfe00 : v - 0xe0100 + 16; });
        add("variation_payload", i, j, `${j - i} selector(s) in a row`, {decoded: decodeBackslash(bytes)});
      } else if (j - i > 1) {
        add("variation_selector", i, j, `${j - i} selector(s) in a row`);
      } else if (!emoji.has(i) && i && isSelector(chars[i - 1])) {
        add("variation_selector", i, j, "selector after the emoji's own selector");
      } else if (!emoji.has(i) && (!i || /[\p{Z}\p{C}]/u.test(chars[i - 1]))) {
        add("variation_selector", i, j, "no visible base before the selector");
      }
      i = j;
      continue;
    }
    if (emoji.has(i)) { i++; continue; }
    if (c in BIDI_OPEN) {
      const before = found.length;
      add("bidi_control", i, i + 1, BIDI_NAMES[c]);
      if (rules.has("bidi_control") && found.length > before) stack.push([BIDI_OPEN[c], found[found.length - 1]]);
      else if (rules.has("bidi_control")) stack.push([BIDI_OPEN[c], {detail: ""}]);
    } else if (c in BIDI_CLOSE) {
      if (stack.length && stack[stack.length - 1][0] === BIDI_CLOSE[c]) stack.pop();
      add("bidi_control", i, i + 1, BIDI_NAMES[c]);
    } else if ("\n\r\u2028\u2029\x85".includes(c)) {
      for (const [, row] of stack) row.detail += ", not closed before end of line";
      stack = [];
    } else if (BIDI_MARKS.includes(c)) {
      add("bidi_mark", i, i + 1, BIDI_NAMES[c]);
    } else if (ZERO_WIDTH.includes(c)) {
      if (c === "\ufeff" && i === 0 && bom) { i++; continue; }
      let j = i;
      while (j < n && ZERO_WIDTH.includes(chars[j]) && !emoji.has(j)) j++;
      const left = i ? chars[i - 1] : "", right = j < n ? chars[j] : "";
      const joined = j - i === 1 && JOINERS.includes(c) && left && right && /[\p{L}\p{M}]/u.test(left) &&
        /[\p{L}\p{M}]/u.test(right) && !UNJOINED_SCRIPTS.has(script(left));
      if (!joined) add("zero_width", i, j, [...new Set(chars.slice(i, j).map((z) => ZERO_WIDTH_NAMES[z]))].join(", "));
      i = j;
      continue;
    } else if (c === "\u00ad") {
      add("soft_hyphen", i, i + 1, "SOFT HYPHEN");
    } else if (FILLERS.includes(c) || (/\p{Cf}/u.test(c) && !SHOWN_FORMAT.has(c))) {
      add("invisible_format", i, i + 1, cpHex(c));
    } else if (/\p{Co}/u.test(c)) {
      let j = i;
      while (j < n && /\p{Co}/u.test(chars[j])) j++;
      add("private_use", i, j, `${j - i} private-use code point(s)`);
      i = j;
      continue;
    }
    i++;
  }
  for (const [, row] of stack) row.detail += ", not closed before end of " + endName;
  if (rules.has("mixed_script")) {
    for (const m of text.matchAll(WORD_RE)) {
      let start = cpIndex.get(m.index), word = Array.from(m[0]);
      if (start && chars[start - 1] === "\\") { start += 1; word = word.slice(1); }
      const scripts = word.map(script);
      const present = HOMOGLYPH_SCRIPTS.filter((s) => scripts.includes(s));
      if (present.length > 1) {
        const count = (s) => scripts.filter((x) => x === s).length;
        const major = present.reduce((a, b) => (count(b) > count(a) ? b : a));
        const odd = word.filter((ch, k) => present.includes(scripts[k]) && scripts[k] !== major);
        add("mixed_script", start, cpIndex.get(m.index + m[0].length), present.join("+") + " in one word",
          {word: word.join(""), odd: odd.slice(0, 16).map(cpHex)});
      }
    }
  }
  if (rules.has("homograph_url")) {
    for (const m of text.matchAll(URL_CANDIDATE_RE)) {
      const urlText = m[0].replace(/[.,;!)\]}]+$/u, "");
      const uStart = cpIndex.get(m.index), uEnd = uStart + Array.from(urlText).length;
      let authority = urlText.includes("://") ? urlText.split("://").slice(1).join("://") : urlText;
      authority = authority.split(/[/?#\\]/u)[0];
      let host = authority.slice(authority.lastIndexOf("@") + 1);
      if (host.startsWith("[")) continue;
      host = host.split(":")[0];
      const labels = host.split(/[.\uff0e\u3002\uff61]/u);
      const decoded = labels.map((label) => {
        if (label.toLowerCase().startsWith("xn--")) {
          const d = domainToUnicode(label.toLowerCase());
          if (d) return [d, true];
        }
        return [label, false];
      });
      const full = decoded.map(([d]) => d).join(".");
      for (const [ch, name] of Object.entries(CONFUSABLE_URL_CHARS)) {
        if (authority.includes(ch)) {
          const level = "\uff0e\u3002\uff61".includes(ch) ? "medium" : "high";
          add("homograph_url", uStart, uEnd, `confusable character ${name} (${cpHex(ch)}) in URL authority`,
            {decoded: full, severity: level});
        }
      }
      labels.forEach((label, k) => {
        const [dec, isPuny] = decoded[k];
        const scripts = new Set(Array.from(dec).filter((ch) => /\p{L}/u.test(ch)).map(script));
        const present = HOMOGLYPH_SCRIPTS.filter((s) => scripts.has(s));
        const prefix = isPuny ? `Punycode label '${label}' decodes to ` : "Domain label ";
        if (present.length > 1) {
          add("homograph_url", uStart, uEnd, `${prefix}mixed-script '${dec}' (${present.join("+")})`, {decoded: full});
        } else if (present.length === 1 && !scripts.has("LATIN") &&
                   Array.from(dec).every((ch) => ASCII_CONFUSABLE_LETTERS.has(ch.toLowerCase()) || "0123456789-".includes(ch))) {
          const name = present[0][0] + present[0].slice(1).toLowerCase();
          add("homograph_url", uStart, uEnd, `${prefix}${name} '${dec}' resembles ASCII letters`, {decoded: full});
        }
      });
    }
  }
  return found.sort((a, b) => a.start - b.start || (a.kind < b.kind ? -1 : a.kind > b.kind ? 1 : 0));
}

function hiddenText(text, {kinds, minSeverity = "low"} = {}) {
  if (typeof text !== "string") throw new TypeError("text must be a string");
  return findings(text, selectRules(kinds, minSeverity), minSeverity);
}

function stripHidden(text, options = {}) {
  const drop = new Set();
  for (const row of hiddenText(text, options))
    if (row.kind !== "mixed_script" && row.kind !== "homograph_url") for (let k = row.start; k < row.end; k++) drop.add(k);
  return Array.from(text).filter((_, k) => !drop.has(k)).join("");
}

module.exports = {hiddenText, stripHidden, hiddenTextRules};

if (require.main === module) {
  const [mode, file] = process.argv.slice(2);
  try {
    const fs = require("node:fs");
    if (!["--hidden-text", "--strip-hidden"].includes(mode) || !file) throw new Error("usage: xprobe.cjs --hidden-text|--strip-hidden FILE|-");
    const text = fs.readFileSync(file === "-" ? 0 : file, "utf8");
    if (mode === "--strip-hidden") process.stdout.write(stripHidden(text));
    else {
      const rows = hiddenText(text);
      process.stdout.write(JSON.stringify(rows, null, 2).replace(/[\u007f-\uffff]/g, (ch) => "\\u" + ch.charCodeAt(0).toString(16).padStart(4, "0")) + "\n");
      process.exitCode = rows.length ? 1 : 0;
    }
  } catch (error) {
    process.stderr.write(`xprobe: ${error.message}\n`);
    process.exitCode = 2;
  }
}
