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
                    if not k.startswith(("CLAUDE", "TMUX", "LAUNCHD_OVERDUE", "XDG_CONFIG_HOME"))}
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

    def test_one_time_date_stores_the_intended_year(self):
        now = dict(CLAUDE_AGENDA_NOW="2026-12-20T15:00:00")
        r = self.agenda("add", "jan", "--prefix", "J", "--prompt", "x", "--at", "09:00", "--date", "01-05", **now)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.plist("com.claude-agenda.jan.plist")["ClaudeAgendaYear"], 2027)
        r = self.agenda("add", "jan2", "--prefix", "J", "--prompt", "x", "--at", "09:00", "--date", "2027-01-05", **now)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.plist("com.claude-agenda.jan2.plist")["ClaudeAgendaYear"], 2027)
        r = self.agenda("add", "xmas", "--prefix", "X", "--prompt", "x", "--at", "09:00", "--date", "12-24", **now)
        self.assertEqual(self.plist("com.claude-agenda.xmas.plist")["ClaudeAgendaYear"], 2026)
        self.assertIn("2027-01-05", self.agenda("list").stdout)

    def test_one_time_date_outside_the_next_occurrence_is_rejected(self):
        now = dict(CLAUDE_AGENDA_NOW="2026-12-20T15:00:00")
        for bad in ("2028-01-05", "2026-01-05", "2026-12-20"):   # launchd would fire it on the wrong day
            r = self.agenda("add", "b", "--prefix", "B", "--prompt", "x", "--at", "09:00", "--date", bad, **now)
            self.assertNotEqual(r.returncode, 0, bad)
            self.assertIn("launchd has no year", r.stderr, bad)
        self.assertFalse(os.path.exists(self.la))

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

    def test_idle_session_in_a_foreign_tmux_session_is_not_killed(self):
        # a resumed "R ..." session living in the user's own tmux session must never take that session down
        self.tmux_state({"main": 1, "claude-agenda-R-1": int(time.time())}, {"4242": "main"})
        agents = json.dumps([{"kind": "interactive", "name": "R 01-01", "status": "idle", "pid": 4242}])
        r = self.agenda("run", "R", "hi", FAKE_AGENTS=agents)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn(["kill-session", "-t", "main"], self.calls("tmux"))
        self.assertIn("idle_outside_tmux", r.stdout)   # default "skip": treated like an idle session outside tmux
        self.assertEqual(self.new_sessions(), [])

    def test_idle_session_in_a_foreign_tmux_session_open_mode(self):
        d = os.path.join(self.home, ".config", "claude-agenda")
        os.makedirs(d)
        with open(os.path.join(d, "config.json"), "w") as f:
            json.dump({"idle_outside_tmux": "open"}, f)
        self.tmux_state({"main": 1}, {"4242": "main"})
        agents = json.dumps([{"kind": "interactive", "name": "R 01-01", "status": "idle", "pid": 4242}])
        r = self.agenda("run", "R", "hi", FAKE_AGENTS=agents)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual([c for c in self.calls("tmux") if c[0] == "kill-session"], [])
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


