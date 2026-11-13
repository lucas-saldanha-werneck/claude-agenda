# Changelog

All notable changes to this project are documented here. Versions follow [Semantic Versioning](https://semver.org/).

## [0.3.0] - 2026-11-13
- Renamed the skill to `launchd-agenda` (the old name broke the skill schema). The `claude-agenda` command keeps its name.
- Skill frontmatter has `version` and `tags`; the skill has Purpose, Prerequisites, Limitations and Troubleshooting sections; the description is in the third person.

## [0.2.7] - 2026-11-13
- Skill author, Instructions and Examples sections.

## [0.2.6] - 2026-11-12
- `--dir` keeps a bare folder name for `claude-open` to resolve.

## [0.2.5] - 2026-11-12
- Fixes from the second audit.

## [0.2.4] - 2026-11-11
- One-time jobs scheduled for next year work; it never kills tmux sessions it did not start.

## [0.2.3] - 2026-11-11
- Maintenance (catalog renamed to `lucas-tools`).

## [0.2.2] - 2026-11-11
- Maintenance (catalog renamed to `lucas-tools`).

## [0.2.1] - 2026-11-09
- Maintenance (short description, catalog install instructions).

## [0.2.0] - 2026-11-08
- Config file (label prefix, your own launch command, default folder, `--dir` aliases), created on first run.
- The plugin is renamed `launchd-agenda`.

## [0.1.0] - 2026-11-08
- First release: schedule local Claude Code sessions with launchd.
