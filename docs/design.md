# Original intent and scope

This module combines the earlier xgrep.py and xfail.py ideas:

1. Reduce repeated troubleshooting searches with built-in configuration/header/key/scheme vocabulary, filtered repository search and explicitly requested environment-name inspection.
2. Preserve explained, deterministic regression inputs gathered from previous failures and make them reusable from pytest or other callers.
3. Keep runtime standard-library-only, single-file and vendor-copyable. External test tools remain in tests/requirements.txt.

Version 0.1 provided basic grep and generic boundary presets. Version 0.2 adds dictionary discovery, a persistent-corpus data contract, seeded corpus sampling and JUnit failure-identity ingestion. It does not infer original inputs or assert that all corpus values should fail every consumer.

Discovery and reproduction have different output needs. Discovery omits values and snippets; a regression corpus must preserve an explicitly supplied original input. The caller chooses what can be recorded or shared. These modes do not execute discovered repository code.

Reference screenshots and earlier descriptions informed the intent, rather than being copied as implementations. Unverified details from unavailable image bytes are not treated as requirements.