class Config(Base):
    """Options from ~/.config/claude-agenda/config.json (outside the plugin, so they survive updates)."""

    def config(self, **cfg):
        d = os.path.join(self.home, ".config", "claude-agenda")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "config.json"), "w") as f:
            json.dump(cfg, f)

    def launcher(self, *extra):
        return [PY, os.path.join(T, "fake_launcher.py"), *extra]

    def test_short_form_is_run(self):
        self.tmux_state()
        r = self.agenda("REPORT", "/weekly-report", "--dir", self.work)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ns = [c for c in self.calls("tmux") if c[0] == "new-session"]
        self.assertEqual(len(ns), 1)
        self.assertIn("/weekly-report", ns[0][-1])
        self.assertNotEqual(self.agenda("--bogus").returncode, 0)

    def test_label_prefix_from_config_and_env_wins(self):
        self.config(label_prefix="org.example.jobs")
        self.agenda("add", "n1", "--prefix", "N", "--prompt", "x", "--at", "08:00", "--dir", self.work)
        self.assertEqual(self.plist("org.example.jobs.n1.plist")["Label"], "org.example.jobs.n1")
        self.assertIn("org.example.jobs.n1", self.agenda("list").stdout)
        self.agenda("add", "n2", "--prefix", "N", "--prompt", "x", "--at", "08:00", "--dir", self.work,
                    CLAUDE_AGENDA_LABEL_PREFIX="com.env.")
        self.assertTrue(os.path.exists(os.path.join(self.la, "com.env.n2.plist")))

    def test_launch_command_replaces_tmux_launch(self):
        self.tmux_state()
        self.config(launch_command=self.launcher("{dir}", "--name", "{name}", "--prompt", "{prompt}",
                                                 "--prefix={prefix}", "rc={remote_control}"))
        r = self.agenda("NIGHTLY", "/inbox", "--dir", "some/relative/name")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        name = f"NIGHTLY {datetime.datetime.now():%d-%m}"
        self.assertEqual(self.calls("launcher"), [["some/relative/name", "--name", name, "--prompt", "/inbox",
                                                   "--prefix=NIGHTLY", "rc="]])
        self.assertEqual([c for c in self.calls("tmux") if c[0] == "new-session"], [])
        self.assertIn("NIGHTLY: rc=0 launch_command=", r.stdout)
        with open(os.path.join(self.t, "logs", "claude-agenda-launch.log")) as f:
            self.assertIn("launched", f.read(), "the launcher's output goes to claude-agenda-launch.log")

    def test_launch_command_still_closes_idle_and_respects_busy(self):
        self.config(launch_command=self.launcher("{name}"))
        with open(os.path.join(self.home, ".config", "claude-agenda", "close-self-allow"), "w") as f:
            f.write("# sessions my launcher opens\n^claude-x-\n")   # same allow-list as claude-close-self
        self.tmux_state({"claude-x-1": 1}, {"4242": "claude-x-1"})
        idle = json.dumps([{"kind": "interactive", "name": "R 01-01", "status": "idle", "pid": 4242}])
        self.agenda("R", "hi", FAKE_AGENTS=idle)
        self.assertEqual([c for c in self.calls("tmux") if c[0] == "kill-session"], [["kill-session", "-t", "claude-x-1"]])
        self.assertEqual(len(self.calls("launcher")), 1)
        busy = json.dumps([{"kind": "interactive", "name": "R 01-01", "status": "busy", "pid": 4242}])
        self.agenda("R", "hi", FAKE_AGENTS=busy)
        self.assertEqual(len(self.calls("launcher")), 1, "busy previous session: no new launch")

    def test_launch_command_exit_code_and_dry_run(self):
        self.tmux_state()
        self.config(launch_command=self.launcher())
        r = self.agenda("R", "hi", "--dry-run")
        self.assertIn("(dry-run) would run", r.stdout)
        self.assertEqual(self.calls("launcher"), [])
        r = self.agenda("R", "hi", FAKE_LAUNCH_RC="7")
        self.assertEqual(r.returncode, 7)
        self.assertIn("rc=7", r.stdout)

    def test_bad_launch_command_is_rejected(self):
        self.tmux_state()
        self.config(launch_command="not a list")
        r = self.agenda("R", "hi")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("must be a list", r.stderr)
        self.config(launch_command=self.launcher("{nope}"))
        self.assertIn("placeholders", self.agenda("R", "hi").stderr)

    def test_default_dir_and_dir_aliases(self):
        self.tmux_state()
        other = os.path.join(self.t, "other")
        os.makedirs(other)
        self.config(default_dir=self.work, dir_aliases=["--folder"])
        self.agenda("R", "hi")
        ns = [c for c in self.calls("tmux") if c[0] == "new-session"]
        self.assertEqual(ns[-1][ns[-1].index("-c") + 1], self.work)
        self.agenda("R2", "hi", "--folder", other)
        ns = [c for c in self.calls("tmux") if c[0] == "new-session"]
        self.assertEqual(ns[-1][ns[-1].index("-c") + 1], other)

    def test_stale_hours_and_tools_from_config(self):
        self.config(stale_hours=0.01, tmux=os.path.join(T, "fake_tmux.py"))
        self.tmux_state({"claude-agenda-R-1": int(time.time()) - 600})
        env = {"CLAUDE_AGENDA_TMUX": ""}
        r = self.agenda("R", "hi", FAKE_AGENTS_FAIL="1", **env)
        self.assertIn("closing stale", r.stdout)

    def test_bad_config_json_is_reported(self):
        d = os.path.join(self.home, ".config", "claude-agenda")
        os.makedirs(d)
        with open(os.path.join(d, "config.json"), "w") as f:
            f.write("{nope")
        r = self.agenda("list")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not valid JSON", r.stderr)


