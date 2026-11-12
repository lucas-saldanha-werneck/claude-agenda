#!/bin/bash
# Integration test with a REAL tmux and, on a macOS CI runner, a REAL launchd.
#   bash tests/integration.sh
# tmux part: runs anywhere tmux is installed, on its own tmux server (private TMUX_TMPDIR), so your
#   sessions are never seen or touched. Claude is a stand-in script that sleeps.
# launchd part: only when CI=true on macOS (it loads and unloads real launchd jobs; labels
#   org.claude-agenda-ci.*). On a developer Mac it is skipped.
T="$(cd "$(dirname "$0")" && pwd)"
R="$(dirname "$T")"
W="$(mktemp -d "${TMPDIR:-/tmp}/claude-agenda-it.XXXXXX")"
W="$(cd "$W" && pwd -P)"
PASS=0; FAIL=0
ok()  { echo "  PASS: $*"; PASS=$((PASS+1)); }
bad() { echo "  FAIL: $*"; FAIL=$((FAIL+1)); }
PY="$(command -v python3 || command -v python)"
unset XDG_CONFIG_HOME CLAUDE_CLOSE_SELF_ALLOW CLAUDE_CLOSE_SELF_ALLOW_FILE CLAUDE_AGENDA_CONFIG TMUX TMUX_PANE
export HOME="$W/home" TMUX_TMPDIR="$W/tmux" CLAUDE_AGENDA_LOG_DIR="$W/logs"
mkdir -p "$HOME" "$TMUX_TMPDIR" "$W/work"
TM="$(command -v tmux)"
cleanup() {
  [ -n "$TM" ] && "$TM" kill-server 2>/dev/null
  if [ -n "${LOADED:-}" ]; then for l in $LOADED; do launchctl bootout "gui/$(id -u)/$l" 2>/dev/null; done; fi
  rm -rf "$W"
}
trap cleanup EXIT

# stand-in for claude: `agents --json` knows no session; anything else is the session itself
cat > "$W/claude" <<'EOF'
#!/bin/sh
[ "$1" = agents ] && { echo '[]'; exit 0; }
exec sleep 300
EOF
chmod +x "$W/claude"
export CLAUDE_AGENDA_CLAUDE="$W/claude"

wait_for() {   # wait_for SECONDS COMMAND...: retry until the command succeeds
  local n=$(( $1 * 4 )); shift
  while [ $n -gt 0 ]; do "$@" && return 0; sleep 0.25; n=$((n-1)); done
  return 1
}

echo "== real tmux"
if [ -z "$TM" ]; then
  bad "tmux not installed"
else
  OUT=$("$PY" "$R/bin/claude-agenda" run CI "hello world" --dir "$W/work" 2>&1)
  SESS=$("$TM" list-sessions -F '#{session_name}' 2>/dev/null | grep '^claude-agenda-CI-[0-9]*$')
  [ -n "$SESS" ] && ok "run opened tmux session $SESS" || bad "$OUT"
  wait_for 10 sh -c "'$TM' list-panes -t '$SESS' -F '#{pane_current_command}' | grep -q sleep" \
    && ok "the session runs claude (stand-in) through the login shell" \
    || bad "pane runs: $("$TM" list-panes -t "$SESS" -F '#{pane_current_command}' 2>&1)"
  [ "$("$TM" display-message -p -t "$SESS" '#{pane_current_path}')" = "$W/work" ] \
    && ok "session opened in --dir" || bad "path: $("$TM" display-message -p -t "$SESS" '#{pane_current_path}')"
  OUT=$("$PY" "$R/bin/claude-agenda" run CI "again" --dir "$W/work" 2>&1)
  echo "$OUT" | grep -q "still open" && [ "$("$TM" list-sessions | grep -c '^claude-agenda-CI-')" = 1 ] \
    && ok "second run skipped while the first session is open" || bad "$OUT"
  sleep 1   # session names hold the epoch second: the replacement must get a new one
  OUT=$(CLAUDE_AGENDA_STALE_HOURS=0 "$PY" "$R/bin/claude-agenda" run CI "stale" --dir "$W/work" 2>&1)
  ! "$TM" has-session -t "=$SESS" 2>/dev/null && echo "$OUT" | grep -q "closing stale" \
    && ok "stale session closed and replaced" || bad "$OUT"

  # claude-close-self from inside a session, also with a quote in its name (real run-shell + sh -c)
  for name in "claude-agenda-close-1" "claude-agenda-q'x#y"; do
    "$TM" new-session -d -s "$name" "sh '$R/bin/claude-close-self' 1 > '$W/close.out' 2>&1; sleep 60"
    wait_for 15 sh -c "! '$TM' has-session -t '=$(printf '%s' "$name" | sed "s/'/'\\\\''/g")' 2>/dev/null" \
      && ok "claude-close-self closed '$name'" || bad "'$name' still open: $(cat "$W/close.out" 2>&1)"
  done
  "$TM" new-session -d -s "my-work" "sh '$R/bin/claude-close-self' 1 > '$W/close2.out' 2>&1; sleep 60"
  sleep 3
  "$TM" has-session -t "=my-work" 2>/dev/null && grep -q "not closing it" "$W/close2.out" \
    && ok "claude-close-self leaves a foreign session alone" || bad "$(cat "$W/close2.out" 2>&1)"
