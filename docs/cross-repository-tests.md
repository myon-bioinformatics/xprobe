# Cross-repository failure collection

All repositories should emit the same pytest-compatible JUnit format. The
canonical importer is xprobe.py; consumers reuse a pinned vendored copy instead
of implementing their own parser. Language-specific test runners can participate
when they emit compatible testsuite/testcase/failure/error XML.

## Producer in each repository

Append `--junitxml=reports/junit.xml` to its existing pytest command, keeping the
existing test exit code. Upload reports as a job-specific Actions artifact with
`if: always()`, including on failures. Do not use `continue-on-error` to hide a
failed test run. xprobe and yourself now do this in their own 7-job matrices;
other repositories require separate adoption changes.

The JUnit file can contain parameter labels, messages and traceback; it is a raw
test artifact, not a share-safe diagnosis. The importer omits those fields from
the compact failure corpus. The compact JSON can still identify test names and
repositories. Artifact upload is separate from Pages publication.

## Shared consumer

```python
import xprobe  # or a pinned vendor/xprobe.py

markdown = xprobe.cases_from_junit(
    markdown_xml,
    repository="myon-bioinformatics/markdown",
    commit_sha=markdown_canonical_sha,
    report_id="linux-py310",
)
ascii_artist = xprobe.cases_from_junit(
    ascii_xml,
    repository="myon-bioinformatics/ascii_artist",
    commit_sha=ascii_canonical_sha,
    report_id="windows-py312",
)
assert not markdown["truncated"] and not ascii_artist["truncated"]
corpus = xprobe.merge_cases(markdown["cases"], ascii_artist["cases"])
jsonl = xprobe.corpus_to_json(corpus, jsonl=True)
```

Repository, SHA and report identity are explicit inputs. No new Git collector
is added: use the canonical producer's record. When no canonical SHA is supplied,
it stays null/not measured. xprobe's own CI uses null until producer adoption;
it does not reinterpret GITHUB_SHA as a measured canonical identity.

Each case ID includes repository, canonical SHA (or unmeasured), report ID and
its failed-test ordinal. Report IDs must distinguish matrix jobs, shards,
individual XML files and rerun attempts. Reimporting the same report deduplicates;
conflicting contents for the same ID fail. Failure order changes affect ordinals;
this is report-level identity rather than a durable test-identity database.

```sh
python scripts/xprobe_cli.py --junit reports/junit.xml \
  --repository myon-bioinformatics/markdown \
  --commit-sha FULL_SHA_FROM_CANONICAL_RECORD \
  --report-id linux-py310-shard1-attempt1
```

Do not invent replay inputs from JUnit. To reproduce a failure, record the
original input explicitly in a separate explained case, and keep its expected
value/exception in the target's regression test. A failure corpus does not run
repository code, repair environments, open issues or submit messages.