class ReviewFixes(Base):
    """Regression tests for the review of the config options."""

    def config(self, **cfg):
        d = os.path.join(self.home, ".config", "claude-agenda")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "config.json"), "w") as f:
            json.dump(cfg, f)

    def launcher(self, *extra):
        return [PY, os.path.join(T, "fake_launcher.py"), *extra]

    def test_typo_of_a_subcommand_is_not_run(self):
        self.tmux_state()
        for typo in (["remov", "nightly"], ["lst", "x"], ["ad", "x"]):
            r = self.agenda(*typo)
            self.assertNotEqual(r.returncode, 0, typo)
            self.assertIn("unknown command", r.stderr, typo)
        self.assertEqual([c for c in self.calls("tmux") if c[0] == "new-session"], [])

    def test_short_form_still_accepts_real_prefixes(self):
        self.tmux_state()
        for prefix in ("REPORT", "ZS ofertas", "weekly-check", "R"):
            r = self.agenda(prefix, "hi", "--dir", self.work)
            self.assertEqual(r.returncode, 0, prefix + r.stdout + r.stderr)
        self.assertEqual(len([c for c in self.calls("tmux") if c[0] == "new-session"]), 4)

    def test_idle_session_outside_tmux_default_logs_how_to_change(self):
        self.tmux_state()
        self.config(launch_command=self.launcher("{name}"), default_dir=self.work)
        idle = json.dumps([{"kind": "interactive", "name": "R 01-01", "status": "idle", "pid": 999999}])
        r = self.agenda("R", "hi", FAKE_AGENTS=idle)
        self.assertIn("idle_outside_tmux", r.stdout)
        self.assertEqual(self.calls("launcher"), [])

    def test_idle_session_outside_tmux_open(self):
        self.tmux_state()
        self.config(launch_command=self.launcher("{name}"), default_dir=self.work, idle_outside_tmux="open")
        idle = json.dumps([{"kind": "interactive", "name": "R 01-01", "status": "idle", "pid": 999999}])
        r = self.agenda("R", "hi", FAKE_AGENTS=idle)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.calls("launcher")), 1)
        busy = json.dumps([{"kind": "interactive", "name": "R 01-01", "status": "busy", "pid": 999999}])
        self.agenda("R", "hi", FAKE_AGENTS=busy)
        self.assertEqual(len(self.calls("launcher")), 1, "a busy previous session still skips the run")

    def test_idle_session_outside_tmux_close_command(self):
        self.tmux_state()
        closer = os.path.join(self.t, "closed.txt")
        self.config(launch_command=self.launcher("{name}"), default_dir=self.work, idle_outside_tmux="close",
                    close_command=[PY, "-c", "import sys; open(sys.argv[1], 'w').write(sys.argv[2])", closer, "{pid}"])
        idle = json.dumps([{"kind": "interactive", "name": "R 01-01", "status": "idle", "pid": 999999}])
        r = self.agenda("R", "hi", FAKE_AGENTS=idle)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(closer) as f:
            self.assertEqual(f.read(), "999999")
        self.assertEqual(len(self.calls("launcher")), 1)

    def test_bad_idle_outside_tmux_value(self):
        self.config(idle_outside_tmux="maybe")
        r = self.agenda("R", "hi", "--dir", self.work)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("idle_outside_tmux", r.stdout + r.stderr)

    def test_launcher_that_backgrounds_does_not_hang(self):
        self.tmux_state()
        self.config(launch_command=[PY, os.path.join(T, "fake_bg_launcher.py")], default_dir=self.work)
        t0 = time.time()
        r = self.agenda("R", "hi")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertLess(time.time() - t0, 10, "run must not wait for the launcher's background child")
        with open(os.path.join(self.t, "logs", "claude-agenda-launch.log")) as f:
            self.assertIn("started in background", f.read())

    def test_launch_command_does_not_need_tmux(self):
        self.config(launch_command=self.launcher("{name}"), default_dir=self.work)
        r = self.agenda("R", "hi", CLAUDE_AGENDA_TMUX=os.path.join(self.t, "nope"), PATH="")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.calls("launcher")), 1)

    def test_dir_aliases_must_be_a_list_of_flags(self):
        for bad in ("--folder", ["folder"], [1]):
            self.config(dir_aliases=bad)
            r = self.agenda("R", "hi", "--dir", self.work)
            self.assertNotEqual(r.returncode, 0, bad)
            self.assertIn("dir_aliases", r.stderr, bad)

    def test_launch_command_with_dir_needs_a_folder(self):
        self.tmux_state()
        self.config(launch_command=self.launcher("{dir}"))
        r = self.agenda("R", "hi")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("default_dir", r.stdout + r.stderr)
        self.assertEqual(self.calls("launcher"), [])
        self.config(launch_command=self.launcher("{name}"))
        self.assertEqual(self.agenda("R", "hi").returncode, 0, "a launcher that ignores the folder needs none")

    def test_config_must_be_an_object_in_both_tools(self):
        d = os.path.join(self.home, ".config", "claude-agenda")
        os.makedirs(d)
        with open(os.path.join(d, "config.json"), "w") as f:
            f.write("[1, 2]")
        r1 = self.agenda("list")
        r2 = subprocess.run([PY, OVERDUE, "--dry-run"], capture_output=True, text=True, env=self.env)
        for r in (r1, r2):
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("must hold a JSON object", r.stderr)


