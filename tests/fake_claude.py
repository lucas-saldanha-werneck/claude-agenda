#!/usr/bin/env python3
"""Fake claude: `claude agents --json` prints $FAKE_AGENTS (JSON list); exits 1 if FAKE_AGENTS_FAIL."""
import os, sys
if sys.argv[1:3] == ["agents", "--json"]:
    if os.environ.get("FAKE_AGENTS_FAIL"):
        sys.exit(1)
    print(os.environ.get("FAKE_AGENTS", "[]"))
