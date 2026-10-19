/** Types for xprobe.cjs, the Node twin of xprobe's hidden-text rules. Offsets count code points. */
export type Severity = "low" | "medium" | "high";
export type HiddenTextKind = "tag_text" | "variation_payload" | "bidi_control" | "homograph_url" | "zero_width"
  | "variation_selector" | "invisible_format" | "mixed_script" | "bidi_mark" | "soft_hyphen" | "private_use";
export interface HiddenTextOptions {
  /** One kind or several; default all kinds. */
  kinds?: HiddenTextKind | Iterable<HiddenTextKind> | null;
  /** Default "low". */
  minSeverity?: Severity;
}
export interface HiddenTextFinding {
  kind: HiddenTextKind;
  severity: Severity;
  /** Code-point offsets, end exclusive. */
  start: number;
  end: number;
  length: number;
  /** Up to 16 "U+XXXX" values. */
  codepoints: string[];
  detail: string;
  /** Present for tag_text, variation_payload and homograph_url. */
  decoded?: string;
}
export function hiddenText(text: string, options?: HiddenTextOptions): HiddenTextFinding[];
/** Removes the findings' code points, except mixed_script and homograph_url (visible text). */
export function stripHidden(text: string, options?: HiddenTextOptions): string;
export function hiddenTextRules(): Record<HiddenTextKind, {severity: Severity; about: string}>;
