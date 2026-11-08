#!/usr/bin/env python3
"""Fake launchctl: records each call in $FAKE_DIR/launchctl-calls.jsonl. Never touches launchd."""
import json, os, sys
with open(os.path.join(os.environ["FAKE_DIR"], "launchctl-calls.jsonl"), "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\n")
