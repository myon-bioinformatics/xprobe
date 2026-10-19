/** Types for xprobe.cjs, the Node twin of xprobe.py's hidden-text rules. */
export type HiddenSeverity = "low" | "medium" | "high";
export type HiddenKind =
  | "tag_text" | "variation_payload" | "bidi_control" | "homograph_url"
  | "zero_width" | "variation_selector" | "invisible_format" | "mixed_script"
  | "bidi_mark" | "soft_hyphen" | "private_use";

export interface HiddenFinding {
  kind: HiddenKind;
  severity: HiddenSeverity;
  /** Code-point offsets, like Python str indices (not UTF-16 units). */
  start: number;
  end: number;
  length: number;
  /** The first 16 code points as "U+XXXX". */
  codepoints: string[];
  /** Python spells Unicode names where this twin writes code points. */
  detail: string;
  /** tag_text: hidden ASCII; variation_payload: bytes as UTF-8; homograph_url: decoded host. */
  decoded?: string;
  /** mixed_script: the word and its minority-script code points. */
  word?: string;
  odd?: string[];
}
export interface HiddenTextOptions {
  /** One kind or several; default every rule. */
  kinds?: HiddenKind | HiddenKind[];
  /** Drops findings below this level; default "low". */
  minSeverity?: HiddenSeverity;
}

export function hiddenText(text: string, options?: HiddenTextOptions): HiddenFinding[];
/** The text without reported characters (mixed_script and homograph_url findings are kept). */
export function stripHidden(text: string, options?: HiddenTextOptions): string;
export function hiddenTextRules(): Record<HiddenKind, {severity: HiddenSeverity; about: string}>;
