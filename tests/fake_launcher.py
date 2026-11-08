#!/usr/bin/env python3
"""Fake launch_command for tests: appends its arguments to $FAKE_DIR/launcher-calls.jsonl; exits $FAKE_LAUNCH_RC."""
import json, os, sys

with open(os.path.join(os.environ["FAKE_DIR"], "launcher-calls.jsonl"), "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\n")
print("launched")
sys.exit(int(os.environ.get("FAKE_LAUNCH_RC", "0")))
