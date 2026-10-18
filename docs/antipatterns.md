# Anti-patterns

- **Runtime/test dependency mixing:** Keep development packages in `tests/requirements.txt`; the copied artifact must import with only the standard library.
- **Working-directory import assumptions:** CLI wrappers locate the artifact relative to `__file__`. Verify from an unrelated working directory and copy the artifact alone into a temporary project.
- **False completeness claims:** Report errors, skipped inputs and truncation separately from successful observations. Tests must exercise these boundaries.
- **Inference presented as measurement:** Return observed facts only. Search results do not prove project behavior, and directory names do not establish project or Git identity.
- **Values leaking through context:** Masking only the matched token is insufficient when its surrounding line still contains secrets. Discovery reports omit all values and source lines; raw grep and explicit regression-corpus serialization remain separate contracts.
- **Invented failure inputs:** JUnit traceback/text is not the original target input. Import failed test identities, omit parameter labels/logs, and require explicitly recorded inputs for reproducible regressions.
- **Silent partial scans:** A candidate bound can be reached before enough classified findings exist. Report the truncation reason rather than presenting an incomplete scan as a complete empty result.
- **Printing what a hidden-text scan found:** Writing a matched bidi override or tag run to a terminal or log reorders or hides that output too. Report code points and ASCII-escaped `decoded` text; never echo the raw characters.
- **Escape letters read as words:** In JSON or source text, `\n` followed by Cyrillic is one regex word (`n` + Cyrillic), which looked like a Latin/Cyrillic homoglyph. Drop a letter right after a backslash before judging scripts.
- **Invisible characters written into source by tooling:** Editors and generators can turn `\u200d` / `\ufe0f` escapes into the raw characters, which then hide inside string literals. Keep such characters escaped and let `--hidden-text` catch regressions.
- **Treating every zero-width or direction character as an attack:** U+200B is a common line-break hint on real pages, ZWNJ/ZWJ are spelling in Persian and Indic scripts, and RTL text needs direction marks. Severity separates these from tag text and bidi overrides; the scan reports, a reviewer decides.
