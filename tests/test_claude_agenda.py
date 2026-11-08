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
    def write(self, label, cal, **extra):
        os.makedirs(self.la, exist_ok=True)
        with open(os.path.join(self.la, label + ".plist"), "wb") as f:
            plistlib.dump(dict(Label=label, ProgramArguments=["/bin/true"], StartCalendarInterval=cal, **extra), f)

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


if __name__ == "__main__":
    unittest.main()
