"""Thin search CLI; the vendorable module remains functions-only."""
import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import xprobe


def main(argv=None):
    parser = argparse.ArgumentParser(description="Search text files without executing targets")
    parser.add_argument("pattern", nargs="?")
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--regex", action="store_true")
    parser.add_argument("--ignore-case", action="store_true")
    parser.add_argument("--include-hidden", action="store_true")
    parser.add_argument("--max-bytes", type=int, default=1_000_000)
    parser.add_argument("--max-matches", type=int, default=1000)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--scan-config", action="store_true")
    modes.add_argument("--env-report", action="store_true")
    modes.add_argument("--corpus", action="store_true")
    modes.add_argument("--junit", help="Read a bounded local JUnit report")
    parser.add_argument("--root", dest="root_option")
    parser.add_argument("--include", action="append")
    parser.add_argument("--exclude-dir", action="append")
    parser.add_argument("--category")
    parser.add_argument("--repository", help="Explicit owner/name for JUnit provenance")
    parser.add_argument("--commit-sha", help="Full SHA from canonical repository metadata")
    parser.add_argument("--report-id", default="junit", help="Unique job/report identity")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--count", type=int)
    parser.add_argument("--format", choices=("json", "jsonl", "text"), default="json")
    args = parser.parse_args(argv)
    root = args.root_option or args.root
    if args.pattern and (args.scan_config or args.env_report or args.corpus or args.junit):
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
            return 2 if report["truncated"] else 0
        if args.corpus:
            cases = (xprobe.generate_cases(seed=args.seed, count=args.count, category=args.category)
                     if args.count is not None else xprobe.known_bad_cases(args.category))
            print(xprobe.corpus_to_json(cases, jsonl=args.format == "jsonl"), end="")
            return 0
        if args.env_report:
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
        print(type(error).__name__, file=sys.stderr)
        return 2
    if args.format == "jsonl":
        # The entire report is one record so errors/skips/truncation survive.
        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    elif args.format == "text":
        for key, value in report.items():
            print(key + ": " + json.dumps(value, ensure_ascii=True, sort_keys=True))
    else:
        print(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2))
    return 2 if errors else (0 if found else 1)


if __name__ == "__main__":
    raise SystemExit(main())
