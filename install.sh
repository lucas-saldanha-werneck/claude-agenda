#!/bin/bash
# install.sh - copy claude-agenda, claude-close-self and launchd-overdue into ~/.local/bin and write
# the daily launchd job for launchd-overdue (with your real paths). Loads nothing unless --load.
#
#   ./install.sh [--dry-run] [--load] [--no-overdue-job] [--prefix com.claude-agenda.]
#   ./install.sh --uninstall [--dry-run]
#
# Environment: INSTALL_BIN_DIR (default ~/.local/bin).
set -u
R="$(cd "$(dirname "$0")" && pwd)"
BIN="${INSTALL_BIN_DIR:-$HOME/.local/bin}"
LA="$HOME/Library/LaunchAgents"
PREFIX="${CLAUDE_AGENDA_LABEL_PREFIX:-com.claude-agenda.}"
OS="${INSTALL_OS:-$(uname -s)}"   # INSTALL_OS: test hook
DRY=0; LOAD=0; UNINSTALL=0; JOB=1
TOOLS="claude-agenda claude-close-self launchd-overdue"

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --load) LOAD=1 ;;
    --uninstall) UNINSTALL=1 ;;
    --no-overdue-job) JOB=0 ;;
    --prefix) PREFIX="$2"; shift ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "install.sh: unknown option $1" >&2; exit 2 ;;
  esac
  shift
done
case "$PREFIX" in *.) ;; *) PREFIX="$PREFIX." ;; esac
LABEL="${PREFIX}launchd-overdue"
PLIST="$LA/$LABEL.plist"
LOGDIR="$HOME/Library/Logs"

run() { if [ $DRY = 1 ]; then echo "(dry-run) $*"; else "$@"; fi; }
have_launchctl() { [ "$OS" = Darwin ] && command -v launchctl >/dev/null 2>&1; }

if [ $UNINSTALL = 1 ]; then
  for t in $TOOLS; do
    [ -e "$BIN/$t" ] && run rm -f "$BIN/$t" && echo "removed $BIN/$t"
  done
  if [ -f "$PLIST" ]; then
    have_launchctl && run launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null
    run rm -f "$PLIST" && echo "removed $PLIST"
  fi
  echo "Jobs you created with 'claude-agenda add' are kept. List them with: ls $LA/${PREFIX}*"
  exit 0
fi

PY=""
for c in python3 python; do
  p="$(command -v "$c" 2>/dev/null)" && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 8))' 2>/dev/null && { PY="$p"; break; }
done
[ -n "$PY" ] || { echo "install.sh: python 3.8+ not found (needed by claude-agenda and launchd-overdue)" >&2; exit 1; }
command -v tmux >/dev/null 2>&1 || echo "note: tmux not found - claude-agenda run needs it (brew install tmux)"
command -v claude >/dev/null 2>&1 || [ -x "$HOME/.local/libexec/claude-stable/claude" ] \
  || echo "note: claude not found on PATH - claude-agenda run needs Claude Code"

run mkdir -p "$BIN"
for t in $TOOLS; do
  run cp "$R/bin/$t" "$BIN/$t" && run chmod 755 "$BIN/$t" && echo "installed $BIN/$t"
done
case ":$PATH:" in *":$BIN:"*) ;; *) echo "note: $BIN is not on your PATH" ;; esac

if [ $JOB = 0 ]; then exit 0; fi
if [ "$OS" != Darwin ]; then
  echo "launchd is macOS-only: skipped the daily launchd-overdue job"
  exit 0
fi
XML="<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\">
<dict>
	<key>Label</key>
	<string>$LABEL</string>
	<key>ProgramArguments</key>
	<array>
		<string>$PY</string>
		<string>$BIN/launchd-overdue</string>
		<string>--prefix</string>
		<string>$PREFIX</string>
	</array>
	<key>StartCalendarInterval</key>
	<dict>
		<key>Hour</key>
		<integer>8</integer>
		<key>Minute</key>
		<integer>0</integer>
	</dict>
	<key>RunAtLoad</key>
	<true/>
	<key>StandardOutPath</key>
	<string>$LOGDIR/launchd-overdue.out</string>
	<key>StandardErrorPath</key>
	<string>$LOGDIR/launchd-overdue.out</string>
</dict>
</plist>"
if [ $DRY = 1 ]; then
  echo "(dry-run) would write $PLIST:"; echo "$XML"
else
  mkdir -p "$LA" "$LOGDIR"
  printf '%s\n' "$XML" > "$PLIST"
  echo "wrote $PLIST"
fi
if [ $LOAD = 1 ]; then
  if have_launchctl; then
    run launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null
    run launchctl bootstrap "gui/$(id -u)" "$PLIST" && echo "loaded $LABEL"
  else
    echo "launchctl not found: not loaded"
  fi
else
  echo "not loaded. Load with: launchctl bootstrap gui/\$(id -u) '$PLIST'  (or re-run with --load)"
fi
