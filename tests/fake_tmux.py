#!/usr/bin/env python3
"""Fake tmux for tests. State in $FAKE_DIR/tmux.json: {"sessions": {name: created}, "panes": {pid: name}}.
Every call is appended to $FAKE_DIR/tmux-calls.jsonl."""
import json, os, sys

d = os.environ["FAKE_DIR"]
sf = os.path.join(d, "tmux.json")
st = json.load(open(sf)) if os.path.exists(sf) else {"sessions": {}, "panes": {}}
a = sys.argv[1:]
with open(os.path.join(d, "tmux-calls.jsonl"), "a") as f:
    f.write(json.dumps(a) + "\n")
cmd = a[0] if a else ""
if cmd == "list-sessions":
    if not st["sessions"]:
        sys.stderr.write("no server running\n")
        sys.exit(1)
    for n, c in st["sessions"].items():
        print(f"{n} {c}")
elif cmd == "list-panes":
    for pid, n in st["panes"].items():
        print(f"{pid} {n}")
elif cmd == "kill-session":
    st["sessions"].pop(a[a.index("-t") + 1], None)
elif cmd == "new-session":
    st["sessions"][a[a.index("-s") + 1]] = 0
json.dump(st, open(sf, "w"))
