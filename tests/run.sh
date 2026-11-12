#!/bin/bash
# Shell tests: claude-close-self (with a fake tmux) and install.sh (with a fake HOME and a fake
# launchctl). Nothing reaches a real tmux server or launchd. Run: bash tests/run.sh
T="$(cd "$(dirname "$0")" && pwd)"
R="$(dirname "$T")"
W="$(mktemp -d "${TMPDIR:-/tmp}/claude-agenda-test.XXXXXX")"
trap 'rm -rf "$W"' EXIT
PASS=0; FAIL=0
# Settings paths from the developer's shell would make the tools seed and read real files.
unset XDG_CONFIG_HOME CLAUDE_CLOSE_SELF_ALLOW CLAUDE_CLOSE_SELF_ALLOW_FILE CLAUDE_AGENDA_CONFIG LAUNCHD_OVERDUE_YEARLY_FILE
ok()  { echo "  PASS: $*"; PASS=$((PASS+1)); }
bad() { echo "  FAIL: $*"; FAIL=$((FAIL+1)); }
PY="$(command -v python3 || command -v python)"

# fake tmux: prints $FAKE_TMUX_NAME for display-message and records every call
mkdir -p "$W/fakebin"
printf '%s\n' '#!/bin/sh' 'echo "$*" >> "$FAKE_DIR/tmux-calls"' \
  '[ "$1" = display-message ] && printf "%s\n" "$FAKE_TMUX_NAME"' \
  '[ "$1" = run-shell ] && printf "%s" "$3" > "$FAKE_DIR/run-shell-cmd"' \
  '[ "$1" = kill-session ] && printf "%s" "$3" > "$FAKE_DIR/killed"' 'exit 0' > "$W/fakebin/tmux"
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
# LA-03: a quote in the session name must not break out of the command tmux runs
EVIL="claude-agenda-x'; touch '$W/pwned"
rm -f "$W/run-shell-cmd" "$W/killed" "$W/pwned"
OUT=$(TMUX=/tmp/x FAKE_TMUX_NAME="$EVIL" sh "$CS" 0)
sh -c "$(cat "$W/run-shell-cmd")" 2>/dev/null
[ ! -e "$W/pwned" ] && [ "$(cat "$W/killed" 2>/dev/null)" = "$EVIL" ] && ok "quote in session name stays one argument" \
  || bad "pwned=$([ -e "$W/pwned" ] && echo yes) killed=$(cat "$W/killed" 2>/dev/null) cmd=$(cat "$W/run-shell-cmd")"

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
H2="$W/home2"; mkdir -p "$H2"
OUT=$(HOME="$H2" INSTALL_OS=Darwin bash "$R/install.sh")
P2="$H2/Library/LaunchAgents/com.claude-agenda.launchd-overdue.plist"
[ -f "$P2" ] && "$PY" -c "import plistlib,sys;a=plistlib.load(open(sys.argv[1],'rb'))['ProgramArguments'];assert '--prefix' not in a,a" "$P2" \
  && ok "no --prefix given: the overdue job follows the config file" || bad "plist: $(cat "$P2" 2>&1)"
[ -f "$H2/.local/bin/claude_agenda_config.py" ] && ok "shared module installed next to the tools" || bad "$OUT"
[ -f "$H2/.local/bin/claude-agenda.config.example.json" ] && ok "starter config installed next to the tools" || bad "$OUT"
H3="$W/home3"; mkdir -p "$H3"
OUT=$(cd / && HOME="$H3" "$PY" "$H2/.local/bin/claude-agenda" list 2>&1)
cmp -s "$H3/.config/claude-agenda/config.json" "$R/config.example.json" && [ -f "$H3/.config/claude-agenda/close-self-allow" ] \
  && ok "installed claude-agenda seeds ~/.config/claude-agenda on first run" || bad "not seeded: $OUT"
mkdir -p "$H2/.config/claude-agenda"; echo '{"overdue_prefixes": ["org.cfg."]}' > "$H2/.config/claude-agenda/config.json"
OUT=$(cd / && HOME="$H2" "$PY" "$H2/.local/bin/launchd-overdue" --dry-run 2>&1)
echo "$OUT" | grep -q "org.cfg." && ok "installed launchd-overdue runs and reads the config" || bad "$OUT"
OUT=$(cd / && HOME="$H2" "$PY" "$H2/.local/bin/claude-agenda" list 2>&1)
echo "$OUT" | grep -q "com.claude-agenda.launchd-overdue" && ok "installed claude-agenda runs" || bad "$OUT"
OUT=$(HOME="$H" INSTALL_OS=Darwin bash "$R/install.sh" --prefix org.example.agenda --load)
grep -q "^bootstrap gui/" "$W/launchctl-calls" 2>/dev/null && ok "--load calls (fake) launchctl bootstrap" || bad "$OUT"
OUT=$(HOME="$H" INSTALL_OS=Linux bash "$R/install.sh" --prefix org.other)
echo "$OUT" | grep -q "macOS-only" && [ ! -f "$H/Library/LaunchAgents/org.other.launchd-overdue.plist" ] && ok "non-macOS: no plist" || bad "$OUT"
OUT=$(HOME="$H" INSTALL_OS=Darwin bash "$R/install.sh" --uninstall --prefix org.example.agenda)
[ ! -e "$H/.local/bin/claude-agenda" ] && [ ! -e "$H/.local/bin/claude-agenda.config.example.json" ] && [ ! -f "$P" ] && grep -q "^bootout gui/.*/org.example.agenda.launchd-overdue" "$W/launchctl-calls" && ok "--uninstall reverses it" || bad "$OUT"

# LA-10: paths with XML characters are escaped in the plist
H4="$W/home4"; mkdir -p "$H4"; B4="$W/bin&co"
OUT=$(HOME="$H4" INSTALL_OS=Darwin INSTALL_BIN_DIR="$B4" bash "$R/install.sh" --prefix 'org.a&b')
P4="$H4/Library/LaunchAgents/org.a&b.launchd-overdue.plist"
[ -f "$P4" ] && "$PY" -c "import plistlib,sys;d=plistlib.load(open(sys.argv[1],'rb'));assert d['ProgramArguments'][1]==sys.argv[2]+'/launchd-overdue',d;assert d['Label']=='org.a&b.launchd-overdue',d" "$P4" "$B4" \
  && ok "XML characters in paths escaped" || bad "$OUT / $(cat "$P4" 2>&1)"
# LA-11: a copy that fails makes install.sh fail
H5="$W/home5"; mkdir -p "$H5"; : > "$W/afile"
OUT=$(HOME="$H5" INSTALL_OS=Darwin INSTALL_BIN_DIR="$W/afile/bin" bash "$R/install.sh" 2>&1); RC=$?
[ $RC -ne 0 ] && [ ! -e "$H5/Library/LaunchAgents/com.claude-agenda.launchd-overdue.plist" ] && ok "failed copy: exit $RC, no job written" || bad "rc=$RC $OUT"

echo
echo "RESULT: $PASS passed, $FAIL failed"
[ $FAIL -eq 0 ]