class Overdue(Base):
    def write(self, label, cal, written="2026-01-01T00:00:00", **extra):
        os.makedirs(self.la, exist_ok=True)
        with open(os.path.join(self.la, label + ".plist"), "wb") as f:
            plistlib.dump(dict(Label=label, ProgramArguments=["/bin/true"], StartCalendarInterval=cal, **extra), f)
        t = datetime.datetime.fromisoformat(written).timestamp()
        os.utime(os.path.join(self.la, label + ".plist"), (t, t))

    def run_overdue(self, *args, now="2026-11-08T12:00:00", **env):
        return subprocess.run([PY, OVERDUE, *args], capture_output=True, text=True,
                              env=dict(self.env, LAUNCHD_OVERDUE_NOW=now, **env))

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

    def test_job_for_next_year_is_kept_until_its_date(self):
        # made on 12-20 for 01-05: launchd has no year, so this year's 01-05 must not count
        self.write("com.claude-agenda.jan", {"Month": 1, "Day": 5, "Hour": 9, "Minute": 0}, ClaudeAgendaYear=2027)
        self.run_overdue(now="2026-12-21T08:00:00")
        self.assertIn("com.claude-agenda.jan.plist", self.left())
        self.run_overdue(now="2027-01-07T08:00:00")
        self.assertNotIn("com.claude-agenda.jan.plist", self.left())

    def test_stored_year_in_the_past_is_overdue(self):
        self.write("com.claude-agenda.old", {"Month": 12, "Day": 24, "Hour": 9, "Minute": 0}, ClaudeAgendaYear=2025)
        self.run_overdue()
        self.assertNotIn("com.claude-agenda.old.plist", self.left())

    def test_plist_without_year_uses_the_next_date_after_it_was_written(self):
        # older plists have no ClaudeAgendaYear: the date the add command promised is the next one after the write
        self.write("com.claude-agenda.legacy", {"Month": 1, "Day": 5, "Hour": 9, "Minute": 0}, written="2026-12-20T15:00:00")
        self.run_overdue(now="2026-12-21T08:00:00")
        self.assertIn("com.claude-agenda.legacy.plist", self.left())
        self.run_overdue(now="2027-01-07T08:00:00")
        self.assertNotIn("com.claude-agenda.legacy.plist", self.left())

    def test_custom_prefix(self):
        self.run_overdue("--prefix", "org.other.")
        self.assertNotIn("org.other.past.plist", self.left())
        self.assertIn("com.claude-agenda.past.plist", self.left())

    def write_config(self, **cfg):
        d = os.path.join(self.home, ".config", "claude-agenda")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "config.json"), "w") as f:
            json.dump(cfg, f)

    def test_config_prefixes_yearly_file_and_move_to(self):
        yearly = os.path.join(self.t, "annual.txt")
        with open(yearly, "w") as f:
            f.write("org.other.past\n")
        dest = os.path.join(self.t, "turned-off")
        self.write("org.other.gone", {"Month": 2, "Day": 2})
        self.write_config(overdue_prefixes=["org.other."], yearly_file=yearly, overdue_dir=dest)
        r = self.run_overdue()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("org.other.past.plist", self.left(), "listed in the configured yearly file")
        self.assertTrue(os.path.exists(os.path.join(dest, "org.other.gone.plist")))
        self.assertIn("com.claude-agenda.past.plist", self.left(), "only the configured prefixes")

    def test_label_prefix_from_config_is_the_default(self):
        self.write_config(label_prefix="org.other.")
        self.run_overdue()
        self.assertNotIn("org.other.past.plist", self.left())

    def test_overdue_prefixes_must_be_a_list_of_prefixes(self):
        self.write("com.apple.past", {"Month": 1, "Day": 1})
        for bad in ("com.", ["com"], [""], [5]):
            self.write_config(overdue_prefixes=bad)
            r = self.run_overdue()
            self.assertNotEqual(r.returncode, 0, bad)
            self.assertIn("overdue_prefixes", r.stdout + r.stderr, bad)
        self.assertIn("com.apple.past.plist", self.left())
        self.assertIn("com.claude-agenda.past.plist", self.left())

    def test_label_prefix_without_dot_is_normalized(self):
        self.write("org.otherx.past", {"Month": 1, "Day": 1})
        self.write_config(label_prefix="org.other")
        self.run_overdue()
        self.assertNotIn("org.other.past.plist", self.left())
        self.assertIn("org.otherx.past.plist", self.left(), "org.other means org.other. as in claude-agenda")

    def test_env_overrides_config(self):
        self.write_config(overdue_prefixes=["org.other."])
        self.run_overdue(LAUNCHD_OVERDUE_YEARLY_FILE=os.path.join(self.t, "none.txt"),
                         LAUNCHD_OVERDUE_PREFIX="com.claude-agenda.")
        self.assertNotIn("com.claude-agenda.birthday.plist", self.left(), "the yearly file from env has no entries")
        self.assertIn("org.other.past.plist", self.left())


