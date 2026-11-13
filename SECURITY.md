# Security Policy

## Reporting a vulnerability

Please report it privately: open the repository's **Security** tab and choose **Report a vulnerability**
(https://github.com/lucas-saldanha-werneck/launchd-agenda/security/advisories/new). Please do not open a public issue for a
security problem.

## Supported versions

Only the latest release is supported. Fixes go into a new release.

## What launchd-agenda accesses

- Writes launchd job files into `~/Library/LaunchAgents/` and runs `launchctl` to load and remove them. The job file stores your prompt in plain text and passes it on the command line. `install.sh` copies the tools into `~/.local/bin` and writes a daily `launchd-overdue` job (08:00 and at login). That job turns off finished one-time jobs with your label prefix and moves their files to `~/Library/LaunchAgents/overdue/`.
- Config lives in `~/.config/claude-agenda/` and `~/.config/launchd-overdue/yearly.txt`, created on first run. Logs and lock files go to `~/Library/Logs/` (or `~/.local/state/` off macOS). The launch log records the full `launch_command` line, including the prompt.
- At the set time a job runs `claude agents --json` and closes the previous session of the same prefix when it is idle: it kills a tmux session that it opened, or, with `idle_outside_tmux: "close"`, stops the Claude process with SIGTERM or your `close_command`.
- It then opens a detached tmux session in the folder you chose and runs `claude` with your prompt through your login shell, or your own `launch_command`. With `--remote-control`, you can follow and steer it from the Claude app. That session has the permissions, skills, hooks and MCP servers your own `claude` has in that folder, so schedule only prompts you would run yourself.
- `claude-close-self` closes only the tmux session it was started in, after a short delay, and only when that session's name starts with `claude-agenda-` or matches your allow-list.
- Makes no network requests of its own; the `claude` it starts does.
