#!/bin/zsh
# Install (or remove) a macOS background service that runs the full corpus ingest.
#
#   scripts/install_ingest_service.sh install    start now, and relaunch at every login
#   scripts/install_ingest_service.sh status     show progress
#   scripts/install_ingest_service.sh remove     stop and delete the service
#
# What it survives:
#   - internet drop  : each network call retries with backoff; if it still fails the job
#                      exits non-zero and launchd restarts it 5 minutes later.
#   - sleep          : `caffeinate -i -s` keeps the Mac awake while the job runs.
#   - shutdown/reboot: the LaunchAgent starts again at the next login (RunAtLoad).
#   - crash          : KeepAlive restarts it unless it exited cleanly (all years done).
# Finished years are skipped on every restart, so no work is repeated.
set -e
LABEL="com.pramaan.ingest"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
UV="$(command -v uv)"

case "$1" in
install)
  mkdir -p "$REPO/logs" "$HOME/Library/LaunchAgents"
  cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/caffeinate</string><string>-i</string><string>-s</string>
    <string>$UV</string><string>run</string><string>python</string>
    <string>-m</string><string>pramaan.data.ingest</string>
    <string>--full</string><string>--free-raw</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>300</integer>
  <key>StandardOutPath</key><string>$REPO/logs/ingest.log</string>
  <key>StandardErrorPath</key><string>$REPO/logs/ingest.log</string>
</dict></plist>
PLIST_EOF
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  echo "installed. progress: scripts/install_ingest_service.sh status   log: logs/ingest.log"
  ;;
status)
  launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null | grep -E "state|last exit" || echo "service not loaded"
  (cd "$REPO" && "$UV" run python -m pramaan.data.ingest --full --status | tail -8)
  tail -5 "$REPO/logs/ingest.log" 2>/dev/null
  ;;
remove)
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "removed"
  ;;
*) echo "usage: $0 install|status|remove"; exit 1 ;;
esac
