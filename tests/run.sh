#!/bin/bash
# Shell tests: claude-close-self (with a fake tmux) and install.sh (with a fake HOME and a fake
# launchctl). Nothing reaches a real tmux server or launchd. Run: bash tests/run.sh
T="$(cd "$(dirname "$0")" && pwd)"
R="$(dirname "$T")"
W="$(mktemp -d "${TMPDIR:-/tmp}/claude-agenda-test.XXXXXX")"
trap 'rm -rf "$W"' EXIT
PASS=0; FAIL=0
unset XDG_CONFIG_HOME CLAUDE_CLOSE_SELF_ALLOW CLAUDE_CLOSE_SELF_ALLOW_FILE
ok()  { echo "  PASS: $*"; PASS=$((PASS+1)); }
bad() { echo "  FAIL: $*"; FAIL=$((FAIL+1)); }
PY="$(command -v python3 || command -v python)"

# fake tmux: prints $FAKE_TMUX_NAME for display-message and records every call
mkdir -p "$W/fakebin"
printf '%s\n' '#!/bin/sh' 'echo "$*" >> "$FAKE_DIR/tmux-calls"' \
  '[ "$1" = display-message ] && printf "%s\n" "$FAKE_TMUX_NAME"' 'exit 0' > "$W/fakebin/tmux"
printf '%s\n' '#!/bin/sh' 'echo "$*" >> "$FAKE_DIR/launchctl-calls"' > "$W/fakebin/launchctl"
chmod +x "$W/fakebin/tmux" "$W/fakebin/launchctl"
export FAKE_DIR="$W" PATH="$W/fakebin:$PATH"
CS="$R/bin/claude-close-self"

echo "== claude-close-self"
OUT=$(env -u TMUX sh "$CS"); echo "$OUT" | grep -q "not inside tmux" && ok "outside tmux: nothing" || bad "$OUT"
rm -f "$W/tmux-calls"
OUT=$(TMUX=/tmp/x FAKE_TMUX_NAME=my-work sh "$CS" 5)
echo "$OUT" | grep -q "not closing it" && ! grep -q run-shell "$W/tmux-calls" && ok "foreign session left alone" || bad "$OUT"
OUT=$(TMUX=/tmp/x FAKE_TMUX_NAME=claude-agenda-REPORT-123 sh "$CS" 5)
echo "$OUT" | grep -q "closes in 5s" && grep -Eq "run-shell -b sleep 5; '[^']*tmux' kill-session -t 'claude-agenda-REPORT-123'" "$W/tmux-calls" \
  && ok "agenda session scheduled to close" || bad "$OUT / $(cat "$W/tmux-calls")"
OUT=$(TMUX=/tmp/x FAKE_TMUX_NAME=review-7 CLAUDE_CLOSE_SELF_ALLOW='^review-[0-9]+$' sh "$CS")
echo "$OUT" | grep -q "closes in 30s" && ok "CLAUDE_CLOSE_SELF_ALLOW + default 30 s" || bad "$OUT"
OUT=$(TMUX=/tmp/x FAKE_TMUX_NAME=claude-agenda-x sh "$CS" abc 2>&1); [ $? = 2 ] && ok "bad delay rejected" || bad "$OUT"
AH="$W/allowhome"; mkdir -p "$AH/.config/claude-agenda"
printf '%s\n' '# sessions opened by my own launcher' '' '^claude-(NIGHTLY|REVIEW)-' '^ops-[0-9]+$' > "$AH/.config/claude-agenda/close-self-allow"
OUT=$(HOME="$AH" TMUX=/tmp/x FAKE_TMUX_NAME=claude-REVIEW-9 sh "$CS" 3)
echo "$OUT" | grep -q "closes in 3s" && ok "allow-list file: matching line" || bad "$OUT"
OUT=$(HOME="$AH" TMUX=/tmp/x FAKE_TMUX_NAME=ops-12 sh "$CS" 3)
echo "$OUT" | grep -q "closes in 3s" && ok "allow-list file: second pattern" || bad "$OUT"
OUT=$(HOME="$AH" TMUX=/tmp/x FAKE_TMUX_NAME=claude-retry-5 sh "$CS" 3)
echo "$OUT" | grep -q "not closing it" && ok "allow-list file: other session left alone" || bad "$OUT"
printf '%s\n' '^custom-' > "$W/allow2"
OUT=$(HOME="$AH" CLAUDE_CLOSE_SELF_ALLOW_FILE="$W/allow2" TMUX=/tmp/x FAKE_TMUX_NAME=custom-1 sh "$CS" 3)
echo "$OUT" | grep -q "closes in 3s" && ok "CLAUDE_CLOSE_SELF_ALLOW_FILE" || bad "$OUT"

echo "== install.sh"
H="$W/home"; mkdir -p "$H"
OUT=$(HOME="$H" INSTALL_OS=Darwin bash "$R/install.sh" --dry-run)
[ ! -e "$H/.local/bin/claude-agenda" ] && [ ! -e "$H/Library" ] && echo "$OUT" | grep -q "would write" && ok "--dry-run writes nothing" || bad "$OUT"
OUT=$(HOME="$H" INSTALL_OS=Darwin bash "$R/install.sh" --prefix org.example.agenda)
P="$H/Library/LaunchAgents/org.example.agenda.launchd-overdue.plist"
[ -x "$H/.local/bin/claude-agenda" ] && [ -x "$H/.local/bin/launchd-overdue" ] && [ -x "$H/.local/bin/claude-close-self" ] && ok "tools copied" || bad "$OUT"
[ -f "$P" ] && "$PY" -c "import plistlib,sys;d=plistlib.load(open(sys.argv[1],'rb'));assert d['Label']=='org.example.agenda.launchd-overdue';a=d['ProgramArguments'];assert a[1].endswith('/.local/bin/launchd-overdue') and a[2:]==['--prefix','org.example.agenda.'],a" "$P" \
  && ok "plist valid, real paths, custom prefix" || bad "plist: $(cat "$P" 2>&1)"
grep -q "$H" "$P" && ! grep -q '\$HOME' "$P" && ok "home path expanded in plist" || bad "home not expanded"
if command -v plutil >/dev/null 2>&1; then plutil -lint "$P" >/dev/null && ok "plutil -lint" || bad "plutil -lint failed"; fi
[ ! -f "$W/launchctl-calls" ] && echo "$OUT" | grep -q "not loaded" && ok "nothing loaded without --load" || bad "launchctl called: $(cat "$W/launchctl-calls" 2>&1)"
OUT=$(HOME="$H" INSTALL_OS=Darwin bash "$R/install.sh" --prefix org.example.agenda --load)
grep -q "^bootstrap gui/" "$W/launchctl-calls" 2>/dev/null && ok "--load calls (fake) launchctl bootstrap" || bad "$OUT"
OUT=$(HOME="$H" INSTALL_OS=Linux bash "$R/install.sh" --prefix org.other)
echo "$OUT" | grep -q "macOS-only" && [ ! -f "$H/Library/LaunchAgents/org.other.launchd-overdue.plist" ] && ok "non-macOS: no plist" || bad "$OUT"
OUT=$(HOME="$H" INSTALL_OS=Darwin bash "$R/install.sh" --uninstall --prefix org.example.agenda)
[ ! -e "$H/.local/bin/claude-agenda" ] && [ ! -f "$P" ] && grep -q "^bootout gui/.*/org.example.agenda.launchd-overdue" "$W/launchctl-calls" && ok "--uninstall reverses it" || bad "$OUT"

echo
echo "RESULT: $PASS passed, $FAIL failed"
[ $FAIL -eq 0 ]
