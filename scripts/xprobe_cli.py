"""Thin search CLI; the vendorable module remains functions-only.

Exit codes for agent and shell callers:

0  matches, or a complete mode result. A finished JUnit import is 0 even when
   the imported tests failed.
1  search found nothing.
2  argparse usage, or a failure that produces no report (invalid input, unreadable
   JUnit, bad regex). Stderr is one JSON object and stdout is empty. A finished
   search or scan whose report lists read errors also exits 2, with that report
   on stdout.
3  truncated JUnit report. Stdout is the partial report (``truncated`` true)
   and stderr is one JSON object with ``code`` ``truncated``. Exit 3 is only
   the JUnit case limit, so it does not collide with usage.

Search skips and truncation stay inside the JSON result and do not change 0 or 1.
A JUnit file over ``--max-bytes`` is exit 2 (no report), not exit 3.

``xprobe.cjs`` launches ``xprobe.py`` only, not this advanced CLI; JUnit importer flags are unavailable there.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import xprobe

EXIT_OK = 0
EXIT_NO_MATCH = 1
EXIT_ERROR = 2
EXIT_TRUNCATED = 3

EXIT_HELP = """
Exit codes:
  0  matches, or a complete result (a finished JUnit import is 0 even when tests failed)
  1  search found nothing
  2  usage, or a failure with no report (JSON on stderr, stdout empty)
  3  truncated JUnit report; partial report JSON on stdout; stderr code truncated

