# claude-agenda

Schedule Claude Code sessions on your Mac with launchd. At the set time a real, interactive
session opens in a detached tmux session, in the folder you chose, with your prompt as the first
message. It runs locally, so it has your skills, hooks, MCP servers, files and keychain.

Why not cloud routines or the app's scheduler: cloud routines run on a remote machine without your
local skills and hooks, and an app scheduler only fires while the app is open. launchd runs with
nothing open, and if the Mac was asleep at the scheduled time it runs the job when the Mac wakes up.

Three tools:

| Tool | What it does |
|---|---|
| `claude-agenda` | `add` / `list` / `remove` launchd jobs; `run` is what launchd calls to open the session |
| `claude-close-self` | Last step of a scheduled prompt: closes its own tmux session after N seconds (default 30), so the final answer reaches the app first. Only acts on sessions opened by claude-agenda |
| `launchd-overdue` | Daily: finds one-time jobs whose date has passed and turns them off (launchd has no year, so a dated job would repeat next year) |

## Example

```
$ claude-agenda add weekly-report --prefix REPORT --at 09:00 --weekday mon \
    --dir ~/code/my-app --prompt "/weekly-report. When done, run claude-close-self." --load
wrote /Users/you/Library/LaunchAgents/com.claude-agenda.weekly-report.plist
loaded com.claude-agenda.weekly-report

$ claude-agenda list
com.claude-agenda.weekly-report  [mon 09:00]  REPORT /weekly-report. When done, run claude-close-self.
```

Every Monday at 09:00 a session titled `REPORT DD-MM` opens in `~/code/my-app`. Watch it with
`tmux attach -t claude-agenda-REPORT-<id>` (the id is in the log), or from the app with
`--remote-control`.

Before opening, a previous `REPORT` session is handled: idle → closed; still working → this run is
skipped. When `claude agents --json` is not available, a previous session is closed only after
`CLAUDE_AGENDA_STALE_HOURS` (default 12).

One-time job: `--date 2026-12-24 --at 10:00`. `launchd-overdue` moves it to
`~/Library/LaunchAgents/overdue/` the day after it ran.

## Install

```
git clone https://github.com/lucas-saldanha-werneck/claude-agenda
cd claude-agenda
./install.sh            # copies the 3 tools to ~/.local/bin and writes the daily launchd-overdue job
./install.sh --load     # same, and loads that job
./install.sh --dry-run  # shows what it would do
```

`install.sh` loads nothing unless you pass `--load`. Jobs you create with `claude-agenda add` are
loaded only with `--load` too.

The plugin adds a skill so you can just ask Claude ("run /weekly-report every Monday at 9"):

```
/plugin marketplace add lucas-saldanha-werneck/claude-agenda
/plugin install claude-agenda@claude-agenda
```

The skill uses the `claude-agenda` installed by `install.sh`, so run that too.

Requires `python3` 3.8+, `tmux` and Claude Code (`claude`).

## Settings

| Environment variable | Default | What it does |
|---|---|---|
| `CLAUDE_AGENDA_LABEL_PREFIX` | `com.claude-agenda.` | launchd label prefix (also `--label-prefix`; `install.sh --prefix`) |
| `CLAUDE_AGENDA_CLAUDE` | stable copy if present, else `claude` on PATH | Claude Code binary |
| `CLAUDE_AGENDA_TMUX` | `tmux` on PATH or Homebrew | tmux binary |
| `CLAUDE_AGENDA_LOG_DIR` | `~/Library/Logs` | where `claude-agenda.log` goes |
| `CLAUDE_AGENDA_STALE_HOURS` | `12` | close a previous session of unknown status after this many hours |
| `CLAUDE_CLOSE_SELF_ALLOW` | empty | extra tmux session names (extended regex) `claude-close-self` may close |
| `LAUNCHD_OVERDUE_PREFIX` | `com.claude-agenda.` | prefixes `launchd-overdue` checks (comma-separated; also `--prefix`) |

The session runs through your login shell (`$SHELL -lc`), so your profile's PATH and variables
apply. Jobs that should repeat every year: put the label on a line of
`~/.config/launchd-overdue/yearly.txt`.

## Optional requirements

- **stable-sync** (`~/.local/libexec/claude-stable/claude`): if this fixed-path copy of Claude Code
  exists, claude-agenda uses it, so macOS privacy permissions (Full Disk Access) granted to it keep
  working across updates. Without it, `claude` from PATH is used.
- **`claude agents --json`** (recent Claude Code): tells whether the previous session is idle or
  busy. Without it, the stale-hours rule above is used.
- **Remote Control** (`--remote-control`): to follow the session from the Claude app. Off by default.

## Platform

macOS only for scheduling (launchd). `claude-close-self` and `claude-agenda run` also work on Linux
with tmux, but nothing schedules them there. Tests run on macOS, Linux and Windows (Git Bash) with
fake `tmux`, `claude` and `launchctl`: `python3 tests/test_claude_agenda.py -v && bash tests/run.sh`.

Note on macOS privacy: a session started by launchd runs outside your terminal app, so folders
protected by macOS (Desktop, Documents, cloud drives) may need Full Disk Access for the `claude`
binary itself.

## Uninstall

```
./install.sh --uninstall
```

Removes the 3 tools and the launchd-overdue job. Jobs made with `claude-agenda add` stay; remove
each with `claude-agenda remove NAME`.

## License

MIT

Built with Claude Code
