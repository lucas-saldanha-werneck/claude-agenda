#!/bin/bash
# install.sh - copy claude-agenda, claude-close-self and launchd-overdue into ~/.local/bin and write
# the daily launchd job for launchd-overdue (with your real paths). Loads nothing unless --load.
#
#   ./install.sh [--dry-run] [--load] [--no-overdue-job] [--prefix com.claude-agenda.]
#   --prefix also fixes the prefix the overdue job checks; without it the job follows the config file.
#   ./install.sh --uninstall [--dry-run]
#
# Environment: INSTALL_BIN_DIR (default ~/.local/bin).
set -u
R="$(cd "$(dirname "$0")" && pwd)"
BIN="${INSTALL_BIN_DIR:-$HOME/.local/bin}"
LA="$HOME/Library/LaunchAgents"
PREFIX="${CLAUDE_AGENDA_LABEL_PREFIX:-com.claude-agenda.}"
PREFIX_GIVEN=0; [ -n "${CLAUDE_AGENDA_LABEL_PREFIX:-}" ] && PREFIX_GIVEN=1
OS="${INSTALL_OS:-$(uname -s)}"   # INSTALL_OS: test hook
DRY=0; LOAD=0; UNINSTALL=0; JOB=1
TOOLS="claude-agenda claude-close-self launchd-overdue"
LIBS="claude_agenda_config.py"   # shared module the Python tools import from their own folder
STARTERS="config.example.json close-self-allow.example yearly.example.txt"

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --load) LOAD=1 ;;
    --uninstall) UNINSTALL=1 ;;
    --no-overdue-job) JOB=0 ;;
    --prefix) PREFIX="$2"; PREFIX_GIVEN=1; shift ;;
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
  for t in $TOOLS $LIBS; do
    [ -e "$BIN/$t" ] && run rm -f "$BIN/$t" && echo "removed $BIN/$t"
  done
  for t in $STARTERS; do
    [ -e "$BIN/claude-agenda.$t" ] && run rm -f "$BIN/claude-agenda.$t" && echo "removed $BIN/claude-agenda.$t"
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

ERRORS=0
put() {   # put SRC DEST MODE: copy and set the mode, counting failures
  if run cp "$1" "$2" && run chmod "$3" "$2"; then echo "installed $2"
  else echo "install.sh: could not install $2" >&2; ERRORS=$((ERRORS+1)); fi
}
run mkdir -p "$BIN" || ERRORS=$((ERRORS+1))
for t in $TOOLS; do put "$R/bin/$t" "$BIN/$t" 755; done
for t in $LIBS; do put "$R/bin/$t" "$BIN/$t" 644; done
for t in $STARTERS; do   # starter config files: the tools copy them to ~/.config on first run
  put "$R/$t" "$BIN/claude-agenda.$t" 644
done
if [ $ERRORS -gt 0 ]; then
  echo "install.sh: $ERRORS step(s) failed; the launchd job was not written" >&2
  exit 1
fi
case ":$PATH:" in *":$BIN:"*) ;; *) echo "note: $BIN is not on your PATH" ;; esac

if [ $JOB = 0 ]; then exit 0; fi
if [ "$OS" != Darwin ]; then
  echo "launchd is macOS-only: skipped the daily launchd-overdue job"
  exit 0
fi
# --prefix goes into the job only when you gave one; otherwise launchd-overdue reads overdue_prefixes /
# label_prefix from ~/.config/claude-agenda/config.json on every run.
# XML-escape every value that goes into the plist (a path or prefix may hold & or <).
x() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }
PREFIX_ARGS=""
[ $PREFIX_GIVEN = 1 ] && PREFIX_ARGS="
		<string>--prefix</string>
		<string>$(x "$PREFIX")</string>"
XML="<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\">
<dict>
	<key>Label</key>
	<string>$(x "$LABEL")</string>
	<key>ProgramArguments</key>
	<array>
		<string>$(x "$PY")</string>
		<string>$(x "$BIN/launchd-overdue")</string>$PREFIX_ARGS
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
	<string>$(x "$LOGDIR/launchd-overdue.out")</string>
	<key>StandardErrorPath</key>
	<string>$(x "$LOGDIR/launchd-overdue.out")</string>
</dict>
</plist>"
if [ $DRY = 1 ]; then
  echo "(dry-run) would write $PLIST:"; echo "$XML"
else
  mkdir -p "$LA" "$LOGDIR" && printf '%s\n' "$XML" > "$PLIST" \
    || { echo "install.sh: could not write $PLIST" >&2; exit 1; }
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
