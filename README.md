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
`stale_hours` (default 12; see Settings).

One-time job: `--date 2026-12-24 --at 10:00`. `launchd-overdue` moves it to
`~/Library/LaunchAgents/overdue/` the day after it ran.

## Install

```
git clone https://github.com/lucas-saldanha-werneck/claude-agenda
cd claude-agenda
./install.sh            # copies the 3 tools (and their shared module) to ~/.local/bin and writes the daily launchd-overdue job
./install.sh --load     # same, and loads that job
./install.sh --dry-run  # shows what it would do
```

`install.sh` loads nothing unless you pass `--load`. Without `--prefix`, the launchd-overdue job reads
its prefixes from the config file on each run; with `--prefix`, that prefix is written into the job. Jobs you create with `claude-agenda add` are
loaded only with `--load` too.

The plugin adds a skill so you can just ask Claude ("run /weekly-report every Monday at 9"):

```
/plugin marketplace add lucas-saldanha-werneck/claude-agenda
/plugin install launchd-agenda@launchd-agenda
```

The plugin is called `launchd-agenda` because Claude Code reserves plugin names that start with `claude-`. The skill uses the `claude-agenda` installed by `install.sh`, so run that too.

Requires `python3` 3.8+, `tmux` and Claude Code (`claude`).

## Settings

Settings live in `~/.config/claude-agenda/config.json` (or `$CLAUDE_AGENDA_CONFIG`). **They survive plugin
updates:** the file is outside the plugin folder, and `/plugin update` or a new `install.sh` never touches
it. launchd reads it on every run, so a change applies from the next run. An environment variable wins over
the same setting in the file.

| Config key | Environment variable | Default | What it does |
|---|---|---|---|
| `label_prefix` | `CLAUDE_AGENDA_LABEL_PREFIX` | `com.claude-agenda.` | launchd label prefix for `add`/`list`/`remove` (also `--label-prefix`; `install.sh --prefix`) |
| `claude` | `CLAUDE_AGENDA_CLAUDE` | stable copy if present, else `claude` on PATH | Claude Code binary |
| `tmux` | `CLAUDE_AGENDA_TMUX` | `tmux` on PATH or Homebrew | tmux binary |
| `log_dir` | `CLAUDE_AGENDA_LOG_DIR` | `~/Library/Logs` | where `claude-agenda.log` goes |
| `stale_hours` | `CLAUDE_AGENDA_STALE_HOURS` | `12` | close a previous session of unknown status after this many hours |
| `default_dir` | | the current folder | folder for `run` when the job gives no `--dir` (launchd starts jobs in `/`) |
| `dir_aliases` | | `[]` | other flag names accepted for `--dir` by `run`, such as `["--folder"]`, for jobs written by hand or by an older script (a list; each starts with `-`) |
| `launch_command` | | built-in tmux launch | your own launcher, as a list (below) |
| `idle_outside_tmux` | | `skip` | what to do when the previous session of the same prefix is idle but not in tmux (below): `skip`, `open` or `close` |
| `close_command` | | SIGTERM to the session's process | with `idle_outside_tmux: "close"`, a list with `{pid}`, `{name}`, `{prefix}` that closes it |
| `overdue_prefixes` | `LAUNCHD_OVERDUE_PREFIX` (comma-separated) | `[label_prefix]` | label prefixes `launchd-overdue` checks (also `--prefix`). A list; each ends with `.`, otherwise it refuses to run and logs why |
| `yearly_file` | `LAUNCHD_OVERDUE_YEARLY_FILE` | `~/.config/launchd-overdue/yearly.txt` | labels of dated jobs that should repeat every year, one per line (`#` = comment) |
| `overdue_dir` | `LAUNCHD_OVERDUE_MOVE_TO` | `~/Library/LaunchAgents/overdue` | where `launchd-overdue` moves plists it turns off |

```json
{
  "label_prefix": "com.example.claude.",
  "default_dir": "~/code",
  "stale_hours": 6
}
```

### Your own launcher (`launch_command`)

By default `run` opens the session itself in a detached tmux session. If you already have a script that
opens Claude sessions the way you like (a wrapper that retries, loads secrets, sets a window title...),
give it as `launch_command`: a list whose items may hold `{prefix}`, `{name}` (`PREFIX DD-MM`),
`{prompt}`, `{dir}` (as written in the job), `{dir_abs}` and `{remote_control}` (`1` or empty). The first
item may start with `~`. No shell is involved, so a prompt with quotes or spaces stays one argument.

```json
{ "launch_command": ["~/bin/open-claude", "{dir}", "--detached", "--title", "{name}", "--prompt", "{prompt}"] }
```

Before launching, `run` still skips the run when the previous session with the same prefix is working,
and closes it when it is idle and inside tmux (it finds the session with `claude agents --json`, and its
tmux session from the process). If your launcher opens sessions outside tmux, an idle previous session is
handled by `idle_outside_tmux`: `skip` (default) logs on every run that it skipped and why; `open` opens
the new session beside it; `close` runs `close_command` (or sends SIGTERM to its process) and then opens.

With a launcher, `{dir}` is passed as written, without checking that the folder exists, so the launcher
can resolve its own names. If the launcher uses `{dir}`, the job needs `--dir` or the config needs
`default_dir` (launchd starts jobs in `/`). The launcher runs without pipes, in its own process session,
with its output appended to `claude-agenda-launch.log` in the log folder, so a launcher that leaves Claude
running in the background returns at once; its exit code goes to `claude-agenda.log` (one still running
after 180 s is left running). tmux is not required with a launcher. `--dry-run` prints the command instead
of running it. The stale-hours rule applies only to sessions that claude-agenda opened itself.

### Short form for hand-written jobs

`claude-agenda PREFIX "PROMPT" [--dir DIR]` is the same as `claude-agenda run PREFIX "PROMPT" ...`, so jobs
written by hand that call `claude-agenda PREFIX PROMPT` keep working. A lower-case first word that looks like
a command or a typo of one (`remov`, `lst`, `ad`) is refused as an unknown command instead of opening a
session; prefixes in capitals are always accepted. Such a prefix (or `run`, `add`, `list`, `ls`, `remove`,
`rm`, `help`) needs the long form, `claude-agenda run PREFIX PROMPT`.

### Sessions `claude-close-self` may close

It closes only tmux sessions whose name starts with `claude-agenda-`. To let it close sessions opened by
your own launcher, put one extended regex per line in `~/.config/claude-agenda/close-self-allow` (another
file: `$CLAUDE_CLOSE_SELF_ALLOW_FILE`; blank lines and `#` lines are ignored), or set one regex in
`CLAUDE_CLOSE_SELF_ALLOW`:

```
# sessions opened by my launcher for scheduled jobs
^claude-(NIGHTLY|REPORT)-
```

The session runs through your login shell (`$SHELL -lc`), so your profile's PATH and variables
apply.

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