Search skips and truncation stay inside the JSON and do not change 0 or 1.
Exit 3 is only the JUnit case limit, so it does not collide with argparse usage (2).
A JUnit file over --max-bytes is exit 2 (no report), not exit 3.
""".strip()


def emit_failure(code, error, exit_code, message=None):
    """Print one ASCII JSON object on stderr. Do not include file or pattern text."""
    payload = {"ok": False, "code": code, "error": error, "exit": exit_code}
    if message:
        payload["message"] = message
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True), file=sys.stderr)


class AgentArgumentParser(argparse.ArgumentParser):
    """Usage errors stay exit 2 and are JSON, not a truncated JUnit report."""

    def error(self, message):
        emit_failure("usage", "usage", EXIT_ERROR, message)
        self.exit(EXIT_ERROR)


def _failure_code(error):
    if isinstance(error, OSError):
        return "io_error"
    if isinstance(error, re.error):
        return "regex"
    if isinstance(error, LookupError):
        return "lookup"
    return "invalid_input"


def main(argv=None):
    parser = AgentArgumentParser(
        description="Search text files without executing targets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EXIT_HELP,
    )
    parser.add_argument("pattern", nargs="?", help="Literal or regular-expression text to search for")
    parser.add_argument("root", nargs="?", default=".", help="File or directory to search (default: .)")
    parser.add_argument("--regex", action="store_true", help="Treat pattern as a Python regular expression")
    parser.add_argument("--ignore-case", action="store_true", help="Match without case sensitivity")
    parser.add_argument("--include-hidden", action="store_true", help="Search hidden files and directories")
    parser.add_argument("--max-bytes", type=int, default=1_000_000,
                        help="Maximum bytes read from each file or the JUnit report (default: 1000000)")
    parser.add_argument("--max-matches", type=int, default=1000,
                        help="Maximum matches, findings, or JUnit cases (default: 1000)")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--scan-config", action="store_true", help="Discover configuration keys under --root")
    modes.add_argument("--env-report", action="store_true",
                       help="Report recognized environment variable names without values")
    modes.add_argument("--corpus", action="store_true", help="Emit the built-in regression corpus")
    modes.add_argument("--factor-cases", action="store_true", help="Emit seeded factor-generation cases")
    modes.add_argument("--junit", help="Read a bounded local JUnit report and print failure identities as JSON")
    parser.add_argument("--root", dest="root_option",
                        help="Root for discovery modes; overrides the positional root")
    parser.add_argument("--include", action="append",
                        help="Glob of files to include; repeat to add another (replaces the default)")
    parser.add_argument("--exclude-dir", action="append",
                        help="Directory name to skip; repeat to add another")
    parser.add_argument("--category", help="Corpus category filter, such as git or json")
    parser.add_argument("--repository", help="Explicit owner/name for JUnit provenance")
    parser.add_argument("--commit-sha", help="Full SHA from canonical repository metadata")
    parser.add_argument("--report-id", default="junit", help="Unique job/report identity (default: junit)")
    parser.add_argument("--seed", type=int, default=0, help="Seed for corpus or factor generation (default: 0)")
    parser.add_argument("--count", type=int, help="Number of generated corpus or factor cases")
    parser.add_argument("--format", choices=("json", "jsonl", "text"), default="json",
                        help="Output format: json (default), jsonl, or text")
    args = parser.parse_args(argv)
    root = args.root_option or args.root
    if args.pattern and (args.scan_config or args.env_report or args.corpus or args.junit or args.factor_cases):
        parser.error("discovery/corpus modes take --root, not a search pattern")
    try:
        if args.junit:
            if args.max_bytes <= 0:
                raise ValueError("max-bytes must be positive")
            with Path(args.junit).open("rb") as stream:
                data = stream.read(args.max_bytes + 1)
            if len(data) > args.max_bytes:
                raise ValueError("JUnit exceeds byte limit")
            report = xprobe.cases_from_junit(data.decode("utf-8"),
                                             max_bytes=args.max_bytes, max_cases=args.max_matches,
                                             repository=args.repository, commit_sha=args.commit_sha,
                                             report_id=args.report_id)
            print(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2))
            if report["truncated"]:
                emit_failure("truncated", "truncated", EXIT_TRUNCATED,
                             "JUnit case limit reached; partial report is on stdout")
                return EXIT_TRUNCATED
            return EXIT_OK
        if args.corpus:
            cases = (xprobe.generate_cases(seed=args.seed, count=args.count, category=args.category)
                     if args.count is not None else xprobe.known_bad_cases(args.category))
            print(xprobe.corpus_to_json(cases, jsonl=args.format == "jsonl"), end="")
            return EXIT_OK
        if args.factor_cases:
            count = 20 if args.count is None else args.count
            report = xprobe.generate_factor_cases(seed=args.seed, count=count)
            found, errors = True, False
        elif args.env_report:
            report = {"environment": xprobe.inspect_environment(os.environ)}
            found, errors = bool(report["environment"]), False
        elif args.scan_config:
            options = {}
            if args.include is not None:
                options["include"] = args.include
            if args.exclude_dir is not None:
                options["exclude_dirs"] = args.exclude_dir
            report = xprobe.scan_config(root, max_bytes=args.max_bytes,
                                        max_findings=args.max_matches, **options)
            found, errors = bool(report["findings"]), bool(report["errors"])
        else:
            if args.pattern is None:
                parser.error("a pattern or an explicit discovery/corpus mode is required")
            report = xprobe.search_files(root, args.pattern, regex=args.regex,
                                        ignore_case=args.ignore_case,
                                        include_hidden=args.include_hidden,
                                        max_bytes=args.max_bytes, max_matches=args.max_matches,
                                        include=args.include or ("*",),
                                        exclude_dirs=args.exclude_dir or ())
            found, errors = bool(report["matches"]), bool(report["errors"])
    except (OSError, ValueError, LookupError, re.error) as error:
        # Avoid echoing invalid values or path contents in diagnostics.
        emit_failure(_failure_code(error), type(error).__name__, EXIT_ERROR)
        return EXIT_ERROR
    if args.format == "jsonl":
        # The entire report is one record so errors/skips/truncation survive.
        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    elif args.format == "text":
        for key, value in report.items():
            print(key + ": " + json.dumps(value, ensure_ascii=True, sort_keys=True))
    else:
        print(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2))
    return EXIT_ERROR if errors else (EXIT_OK if found else EXIT_NO_MATCH)


if __name__ == "__main__":
    raise SystemExit(main())
