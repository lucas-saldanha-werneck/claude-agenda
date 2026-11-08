#!/usr/bin/env python3
"""Tests for claude-agenda and launchd-overdue.

Everything runs with a fake HOME in a temp folder and fake tmux / claude / launchctl
(tests/fake_*.py, passed through the CLAUDE_AGENDA_* and LAUNCHD_OVERDUE_LAUNCHCTL overrides).
No real tmux server, Claude session or launchd job is touched. Run: python3 tests/test_claude_agenda.py -v
"""
import datetime
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = os.path.join(ROOT, "tests")
PY = sys.executable
AGENDA = os.path.join(ROOT, "bin", "claude-agenda")
OVERDUE = os.path.join(ROOT, "bin", "launchd-overdue")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = os.path.realpath(self.tmp.name)
        self.home = os.path.join(self.t, "home")
        self.work = os.path.join(self.t, "work")
        os.makedirs(self.home)
        os.makedirs(self.work)
        self.la = os.path.join(self.home, "Library", "LaunchAgents")
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("CLAUDE", "TMUX", "LAUNCHD_OVERDUE"))}
        self.env.update(HOME=self.home, FAKE_DIR=self.t,
                        CLAUDE_AGENDA_LOG_DIR=os.path.join(self.t, "logs"),
                        CLAUDE_AGENDA_TMUX=os.path.join(T, "fake_tmux.py"),
                        CLAUDE_AGENDA_CLAUDE=os.path.join(T, "fake_claude.py"),
                        CLAUDE_AGENDA_LAUNCHCTL=os.path.join(T, "fake_launchctl.py"),
                        LAUNCHD_OVERDUE_LAUNCHCTL=os.path.join(T, "fake_launchctl.py"))

    def tearDown(self):
        for _ in range(20):
            try:
                self.tmp.cleanup()
                return
            except OSError:
                time.sleep(0.2)

    def agenda(self, *args, **env):
        e = dict(self.env, **env)
        return subprocess.run([PY, AGENDA, *args], capture_output=True, text=True, env=e, cwd=self.work)

    def calls(self, tool):
        p = os.path.join(self.t, f"{tool}-calls.jsonl")
        if not os.path.exists(p):
            return []
        with open(p) as f:
            return [json.loads(l) for l in f]

    def tmux_state(self, sessions=None, panes=None):
        with open(os.path.join(self.t, "tmux.json"), "w") as f:
            json.dump({"sessions": sessions or {}, "panes": panes or {}}, f)

    def plist(self, name):
        with open(os.path.join(self.la, name), "rb") as f:
            return plistlib.load(f)