class AuditFixes2(Base):
    """Regression tests for the second audit (finding ids in the test names' docstrings)."""

    def config(self, **cfg):
        d = os.path.join(self.home, ".config", "claude-agenda")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "config.json"), "w") as f:
            json.dump(cfg, f)

    def launcher(self, *extra):
        return [PY, os.path.join(T, "fake_launcher.py"), *extra]

    def kills(self):
        return [c for c in self.calls("tmux") if c and c[0] == "kill-session"]

    def new_sessions(self):
        return [c for c in self.calls("tmux") if c and c[0] == "new-session"]

    def test_waiting_or_shell_session_is_not_closed(self):
        """LA-12: only "idle" is safe to close; waiting (permission/dialog) and shell follow stale_hours."""
        for status in ("waiting", "shell", None, "something-new"):
            for f in ("tmux-calls.jsonl",):
                p = os.path.join(self.t, f)
                if os.path.exists(p):
                    os.remove(p)
            self.tmux_state({"claude-agenda-R-1": int(time.time()) - 60}, {"4242": "claude-agenda-R-1"})
            a = {"kind": "interactive", "name": "R 01-01", "pid": 4242}
            if status:
                a["status"] = status
            r = self.agenda("run", "R", "hi", FAKE_AGENTS=json.dumps([a]))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(self.kills(), [], status)
            self.assertEqual(self.new_sessions(), [], status)
            self.assertIn("skipped", r.stdout, status)

    def test_waiting_session_older_than_stale_hours_is_closed(self):
        """LA-12: past stale_hours the stale rule applies."""
        self.tmux_state({"claude-agenda-R-1": int(time.time()) - 13 * 3600}, {"4242": "claude-agenda-R-1"})
        a = [{"kind": "interactive", "name": "R 01-01", "status": "waiting", "pid": 4242}]
        r = self.agenda("run", "R", "hi", FAKE_AGENTS=json.dumps(a))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.kills(), [["kill-session", "-t", "claude-agenda-R-1"]])
        self.assertEqual(len(self.new_sessions()), 1)

    def test_waiting_session_outside_tmux_skips(self):
        """LA-12: a waiting session outside tmux is never closed, even with idle_outside_tmux=close."""
        closer = os.path.join(self.t, "closed.txt")
        self.config(launch_command=self.launcher("{name}"), default_dir=self.work, idle_outside_tmux="close",
                    close_command=[PY, "-c", "open(__import__('sys').argv[1], 'w')", closer])
        self.tmux_state()
        a = [{"kind": "interactive", "name": "R 01-01", "status": "waiting", "pid": 999999}]
        r = self.agenda("R", "hi", FAKE_AGENTS=json.dumps(a))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(closer))
        self.assertEqual(self.calls("launcher"), [])

    def test_idle_agent_does_not_take_down_a_busy_one_in_the_same_session(self):
        """LA-07: every agent is looked at before a tmux session is killed."""
        self.tmux_state({"claude-agenda-R-1": int(time.time())}, {"4242": "claude-agenda-R-1", "4343": "claude-agenda-R-1"})
        for other in ({"name": "R 02-01", "status": "busy"}, {"name": "OTHER 01-01", "status": "waiting"}):
            agents = [{"kind": "interactive", "name": "R 01-01", "status": "idle", "pid": 4242},
                      dict(other, kind="interactive", pid=4343)]
            r = self.agenda("run", "R", "hi", FAKE_AGENTS=json.dumps(agents))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(self.kills(), [], other)
            self.assertEqual(self.new_sessions(), [], other)

    def test_failed_close_command_stops_the_run(self):
        """LA-06: if closing the previous session fails, no new session is opened."""
        self.tmux_state()
        self.config(launch_command=self.launcher("{name}"), default_dir=self.work, idle_outside_tmux="close",
                    close_command=[PY, "-c", "raise SystemExit(3)"])
        idle = json.dumps([{"kind": "interactive", "name": "R 01-01", "status": "idle", "pid": 999999}])
        r = self.agenda("R", "hi", FAKE_AGENTS=idle)
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.calls("launcher"), [])
        self.assertIn("close_command", r.stdout)

    @unittest.skipIf(os.name == "nt", "flock is POSIX-only; Windows runs without the lock")
    def test_concurrent_run_of_the_same_prefix_is_skipped(self):
        """LA-08: one run per prefix at a time."""
        import fcntl
        self.tmux_state()
        lockdir = os.path.join(self.t, "logs")
        os.makedirs(lockdir, exist_ok=True)
        with open(os.path.join(lockdir, "claude-agenda-R.lock"), "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            r = self.agenda("run", "R", "hi")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("another run", r.stdout)
            self.assertEqual(self.new_sessions(), [])
            r = self.agenda("run", "OTHER", "hi")   # another prefix is not blocked
            self.assertEqual(len(self.new_sessions()), 1, r.stdout + r.stderr)

    def test_prefix_that_starts_another_prefix_is_not_confused(self):
        """LA-14: R must not treat the sessions of R-X (or "R X") as its own."""
        self.tmux_state({"claude-agenda-R-X-1": int(time.time()) - 13 * 3600})
        r = self.agenda("run", "R", "hi", FAKE_AGENTS_FAIL="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.kills(), [])
        self.tmux_state({"claude-agenda-R-X-1": int(time.time())}, {"4242": "claude-agenda-R-X-1"})
        busy = json.dumps([{"kind": "interactive", "name": "R X 01-01", "status": "busy", "pid": 4242}])
        r = self.agenda("run", "R", "hi", FAKE_AGENTS=busy)
        self.assertNotIn("still working", r.stdout)
        self.assertEqual(len(self.new_sessions()), 2)

    def test_remove_refuses_paths(self):
        """LA-04: a NAME with / or .. never reaches outside LaunchAgents."""
        os.makedirs(os.path.join(self.la, "com.claude-agenda.x"))
        victim = os.path.join(self.la, "victim.plist")
        with open(victim, "w") as f:
            f.write("x")
        for bad in ("com.claude-agenda.x/../victim", "com.claude-agenda.x/../../LaunchAgents/victim"):
            r = self.agenda("remove", bad)
            self.assertNotEqual(r.returncode, 0, bad)
            self.assertTrue(os.path.exists(victim), bad)

    def test_add_does_not_overwrite_without_force(self):
        """LA-02: repeating a name needs --force; the plist is replaced atomically."""
        args = ["add", "dup", "--prefix", "D", "--prompt", "first", "--at", "08:00", "--dir", self.work]
        self.assertEqual(self.agenda(*args).returncode, 0)
        r = self.agenda(*args[:4], "--prompt", "second", *args[6:])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--force", r.stderr)
        self.assertEqual(self.plist("com.claude-agenda.dup.plist")["ProgramArguments"][4], "first")
        r = self.agenda(*args[:4], "--prompt", "second", *args[6:], "--force")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.plist("com.claude-agenda.dup.plist")["ProgramArguments"][4], "second")
        self.assertEqual(sorted(os.listdir(self.la)), ["com.claude-agenda.dup.plist"])

    def test_add_refuses_to_point_into_the_plugin_cache(self):
        """LA-01: a plist must not point at the plugin cache, which the next plugin update deletes."""
        import shutil
        cache_bin = os.path.join(self.home, ".claude", "plugins", "cache", "x", "launchd-agenda", "0.0.0", "bin")
        shutil.copytree(os.path.join(ROOT, "bin"), cache_bin)
        r = subprocess.run([PY, os.path.join(cache_bin, "claude-agenda"), "add", "c", "--prefix", "C",
                            "--prompt", "x", "--at", "08:00", "--dir", self.work],
                           capture_output=True, text=True, env=self.env, cwd=self.work)
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("install.sh", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.la, "com.claude-agenda.c.plist")))


