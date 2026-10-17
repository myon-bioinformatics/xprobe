# First native error sweep: immutable historical corpus

Collected from [Flutter CI run 39034483324](https://github.com/myon-bioinformatics/flutter_navigation_basic/actions/runs/39034483324),
source commit `85491b2632520d9455f2dcecf963309851c239e7`, using the acquisition
workflow and five explicit implementations in that revision's
[`tools/native_error_corpus`](https://github.com/myon-bioinformatics/flutter_navigation_basic/tree/85491b2632520d9455f2dcecf963309851c239e7/tools/native_error_corpus).

The nine conditions comprise two successful array lengths and seven negative
categories: negative length, bounds, null, cast, integer parse, JSON parse, and
integer divide-by-zero. All explicit expectations passed. Dart and Swift each
executed nine native controls. Kotlin executed eight; its JSON parser capability
is explicitly unobserved because the existing JVM test dependencies lack a real
JSON parser. Its original JUnit retains six actual failures and one skip.
Each native CI job also executed all nine inputs through independent Python and
Node implementations. Python/JS operations with no direct cast/null-assert
equivalent use explicit common-contract guards; these are not claims about
identical built-in exception behavior.

`dart.json`, `kotlin.json`, and `swift.json` are the **unaltered receipt bytes**
downloaded from the artifacts. `kotlin-original-junit.xml` is the unaltered Gradle
JUnit. `cases.json` is the explicitly chosen input/expectation specification.
`index.json` records source/run identity, original ZIP digests, archived file
digests and the known gap. The full artifacts additionally contain individual
raw stdout/stderr byte streams and source snapshots; those have 90-day retention.
The records here persist in Git independently of artifact expiration.

The first healthy Flutter Web/Android/iOS builds were executed in run
`39033656033` at `0f50acf3dd5c768bbdb9aaf7b77aef1262deda55`. This sweep verified
unchanged tracked build inputs/toolchain versions and reused those historical
healthy-build results. Each receipt explicitly reports
`healthy_build_executed_current_run: false`. All error probes, Swift probe
compilation, and Python/Node companions were actually executed in the new run.

SDK-free tests verify this archive and exercise the existing JUnit writer/importer
against it. They **do not execute current Dart, Kotlin, Swift or app code**.
This is language-primitive evidence from Dart VM, app JVM/JUnit and a host Swift
CLI, not native UI/OS permission or full application equivalence. Keep raw
diagnostics and source/runtime identities when extending the corpus; do not
silently relabel this historical fixture as current native verification.
