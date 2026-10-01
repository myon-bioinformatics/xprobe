# Standalone runtime design

The primary deliverable is the reusable stdlib-only xprobe.py artifact plus
its guarded direct entry point, along the same copy-one-file pattern as
markdown/ascii_artist. Tests validate that artifact; they are not its purpose.

Default: inspect common local source/config locations, show categories and
source locations, then provide review suggestions. Never execute targets or
turn a heuristic text match into a vulnerability/bug claim. Scope/limits and
unreadable/skipped files remain visible.

Explicit --search: use the existing literal file-search implementation with
default generated-directory exclusions. This opt-in mode includes raw lines.

Explicit --evidence: use the existing JUnit/native pytest support as an optional
input, not a runtime dependency or a default prerequisite. No reports are
downloaded/generated, no test environment is installed, and no failure input
or root cause is invented. The old importable APIs/advanced CLI stay compatible.

Import performs no work. The single file also runs with python -S from another
directory. No shared-module checkout is needed to use the tool.