fi

echo "== real launchd"
if [ "$(uname -s)" != Darwin ] || [ "${CI:-}" != true ]; then
  echo "  skipped (only on a macOS CI runner: it loads real launchd jobs)"
else
  U=$(id -u); LP="org.claude-agenda-ci."; N="job$$"; L="$LP$N"
  OUT=$("$PY" "$R/bin/claude-agenda" add "$N" --label-prefix "$LP" --prefix CI --prompt hi --at 03:17 \
        --dir "$W/work" --load 2>&1)
  LOADED="$L"
  launchctl print "gui/$U/$L" >/dev/null 2>&1 && ok "add --load: launchd knows $L" || bad "$OUT"
  plutil -lint "$HOME/Library/LaunchAgents/$L.plist" >/dev/null && ok "plist passes plutil -lint" || bad "plutil"
  OUT=$("$PY" "$R/bin/claude-agenda" add "$N" --label-prefix "$LP" --prefix CI --prompt hi --at 03:18 \
        --dir "$W/work" --load 2>&1); RC=$?
  [ $RC -ne 0 ] && echo "$OUT" | grep -q -- "--force" && ok "add of an existing NAME needs --force" || bad "$OUT"
  OUT=$("$PY" "$R/bin/claude-agenda" add "$N" --label-prefix "$LP" --prefix CI --prompt hi --at 03:18 \
        --dir "$W/work" --load --force 2>&1)
  "$PY" -c "import plistlib,sys; assert plistlib.load(open(sys.argv[1],'rb'))['StartCalendarInterval']['Minute']==18" \
      "$HOME/Library/LaunchAgents/$L.plist" && launchctl print "gui/$U/$L" >/dev/null 2>&1 \
    && ok "--force replaced and reloaded the job" || bad "$OUT"
  OUT=$("$PY" "$R/bin/claude-agenda" remove "$L" --label-prefix "$LP" 2>&1)
  ! launchctl print "gui/$U/$L" >/dev/null 2>&1 && [ ! -e "$HOME/Library/LaunchAgents/$L.plist" ] \
    && ok "remove unloads and deletes" || bad "$OUT"
  LOADED=""

  # launchd-overdue on a loaded one-time job whose date has passed
  O="${LP}overdue$$"; P="$HOME/Library/LaunchAgents/$O.plist"
  "$PY" -c "import plistlib,sys; plistlib.dump(dict(Label=sys.argv[2], ProgramArguments=['/usr/bin/true'],
StartCalendarInterval=dict(Month=1, Day=2, Hour=3, Minute=4), ClaudeAgendaYear=2020), open(sys.argv[1], 'wb'))" "$P" "$O"
  launchctl bootstrap "gui/$U" "$P" && LOADED="$O"
  launchctl print "gui/$U/$O" >/dev/null 2>&1 && ok "past one-time job loaded" || bad "bootstrap failed"
  OUT=$("$PY" "$R/bin/launchd-overdue" --prefix "$LP" 2>&1)
  ! launchctl print "gui/$U/$O" >/dev/null 2>&1 && [ -f "$HOME/Library/LaunchAgents/overdue/$O.plist" ] && [ ! -e "$P" ] \
    && ok "launchd-overdue unloaded and archived it" || bad "$OUT"
  LOADED=""
fi

echo
echo "RESULT: $PASS passed, $FAIL failed"
[ $FAIL -eq 0 ]
