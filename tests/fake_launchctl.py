#!/usr/bin/env python3
"""Fake launchctl: records each call in $FAKE_DIR/launchctl-calls.jsonl. Never touches launchd.
$FAKE_LAUNCHCTL_FAIL: comma-separated subcommands that exit 1 (e.g. "bootout,print")."""
import json, os, sys
with open(os.path.join(os.environ["FAKE_DIR"], "launchctl-calls.jsonl"), "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\n")
fail = [x for x in os.environ.get("FAKE_LAUNCHCTL_FAIL", "").split(",") if x]
sys.exit(1 if sys.argv[1:2] and sys.argv[1] in fail else 0)
