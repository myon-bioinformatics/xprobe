"""Zipilogue shared rule ledger: grow slang-like shortenings across turns.

Both peers load the same JSON RuleBook. Early turns stay long while rules are
declared or auto-adopted from repeated phrases; later turns replace long forms
with opaque short tokens (r1, r2, …). Optional crypto envelope stays in
zipilogue.encode/decode — RuleBook is the evolving content channel.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RULEBOOK_VERSION = 1
DEFAULT_THRESHOLD = 3
_MAX_NGRAM = 5
_MIN_NGRAM = 2
_MIN_PHRASE_CHARS = 4
_DECLARE_RE = re.compile(
    r"^(?:rule:\s*(.+?)\s*=>\s*(.+)|::\s*(.+?)\s*=\s*(.+))\s*$",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"\w+")
# Word chars that need a boundary (kana/CJK are written without spaces).
_SPACED_WORD = r"[^\W\u3040-\u30ff\u3400-\u9fff]"


def _bounded(phrase: str) -> str:
    """Escape *phrase*, guarding edges that are spaced-script word chars."""
    body = re.escape(phrase)
    if re.match(_SPACED_WORD, phrase):
        body = rf"(?<!{_SPACED_WORD})" + body
    if re.match(_SPACED_WORD, phrase[-1:]):
        body += rf"(?!{_SPACED_WORD})"
    return body


@dataclass
class Rule:
    id: str
    long: str
    short: str
    count: int = 0
    created_turn: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "long": self.long,
            "short": self.short,
            "count": self.count,
            "created_turn": self.created_turn,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Rule":
        return cls(
            id=str(d["id"]),
            long=str(d["long"]),
            short=str(d["short"]),
            count=int(d.get("count", 0)),
            created_turn=int(d.get("created_turn", 0)),
        )


@dataclass
class RuleBook:
    """Shared rule ledger both sender and receiver load."""

    path: Path | None = None
    version: int = RULEBOOK_VERSION
    turn: int = 0
    threshold: int = DEFAULT_THRESHOLD
    rules: list[Rule] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    proposals: list[dict[str, Any]] = field(default_factory=list)
    next_id: int = 1
    auto_adopt: bool = True

    # --- persistence ---

    @classmethod
    def load(cls, path: str | Path, *, threshold: int | None = None) -> "RuleBook":
        p = Path(path)
        if not p.is_file():
            book = cls(path=p, threshold=threshold or DEFAULT_THRESHOLD)
            return book
        data = json.loads(p.read_text(encoding="utf-8"))
        rules = [Rule.from_dict(r) for r in data.get("rules", [])]
        next_id = int(data.get("next_id", 1))
        if rules:
            max_n = 0
            for r in rules:
                m = re.match(r"^r(\d+)$", r.id)
                if m:
                    max_n = max(max_n, int(m.group(1)))
            next_id = max(next_id, max_n + 1)
        book = cls(
            path=p,
            version=int(data.get("version", RULEBOOK_VERSION)),
            turn=int(data.get("turn", 0)),
            threshold=int(threshold if threshold is not None else data.get("threshold", DEFAULT_THRESHOLD)),
            rules=rules,
            counts={str(k): int(v) for k, v in data.get("counts", {}).items()},
            proposals=list(data.get("proposals", [])),
            next_id=next_id,
            auto_adopt=bool(data.get("auto_adopt", True)),
        )
        return book

    def save(self, path: str | Path | None = None) -> Path:
        p = Path(path) if path is not None else self.path
        if p is None:
            raise ValueError("RuleBook.save needs a path")
        self.path = p
        payload = {
            "version": self.version,
            "turn": self.turn,
            "threshold": self.threshold,
            "auto_adopt": self.auto_adopt,
            "next_id": self.next_id,
            "rules": [r.to_dict() for r in self.rules],
            "counts": self.counts,
            "proposals": self.proposals,
        }
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return p

    def stats(self) -> dict[str, Any]:
        return {
            "turn": self.turn,
            "rules": len(self.rules),
            "proposals": len(self.proposals),
            "tracked_phrases": len(self.counts),
            "threshold": self.threshold,
        }

    # --- declare / ingest ---

    def _alloc_short(self, preferred: str | None = None) -> str:
        if preferred:
            shorts = {r.short for r in self.rules}
            if preferred not in shorts:
                return preferred
        while True:
            short = f"r{self.next_id}"
            self.next_id += 1
            if short not in {r.short for r in self.rules}:
                return short

    def declare(self, long: str, short: str | None = None) -> Rule:
        long_n = _normalize_phrase(long)
        if not long_n:
            raise ValueError("empty long form")
        existing = self._find_by_long(long_n)
        if existing:
            if short and short != existing.short:
                # rebind short if free
                if short not in {r.short for r in self.rules if r.id != existing.id}:
                    existing.short = short
            existing.count = max(existing.count, self.counts.get(long_n, existing.count))
            return existing
        sid = self._alloc_short(short)
        rule = Rule(
            id=sid if re.match(r"^r\d+$", sid) else f"r{self.next_id - 1}",
            long=long_n,
            short=sid,
            count=max(1, self.counts.get(long_n, 0)),
            created_turn=self.turn,
        )
        if not re.match(r"^r\d+$", sid):
            rule.id = sid
        self.rules.append(rule)
        self.counts[long_n] = max(self.counts.get(long_n, 0), rule.count)
        # drop matching proposals
        self.proposals = [p for p in self.proposals if p.get("long") != long_n]
        return rule

    def ingest_line(self, line: str) -> Rule | None:
        """Parse ``rule: long => short`` or ``:: long = short``. Returns Rule or None."""
        m = _DECLARE_RE.match(line.strip())
        if not m:
            return None
        long = (m.group(1) or m.group(3) or "").strip()
        short = (m.group(2) or m.group(4) or "").strip()
        if not long or not short:
            return None
        return self.declare(long, short)

    def _find_by_long(self, long_n: str) -> Rule | None:
        for r in self.rules:
            if r.long == long_n:
                return r
        return None

    def _find_by_short(self, short: str) -> Rule | None:
        for r in self.rules:
            if r.short == short:
                return r
        return None

    # --- observe / auto-adopt ---

    def observe(self, text: str, *, advance_turn: bool = True) -> dict[str, Any]:
        """Count repeated phrases; auto-adopt when count hits threshold.

        Also ingests inline declare lines. Returns a stats dict including
        newly adopted rules.
        """
        adopted: list[dict[str, Any]] = []
        declared: list[dict[str, Any]] = []

        # Inline declare lines (whole line is a declare)
        stripped = text.strip()
        if _DECLARE_RE.match(stripped):
            rule = self.ingest_line(stripped)
            if rule:
                declared.append(rule.to_dict())
                if advance_turn:
                    self.turn += 1
                return {
                    "adopted": adopted,
                    "declared": declared,
                    "turn": self.turn,
                    **self.stats(),
                }

        phrases = _extract_phrases(text)
        # unique phrases this turn, preserving longest-first order for adopt
        seen_this: dict[str, int] = {}
        for phrase in phrases:
            seen_this[phrase] = seen_this.get(phrase, 0) + 1
        for phrase, add in sorted(seen_this.items(), key=lambda kv: len(kv[0]), reverse=True):
            self.counts[phrase] = self.counts.get(phrase, 0) + add
            count = self.counts[phrase]
            existing = self._find_by_long(phrase)
            if existing:
                existing.count = max(existing.count, count)
                continue
            # skip if this phrase is contained in an already-known longer rule
            if any(phrase != r.long and phrase in r.long for r in self.rules):
                continue
            if count >= self.threshold:
                if self.auto_adopt:
                    # skip if contained in a longer phrase also hitting threshold now
                    if any(
                        phrase != other
                        and phrase in other
                        and self.counts.get(other, 0) >= self.threshold
                        for other in seen_this
                    ):
                        continue
                    # one adopt per observe: keep only the longest maximal hit
                    if adopted:
                        continue
                    rule = self.declare(phrase)
                    rule.count = count
                    adopted.append(rule.to_dict())
                else:
                    short = f"r{self.next_id}"
                    prop = {"long": phrase, "short": short, "count": count}
                    if not any(p.get("long") == phrase for p in self.proposals):
                        self.proposals.append(prop)
            elif count >= max(1, self.threshold - 1):
                short_guess = f"r{self.next_id}"
                if not any(p.get("long") == phrase for p in self.proposals) and not self._find_by_long(
                    phrase
                ):
                    self.proposals.append(
                        {"long": phrase, "short": short_guess, "count": count}
                    )

        if advance_turn:
            self.turn += 1
        return {
            "adopted": adopted,
            "declared": declared,
            "turn": self.turn,
            **self.stats(),
        }

    # --- export / import / threshold ---

    def set_threshold(self, n: int) -> None:
        """Tune auto-adopt threshold (must be >= 1). Persists on next save."""
        if n < 1:
            raise ValueError("threshold must be >= 1")
        self.threshold = int(n)

    def export_rules(self, path: str | Path | None = None) -> dict[str, Any]:
        """Export rules (+ meta) for sharing / negotiation merge.

        Writes JSON when ``path`` is given. Returns the payload dict.
        """
        payload = {
            "version": self.version,
            "threshold": self.threshold,
            "auto_adopt": self.auto_adopt,
            "next_id": self.next_id,
            "rules": [r.to_dict() for r in self.rules],
            "proposals": list(self.proposals),
        }
        if path is not None:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return payload

    def import_rules(
        self,
        source: str | Path | dict[str, Any],
        *,
        merge: bool = True,
        adopt_proposals: bool = False,
    ) -> dict[str, Any]:
        """Import rules from another book export or live peer.

        With ``merge=True`` (default), declare each incoming long→short (rebinding
        free shorts). With ``merge=False``, replace ``self.rules`` entirely.
        Optionally adopt foreign proposals as declarations.
        Returns stats: added / updated / proposals_taken.
        """
        if isinstance(source, dict):
            data = source
        else:
            data = json.loads(Path(source).read_text(encoding="utf-8"))
        added = 0
        updated = 0
        if not merge:
            self.rules = []
            self.next_id = int(data.get("next_id", 1))
        for rd in data.get("rules") or []:
            long = str(rd.get("long", ""))
            short = str(rd.get("short", ""))
            if not long:
                continue
            before = self._find_by_long(_normalize_phrase(long))
            rule = self.declare(long, short or None)
            if before is None:
                added += 1
            elif before.short != rule.short or before.long != rule.long:
                updated += 1
            # preserve higher count
            rule.count = max(rule.count, int(rd.get("count", 0)))
        proposals_taken = 0
        if adopt_proposals:
            for prop in data.get("proposals") or []:
                long = str(prop.get("long", ""))
                short = str(prop.get("short") or "") or None
                if not long or self._find_by_long(_normalize_phrase(long)):
                    continue
                self.declare(long, short)
                proposals_taken += 1
        # bump next_id past any rN we now hold
        max_n = self.next_id
        for r in self.rules:
            m = re.match(r"^r(\d+)$", r.id) or re.match(r"^r(\d+)$", r.short)
            if m:
                max_n = max(max_n, int(m.group(1)) + 1)
        self.next_id = max(self.next_id, max_n)
        return {
            "added": added,
            "updated": updated,
            "proposals_taken": proposals_taken,
            "rules": len(self.rules),
        }

    def negotiate(
        self,
        peer_exports: list[str | Path | dict[str, Any]],
        *,
        adopt_proposals: bool = True,
    ) -> dict[str, Any]:
        """Multi-peer merge: import each peer export into this book.

        Models a simple negotiation round where agents share rule dumps and
        converge on a union of long→short mappings.
        """
        rounds: list[dict[str, Any]] = []
        for src in peer_exports:
            rounds.append(self.import_rules(src, merge=True, adopt_proposals=adopt_proposals))
        return {"peers": len(peer_exports), "rounds": rounds, **self.stats()}

    # --- encode / decode ---

    def encode_with_rules(self, text: str) -> str:
        """Replace longest matching long forms with short tokens."""
        if not self.rules:
            return text
        # longest first
        ordered = sorted(self.rules, key=lambda r: len(r.long), reverse=True)
        out = text
        for rule in ordered:
            # case-insensitive replace of the long phrase as a whole span
            pattern = re.compile(_bounded(rule.long), re.IGNORECASE)
            out = pattern.sub(rule.short, out)
        return out

    def decode_with_rules(self, text: str) -> str:
        """Expand short tokens back to long forms (longest short first)."""
        if not self.rules:
            return text
        ordered = sorted(self.rules, key=lambda r: len(r.short), reverse=True)
        out = text
        for rule in ordered:
            # word-boundary-ish: short as whole token
            pattern = re.compile(_bounded(rule.short))
            out = pattern.sub(rule.long, out)
        return out


def _normalize_phrase(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def _extract_phrases(text: str) -> list[str]:
    """Yield candidate multi-word phrases (≥2 words or ≥4 chars) for counting.

    Each distinct phrase in this text is returned once per occurrence
    (overlapping n-grams count separately for each span).
    """
    words = _WORD_RE.findall(text)
    found: list[str] = []
    n = len(words)
    for size in range(_MAX_NGRAM, _MIN_NGRAM - 1, -1):
        for i in range(0, n - size + 1):
            phrase = " ".join(words[i : i + size])
            if len(phrase) >= _MIN_PHRASE_CHARS:
                found.append(phrase.lower() if phrase.isascii() else phrase)
    # also track single long tokens (≥4 chars) as optional 1-grams for slang growth
    for w in words:
        if len(w) >= 6:  # single long words can become slang too
            found.append(w.lower() if w.isascii() else w)
    return found


def parse_declare(text: str) -> tuple[str, str] | None:
    m = _DECLARE_RE.match(text.strip())
    if not m:
        return None
    long = (m.group(1) or m.group(3) or "").strip()
    short = (m.group(2) or m.group(4) or "").strip()
    if not long or not short:
        return None
    return long, short
