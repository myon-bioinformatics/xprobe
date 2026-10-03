"""Exercise the owning CLI used by CI; collector success is not pytest success."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('source,options,status', [
    (None, [], 2),
    ('<testsuites>', [], 2),
    ('<testsuite><testcase name="one"><failure/></testcase>'
     '<testcase name="two"><error/></testcase></testsuite>', ['--max-matches=1'], 2),
    ('<testsuite><testcase name="ok"/></testsuite>', [], 0),
    ('<testsuite><testcase name="bad"><failure/></testcase></testsuite>', [], 0),
])
def test_collector_does_not_hide_invalid_or_truncated_reports(tmp_path, source, options, status):
    report = tmp_path / 'junit.xml'
    if source is not None:
        report.write_text(source, encoding='utf-8')
    result = subprocess.run(
        [sys.executable, str(ROOT / 'scripts/xprobe_cli.py'), '--junit', str(report),
         '--repository=owner/repo', '--report-id=sample', *options],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == status
    if source is None or source == '<testsuites>':
        assert not result.stdout  # No empty success report synthesized on error.
    else:
        imported = json.loads(result.stdout)
        assert imported['truncated'] is bool(options)
        assert all(row['context']['commit_sha'] is None for row in imported['cases'])
