"""Thin search CLI; the vendorable module remains functions-only."""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import xprobe


def main(argv=None):
    parser = argparse.ArgumentParser(description="Search text files without executing targets")
    parser.add_argument("pattern")
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--regex", action="store_true")
    parser.add_argument("--ignore-case", action="store_true")
    parser.add_argument("--include-hidden", action="store_true")
    parser.add_argument("--max-bytes", type=int, default=1_000_000)
    parser.add_argument("--max-matches", type=int, default=1000)
    args = parser.parse_args(argv)
    try:
        report = xprobe.search_files(args.root, args.pattern, regex=args.regex,
                                    ignore_case=args.ignore_case,
                                    include_hidden=args.include_hidden,
                                    max_bytes=args.max_bytes, max_matches=args.max_matches)
    except (OSError, ValueError, LookupError, re.error) as error:
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2))
    return 2 if report["errors"] else (0 if report["matches"] else 1)


if __name__ == "__main__":
    raise SystemExit(main())