class Add(Base):
    def test_add_writes_plist_and_does_not_load(self):
        r = self.agenda("add", "nightly", "--prefix", "NIGHTLY", "--prompt", "/review-inbox",
                        "--at", "23:30", "--dir", self.work)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("not loaded", r.stdout)
        p = self.plist("com.claude-agenda.nightly.plist")
        self.assertEqual(p["Label"], "com.claude-agenda.nightly")
        self.assertEqual(p["ProgramArguments"][2:], ["run", "NIGHTLY", "/review-inbox", "--dir", self.work])
        self.assertEqual(p["StartCalendarInterval"], {"Hour": 23, "Minute": 30})
        self.assertIn("/.local/bin:", p["EnvironmentVariables"]["PATH"])
        self.assertEqual(self.calls("launchctl"), [])

    def test_add_load_calls_bootstrap(self):
        r = self.agenda("add", "job", "--prefix", "JOB", "--prompt", "hi", "--at", "8:05", "--load")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        c = self.calls("launchctl")
        self.assertEqual(c[-1][0], "bootstrap")
        self.assertTrue(c[-1][2].endswith("com.claude-agenda.job.plist"))

    def test_weekdays_and_custom_prefix(self):
        r = self.agenda("add", "weekly", "--prefix", "W", "--prompt", "x", "--at", "09:00",
                        "--weekday", "mon", "--weekday", "fri", "--label-prefix", "org.example.ai")
        self.assertEqual(r.returncode, 0, r.stderr)
        p = self.plist("org.example.ai.weekly.plist")
        self.assertEqual(p["StartCalendarInterval"],
                         [{"Hour": 9, "Minute": 0, "Weekday": 1}, {"Hour": 9, "Minute": 0, "Weekday": 5}])

    def test_one_time_date(self):
        r = self.agenda("add", "once", "--prefix", "O", "--prompt", "x", "--at", "10:00", "--date", "12-24")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("one-time job", r.stdout)
        self.assertEqual(self.plist("com.claude-agenda.once.plist")["StartCalendarInterval"],
                         {"Hour": 10, "Minute": 0, "Month": 12, "Day": 24})

    def test_bad_input_is_rejected(self):
        self.assertNotEqual(self.agenda("add", "x", "--prefix", "X", "--prompt", "y", "--at", "25:00").returncode, 0)
        self.assertNotEqual(self.agenda("add", "x", "--prefix", "X", "--prompt", "y").returncode, 0)
        self.assertNotEqual(self.agenda("add", "x", "--prefix", "X", "--prompt", "y", "--at", "1:00",
                                        "--date", "02-30").returncode, 0)

    def test_dry_run_writes_nothing(self):
        r = self.agenda("add", "d", "--prefix", "D", "--prompt", "y", "--at", "1:00", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("<key>Label</key>", r.stdout)
        self.assertFalse(os.path.exists(self.la))

    def test_list_and_remove(self):
        self.agenda("add", "a1", "--prefix", "A", "--prompt", "/x", "--at", "07:00", "--weekday", "sun")
        r = self.agenda("list")
        self.assertIn("com.claude-agenda.a1", r.stdout)
        self.assertIn("sun 07:00", r.stdout)
        r = self.agenda("remove", "a1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.la, "com.claude-agenda.a1.plist")))
        self.assertEqual(self.calls("launchctl")[-1][0], "bootout")


class Run(Base):
    def new_sessions(self):
        return [c for c in self.calls("tmux") if c and c[0] == "new-session"]

    def test_opens_session_in_tmux(self):
        self.tmux_state()
        r = self.agenda("run", "REPORT", "/weekly-report", "--dir", self.work)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ns = self.new_sessions()
        self.assertEqual(len(ns), 1)
        c = ns[0]
        self.assertTrue(c[c.index("-s") + 1].startswith("claude-agenda-REPORT-"))
        self.assertEqual(c[c.index("-c") + 1], self.work)
        name = f"REPORT {datetime.datetime.now():%d-%m}"
        self.assertIn(f"-n '\"'\"'{name}'\"'\"'", c[-1])
        self.assertIn("/weekly-report", c[-1])
        self.assertNotIn("--remote-control", c[-1])
        self.assertIn("CLAUDE_CODE_DISABLE_NOTIFICATION_PRESENCE_CHECK=1", c[-1])

    def test_remote_control_flag(self):
        self.tmux_state()
        self.agenda("run", "R", "hi", "--remote-control")
        self.assertIn("--remote-control", self.new_sessions()[0][-1])

    def test_busy_previous_session_skips(self):
        self.tmux_state({"claude-agenda-R-1": int(time.time())}, {"4242": "claude-agenda-R-1"})
        agents = json.dumps([{"kind": "interactive", "name": "R 01-01", "status": "busy", "pid": 4242}])
        r = self.agenda("run", "R", "hi", FAKE_AGENTS=agents)
        self.assertEqual(r.returncode, 0)
        self.assertIn("still working", r.stdout)
        self.assertEqual(self.new_sessions(), [])

    def test_idle_previous_session_is_closed(self):
        self.tmux_state({"claude-agenda-R-1": int(time.time())}, {"4242": "claude-agenda-R-1"})
        agents = json.dumps([{"kind": "interactive", "name": "R 01-01", "status": "idle", "pid": 4242},
                             {"kind": "interactive", "name": "OTHER 01-01", "status": "busy", "pid": 1}])
        r = self.agenda("run", "R", "hi", FAKE_AGENTS=agents)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        kills = [c for c in self.calls("tmux") if c[0] == "kill-session"]
        self.assertEqual(kills, [["kill-session", "-t", "claude-agenda-R-1"]])
        self.assertEqual(len(self.new_sessions()), 1)

    def test_unknown_status_recent_skips_old_is_closed(self):
        self.tmux_state({"claude-agenda-R-1": int(time.time()) - 600, "my-work": 1})
        r = self.agenda("run", "R", "hi", FAKE_AGENTS_FAIL="1")
        self.assertIn("status unknown", r.stdout)
        self.assertEqual(self.new_sessions(), [])
        self.tmux_state({"claude-agenda-R-1": int(time.time()) - 13 * 3600, "my-work": 1})
        r = self.agenda("run", "R", "hi", FAKE_AGENTS_FAIL="1")
        self.assertIn("closing stale", r.stdout)
        kills = [c for c in self.calls("tmux") if c[0] == "kill-session"]
        self.assertEqual(kills, [["kill-session", "-t", "claude-agenda-R-1"]])   # never "my-work"
        self.assertEqual(len(self.new_sessions()), 1)

    def test_dry_run_opens_nothing(self):
        self.tmux_state()
        r = self.agenda("run", "R", "hi", "--dry-run")
        self.assertIn("(dry-run) would run", r.stdout)
        self.assertEqual(self.new_sessions(), [])

    def test_missing_tmux_is_clear_error(self):
        r = self.agenda("run", "R", "hi", CLAUDE_AGENDA_TMUX=os.path.join(self.t, "nope"), PATH="")
        self.assertEqual(r.returncode, 1)
        self.assertIn("tmux not found", r.stdout)
        self.assertNotIn("Traceback", r.stderr)

    def test_log_written(self):
        self.tmux_state()
        self.agenda("run", "LOGGED", "hi")
        with open(os.path.join(self.t, "logs", "claude-agenda.log")) as f:
            self.assertIn("LOGGED: rc=0", f.read())


class Overdue(Base):
    def write(self, label, cal, **extra):
        os.makedirs(self.la, exist_ok=True)
        with open(os.path.join(self.la, label + ".plist"), "wb") as f:
            plistlib.dump(dict(Label=label, ProgramArguments=["/bin/true"], StartCalendarInterval=cal, **extra), f)

    def run_overdue(self, *args, now="2026-11-08T12:00:00"):
        return subprocess.run([PY, OVERDUE, *args], capture_output=True, text=True,
                              env=dict(self.env, LAUNCHD_OVERDUE_NOW=now))

    def setUp(self):
        super().setUp()
        self.write("com.claude-agenda.past", {"Month": 11, "Day": 1, "Hour": 9, "Minute": 0})
        self.write("com.claude-agenda.yesterday-ish", {"Month": 11, "Day": 8, "Hour": 9, "Minute": 0})
        self.write("com.claude-agenda.future", {"Month": 12, "Day": 24, "Hour": 9, "Minute": 0})
        self.write("com.claude-agenda.weekly", {"Weekday": 1, "Hour": 9, "Minute": 0})
        self.write("com.claude-agenda.birthday", {"Month": 3, "Day": 3, "Hour": 9, "Minute": 0})
        self.write("com.claude-agenda.launchd-overdue", {"Month": 1, "Day": 1})
        self.write("org.other.past", {"Month": 1, "Day": 1})
        os.makedirs(os.path.join(self.home, ".config", "launchd-overdue"))
        with open(os.path.join(self.home, ".config", "launchd-overdue", "yearly.txt"), "w") as f:
            f.write("# yearly jobs\ncom.claude-agenda.birthday\n")

    def left(self):
        return sorted(f for f in os.listdir(self.la) if f.endswith(".plist"))

    def test_dry_run_reports_only(self):
        r = self.run_overdue("--dry-run")
        self.assertIn("(dry-run) overdue com.claude-agenda.past", r.stdout)
        self.assertEqual(len(self.left()), 7)
        self.assertEqual(self.calls("launchctl"), [])

    def test_turns_off_only_past_one_time_jobs(self):
        r = self.run_overdue()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("com.claude-agenda.past.plist", self.left())
        self.assertTrue(os.path.exists(os.path.join(self.la, "overdue", "com.claude-agenda.past.plist")))
        for kept in ("yesterday-ish", "future", "weekly", "birthday", "launchd-overdue"):
            self.assertIn(f"com.claude-agenda.{kept}.plist", self.left(), kept)
        self.assertIn("org.other.past.plist", self.left())
        self.assertEqual(self.calls("launchctl"), [["bootout", f"gui/{getattr(os, 'getuid', lambda: 0)()}/com.claude-agenda.past"]])

    def test_custom_prefix(self):
        self.run_overdue("--prefix", "org.other.")
        self.assertNotIn("org.other.past.plist", self.left())
        self.assertIn("com.claude-agenda.past.plist", self.left())


if __name__ == "__main__":
    unittest.main()
