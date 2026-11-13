# Security Policy

## Reporting a vulnerability

Please report it privately: open the repository's **Security** tab and choose **Report a vulnerability**
(https://github.com/lucas-saldanha-werneck/launchd-agenda/security/advisories/new). Please do not open a public issue for a
security problem.

## Supported versions

Only the latest release (0.2.7) is supported. Fixes go into a new release.

## What launchd-agenda accesses

- Writes launchd job files into `~/Library/LaunchAgents/` and runs `launchctl` to load and remove them. Its config lives in `~/.config/claude-agenda/`.
- At the set time a job starts a detached tmux session in the folder you chose and runs your launch command (default: `claude`) with your prompt. That session has the permissions, skills, hooks and MCP servers your own `claude` has in that folder, so schedule only prompts you would run yourself.
- `claude-close-self` closes only the tmux session it was started in, after a short delay.
- Makes no network requests of its own.
