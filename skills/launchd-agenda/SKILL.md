---
name: launchd-agenda
description: Schedule a Claude Code session to run on this Mac at a set time with launchd, locally, with the user's skills, hooks, MCP servers and files, through the `claude-agenda` command. Use when the user says "schedule this", "run /some-skill every Monday at 9", "every night at 23:00 do X", "tomorrow at 8 run Y", "agenda", "agendar", "list the scheduled Claude jobs", "remove that schedule", or asks for a local cron for Claude. Not for cloud routines, which run on a remote machine.
version: "0.3.0"
metadata:
  author: Lucas Saldanha Werneck <lucas@2olhares.com>
  tags: [macos, launchd, schedule, cron, tmux]
---

# launchd-agenda

## Purpose

Schedule a launchd job, through the `claude-agenda` command, that opens an interactive Claude Code session
(in a detached tmux session) at the given times, with a prompt as the first message. macOS only.
The command keeps its name; the skill is called `launchd-agenda`.

## Instructions

1. Find the command (`command -v claude-agenda`); if it is missing, tell the user to run `./install.sh`.
2. Read `~/.config/claude-agenda/config.json` if it exists (label prefix, default folder, launcher).
3. Build the `claude-agenda add NAME --prefix PREFIX --prompt "TEXT" --at HH:MM ...` call and run it with `--dry-run`.
4. Show the schedule in one line; add `--load` when the user already asked for it, otherwise ask first.
5. Confirm with `claude-agenda list` and `launchctl print gui/$(id -u)/<label>`.

## Find the command

1. `command -v claude-agenda` - use it if found (installed by `install.sh`, path stays stable).
2. Otherwise tell the user to run `./install.sh` from the plugin folder
   (`${CLAUDE_PLUGIN_ROOT}/install.sh`). Do not write a plist that points into the plugin cache:
   that path changes on every plugin update and the job would break.

## Create a job

```
claude-agenda add NAME --prefix PREFIX --prompt "TEXT" --at HH:MM \
  [--weekday mon --weekday fri] [--day 15] [--date YYYY-MM-DD] \
  [--dir /path/to/project] [--remote-control] [--load] [--force]
```

- `NAME`: short job id (letters, digits, dashes). The launchd label is `<label-prefix><NAME>`.
- `PREFIX`: short upper-case tag for the session title (`PREFIX DD-MM`). A previous session with the
  same prefix is closed if idle, and the run is skipped if it is still working or waiting for a
  permission or an answer.
- `--prompt`: the first message, often a slash command (`/weekly-report`). End it with
  "When done, run `claude-close-self`." so the session closes itself after the final answer.
- `--dir`: the folder the session opens in (default: current folder).
- `--date`: one-time job, the next such date within 12 months (launchd has no year; a YYYY for a later year is refused). `launchd-overdue` turns it off after the date.
- `--remote-control`: start the session with Remote Control, to follow it from the app or phone.
- `--force`: replace an existing job with the same NAME (without it, `add` refuses). Use it only
  when the user wants that job changed.
- No `--weekday`/`--day`/`--date` = every day.

Steps:
1. Run the command with `--dry-run` first and show the user the schedule in one line.
2. If the user already asked for the schedule, run it again with `--load`. Otherwise ask first.
3. Confirm with `claude-agenda list` and `launchctl print gui/$(id -u)/<label>` (look for `state`).

## Other commands

- `claude-agenda list` - jobs with this label prefix and their times.
- `claude-agenda remove NAME` - unloads and deletes the job.
- `claude-agenda run PREFIX "PROMPT" --dir DIR --dry-run` - shows what a run would do, opens nothing.
- `launchd-overdue --dry-run` - lists one-time jobs whose date has passed.

## Settings

The user's settings are in `~/.config/claude-agenda/config.json` (label prefix, default folder, their
own `launch_command`, the yearly-jobs file, ...) and `~/.config/claude-agenda/close-self-allow` (extra
tmux session names `claude-close-self` may close). Both are outside the plugin, so they survive updates.
Read them before creating a job if they exist: the label prefix there is the one `add` uses, and with a
`launch_command` the session is opened by the user's launcher, not by tmux directly. The README lists every
key. `claude-agenda PREFIX "PROMPT"` (no `run`) is accepted too, for jobs written by hand.

Logs: `~/Library/Logs/claude-agenda.log` (each run), `~/Library/Logs/claude-agenda.out` (launchd output).

## Examples

- "Every Monday at 9 run /weekly-report in ~/code/my-app":
  `claude-agenda add weekly-report --prefix REPORT --at 09:00 --weekday mon --dir ~/code/my-app --prompt "/weekly-report. When done, run claude-close-self." --load`
  (after a `--dry-run`); a session titled `REPORT DD-MM` opens every Monday at 09:00.
- "Tomorrow at 8 run Y": a one-time job with `--date YYYY-MM-DD --at 08:00`; `launchd-overdue` turns it off after the date.
- "List the scheduled Claude jobs": `claude-agenda list` prints each job with its times and prompt.
- "Remove that schedule": `claude-agenda remove NAME` unloads and deletes the job.

## Prerequisites

- macOS (launchd), `python3` 3.8+, `tmux` and Claude Code (`claude`).
- The `claude-agenda` command, installed by `install.sh` (not run from the plugin cache, whose path changes on every update).

## Limitations

- Scheduling is macOS only; on Linux nothing schedules the jobs.
- launchd has no year: a `--date` job fires on the next such date within 12 months.
- A run is skipped while the previous session with the same prefix is working or waiting for a permission or an answer.

## Troubleshooting

- A job did not run or failed: read `~/Library/Logs/claude-agenda.log` (each run, with the reason for a skip) and `~/Library/Logs/claude-agenda.out` (launchd output).
- Check the job is loaded: `launchctl print gui/$(id -u)/<label>` (look for `state`).
- `add` fails with "already exists": pass `--force` only when the user wants that job replaced.
- Folders protected by macOS (Desktop, Documents, cloud drives) may need Full Disk Access for the `claude` binary, because launchd runs outside the terminal app.