class OverdueAudit2(Overdue):
    def test_failed_bootout_of_a_loaded_job_keeps_the_plist(self):
        """LA-05: the plist is moved only when the job is really unloaded."""
        r = self.run_overdue(FAKE_LAUNCHCTL_FAIL="bootout")   # bootout fails, print says it is still loaded
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("com.claude-agenda.past.plist", self.left())
        self.assertIn("still loaded", r.stdout)
        r = self.run_overdue(FAKE_LAUNCHCTL_FAIL="bootout,print")   # bootout fails because it was not loaded
        self.assertNotIn("com.claude-agenda.past.plist", self.left())

    def test_second_archive_with_the_same_name_keeps_the_first(self):
        """LA-09: an archived plist is never overwritten."""
        dest = os.path.join(self.la, "overdue")
        os.makedirs(dest)
        with open(os.path.join(dest, "com.claude-agenda.past.plist"), "w") as f:
            f.write("older")
        self.run_overdue()
        files = sorted(os.listdir(dest))
        self.assertEqual(len(files), 2, files)
        with open(os.path.join(dest, "com.claude-agenda.past.plist")) as f:
            self.assertEqual(f.read(), "older")
        self.assertTrue(any(f.startswith("com.claude-agenda.past.") and f.endswith(".plist") and f != "com.claude-agenda.past.plist"
                            for f in files), files)


STARTERS = {"config.json": "config.example.json", "close-self-allow": "close-self-allow.example"}
SEED = os.path.join(ROOT, "bin", "claude_agenda_config.py")


def read_bytes(p):
    with open(p, "rb") as f:
        return f.read()


def strip_times(text):
    """Log lines start with a timestamp, and session names hold the time; drop both so two runs can be compared."""
    import re
    return re.sub(r"\d{6,}", "<time>", "\n".join(l[20:] if l[:4].isdigit() else l for l in text.splitlines()))


