#!/usr/bin/env python3
"""Fake launcher that starts a long-lived child holding its stdout/stderr (like a launcher that
backgrounds claude), then exits at once."""
import os, subprocess, sys

subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
print("started in background")
sys.exit(0)
