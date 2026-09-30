# Anti-patterns

- **Runtime/test dependency mixing:** Keep development packages in `tests/requirements.txt`; the copied artifact must import with only the standard library.
- **Working-directory import assumptions:** CLI wrappers locate the artifact relative to `__file__`. Verify from an unrelated working directory and copy the artifact alone into a temporary project.
- **False completeness claims:** Report errors, skipped inputs and truncation separately from successful observations. Tests must exercise these boundaries.
- **Inference presented as measurement:** Return observed facts only. Search results do not prove project behavior, and directory names do not establish project or Git identity.
- **Values leaking through context:** Masking only the matched token is insufficient when its surrounding line still contains secrets. Discovery reports omit all values and source lines; raw grep and explicit regression-corpus serialization remain separate contracts.
- **Invented failure inputs:** JUnit traceback/text is not the original target input. Import failed test identities, omit parameter labels/logs, and require explicitly recorded inputs for reproducible regressions.
- **Silent partial scans:** A candidate bound can be reached before enough classified findings exist. Report the truncation reason rather than presenting an incomplete scan as a complete empty result.