class Seed(Base):
    """The tools create their config files on first run, from the starters in the repo, and never touch a file
    that already exists."""

    def cfgdir(self):
        return os.path.join(self.home, ".config", "claude-agenda")

    def yearly(self):
        return os.path.join(self.home, ".config", "launchd-overdue", "yearly.txt")

    def assert_seeded(self, folder):
        for name, starter in STARTERS.items():
            self.assertEqual(read_bytes(os.path.join(folder, name)), read_bytes(os.path.join(ROOT, starter)), name)

    def test_missing_files_are_created_with_the_defaults(self):
        r = self.agenda("list")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_seeded(self.cfgdir())
        self.assertEqual(read_bytes(self.yearly()), read_bytes(os.path.join(ROOT, "yearly.example.txt")))
        self.assertEqual(r.stderr, "")

    def test_hook_script_seeds_and_exits_0(self):
        r = subprocess.run([PY, SEED, "--seed"], capture_output=True, text=True, env=self.env)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assert_seeded(self.cfgdir())
        self.assertTrue(os.path.isfile(self.yearly()))

    def test_launchd_overdue_seeds_too(self):
        # a real run in an empty fake HOME: no plists, so nothing to turn off
        r = subprocess.run([PY, OVERDUE], capture_output=True, text=True,
                           env=dict(self.env, LAUNCHD_OVERDUE_LAUNCHCTL=os.path.join(T, "fake_launchctl.py")))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_seeded(self.cfgdir())

    def test_help_dry_run_and_typos_leave_a_missing_config_missing(self):
        runs = [self.agenda("--help"), self.agenda("help"), self.agenda("lsit"),
                self.agenda("add", "job", "--prefix", "J", "--prompt", "/x", "--at", "9:00", "--dry-run"),
                self.agenda("run", "R", "hi", "--dry-run"), self.agenda("R", "hi", "--dry-run"),
                self.agenda("remove", "job", "--dry-run"),
                subprocess.run([PY, OVERDUE, "--dry-run"], capture_output=True, text=True, env=self.env),
                subprocess.run([PY, OVERDUE, "--help"], capture_output=True, text=True, env=self.env)]
        self.assertEqual(len(runs), 9)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".config")), os.listdir(self.home))

    def test_existing_files_are_never_changed(self):
        os.makedirs(self.cfgdir())
        os.makedirs(os.path.dirname(self.yearly()))
        mine = {os.path.join(self.cfgdir(), "config.json"): b'{"stale_hours": 3}\r\n',
                os.path.join(self.cfgdir(), "close-self-allow"): b"^mine-\n",
                self.yearly(): b""}
        for p, data in mine.items():
            with open(p, "wb") as f:
                f.write(data)
            os.utime(p, (1000000000, 1000000000))
        for _ in range(2):
            self.agenda("list")
            subprocess.run([PY, SEED, "--seed"], env=self.env)
        for p, data in mine.items():
            self.assertEqual(read_bytes(p), data, p)
            self.assertEqual(os.stat(p).st_mtime, 1000000000, p)

    def test_env_overrides_are_respected(self):
        alt = os.path.join(self.t, "alt", "my.json")
        xdg = os.path.join(self.t, "xdg")
        allow = os.path.join(self.t, "allow", "list")
        yearly = os.path.join(self.t, "y", "yearly")
        r = self.agenda("list", CLAUDE_AGENDA_CONFIG=alt, XDG_CONFIG_HOME=xdg, CLAUDE_CLOSE_SELF_ALLOW_FILE=allow,
                        LAUNCHD_OVERDUE_YEARLY_FILE=yearly)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(read_bytes(alt), read_bytes(os.path.join(ROOT, "config.example.json")))
        self.assertEqual(read_bytes(allow), read_bytes(os.path.join(ROOT, "close-self-allow.example")))
        self.assertTrue(os.path.isfile(yearly))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".config")))
        self.assertFalse(os.path.exists(os.path.join(xdg, "claude-agenda", "config.json")))
        r = self.agenda("list", XDG_CONFIG_HOME=xdg)
        self.assert_seeded(os.path.join(xdg, "claude-agenda"))

    def test_yearly_file_from_the_config_is_where_it_is_seeded(self):
        os.makedirs(self.cfgdir())
        y = os.path.join(self.t, "mine", "yearly.txt")
        with open(os.path.join(self.cfgdir(), "config.json"), "w") as f:
            json.dump({"yearly_file": y}, f)
        self.agenda("list")
        self.assertTrue(os.path.isfile(y))
        self.assertFalse(os.path.exists(self.yearly()))

    def test_unwritable_place_does_not_crash(self):
        with open(os.path.join(self.home, ".config"), "w") as f:   # a file where the folder should be
            f.write("x")
        r = self.agenda("list")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        r = subprocess.run([PY, SEED, "--seed"], capture_output=True, text=True, env=self.env)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                     "read-only folders are not enforced for Windows or root")
    def test_read_only_folder_does_not_crash(self):
        cfg = os.path.join(self.home, ".config")
        os.makedirs(cfg)
        os.chmod(cfg, 0o500)
        try:
            r = self.agenda("list")
            self.assertEqual(r.returncode, 0, r.stderr)
            r = subprocess.run([PY, SEED, "--seed"], capture_output=True, text=True, env=self.env)
            self.assertEqual((r.returncode, r.stderr), (0, ""))
            self.assertEqual(os.listdir(cfg), [])
        finally:
            os.chmod(cfg, 0o700)

    def test_unreadable_existing_config_is_left_alone(self):
        os.makedirs(self.cfgdir())
        p = os.path.join(self.cfgdir(), "config.json")
        with open(p, "w") as f:
            f.write("{}")
        if os.name != "nt":
            os.chmod(p, 0)
        try:
            subprocess.run([PY, SEED, "--seed"], capture_output=True, env=self.env)
        finally:
            os.chmod(p, 0o600)
        self.assertEqual(read_bytes(p), b"{}")

    def test_seeded_config_behaves_like_no_config(self):
        """Same results with the seeded file as with no file at all: every setting, then whole runs."""
        import importlib.util
        from importlib.machinery import SourceFileLoader
        from unittest import mock
        ld = SourceFileLoader("claude_agenda_cli", AGENDA)
        mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(ld.name, ld))
        ld.exec_module(mod)
        with open(os.path.join(ROOT, "config.example.json"), encoding="utf-8") as f:
            starter = json.load(f)
        env = {k: v for k, v in self.env.items() if not k.startswith("CLAUDE_AGENDA_")}

        def resolve(cfg):
            with mock.patch.dict(os.environ, env, clear=True):
                mod._CONFIG = cfg
                return {
                    "label_prefix": mod.label_prefix(), "claude": mod.claude_cmd(), "tmux": mod.tmux_cmd(),
                    "log_dir": mod.log_dir(), "stale_hours": float(mod.setting("stale_hours", default=12)),
                    "default_dir": mod.setting("default_dir", default=None), "launch": mod.launch_command(),
                    "dir_aliases": mod.shared.string_list(mod.config(), "dir_aliases", "t"),
                    "idle": mod.config().get("idle_outside_tmux", "skip"), "close": mod.config().get("close_command"),
                    "yearly": mod.shared.yearly_path(mod.config()),
                    "overdue_prefixes": list(mod.config().get("overdue_prefixes") or
                                             [mod.shared.normalize_prefix(mod.config().get("label_prefix"))]),
                    "overdue_dir": mod.config().get("overdue_dir") or "default",
                }
        self.assertEqual(resolve({}), resolve(starter))

        # whole runs: with no file (the config path cannot be created, so seeding is skipped) and seeded
        blocker = os.path.join(self.t, "blocker")
        with open(blocker, "w") as f:
            f.write("x")
        os.makedirs(os.path.join(self.la, "overdue-test"), exist_ok=True)
        with open(os.path.join(self.la, "com.claude-agenda.old.plist"), "wb") as f:
            plistlib.dump(dict(Label="com.claude-agenda.old", ProgramArguments=["/bin/true"],
                               StartCalendarInterval={"Month": 1, "Day": 1, "Hour": 9, "Minute": 0}), f)
        jan1 = datetime.datetime(2026, 1, 1).timestamp()   # a plist without a year means the next date after its write
        os.utime(os.path.join(self.la, "com.claude-agenda.old.plist"), (jan1, jan1))
        seeded = os.path.join(self.t, "seeded", "config.json")
        self.tmux_state()
        outs = {}
        for name, path in (("none", os.path.join(blocker, "config.json")), ("seeded", seeded)):
            e = dict(CLAUDE_AGENDA_CONFIG=path)
            runs = [self.agenda("add", "job", "--prefix", "J", "--prompt", "/x", "--at", "9:00", "--dry-run", **e),
                    self.agenda("list", **e),
                    self.agenda("run", "R", "hi", "--dry-run", **e),
                    subprocess.run([PY, OVERDUE, "--dry-run"], capture_output=True, text=True,
                                   env=dict(self.env, LAUNCHD_OVERDUE_NOW="2026-11-08T12:00:00", **e))]
            outs[name] = [(r.returncode, strip_times(r.stdout), r.stderr) for r in runs]
            if name == "seeded":
                self.assertEqual(read_bytes(seeded), read_bytes(os.path.join(ROOT, "config.example.json")))
            else:
                self.assertFalse(os.path.exists(path))
        self.assertEqual(outs["none"], outs["seeded"])
        self.assertIn("(dry-run) overdue com.claude-agenda.old", outs["seeded"][3][1])


if __name__ == "__main__":
    unittest.main()
