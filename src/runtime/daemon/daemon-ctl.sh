#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${ASOT_STATE_DIR:-$HOME/.local/state/asot}"
PID_FILE="$STATE_DIR/daemon.pid"
LOG_FILE="$STATE_DIR/daemon.log"
DAEMON="$SCRIPT_DIR/telegram-daemon.py"
PLIST="$HOME/Library/LaunchAgents/com.asot.daemon.plist"
LABEL="com.asot.daemon"

mkdir -p "$STATE_DIR"

running_pid() {
  local launchd_pid
  launchd_pid="$(launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null | awk '/pid = / {print $3; exit}' || true)"
  if [[ -n "$launchd_pid" && "$launchd_pid" != "0" ]]; then
    printf '%s\n' "$launchd_pid"
    return 0
  fi

  if [[ ! -f "$PID_FILE" ]]; then
    return 1
  fi

  local pid
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  [[ -n "$pid" ]] || return 1

  if kill -0 "$pid" 2>/dev/null; then
    printf '%s\n' "$pid"
    return 0
  fi

  return 1
}

case "${1:-status}" in
  start)
    if pid="$(running_pid)"; then
      echo "running pid=$pid"
      exit 0
    fi
    if [[ -f "$PLIST" ]]; then
      launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || true
      launchctl enable "gui/$(id -u)/$LABEL" 2>/dev/null || true
      launchctl kickstart -k "gui/$(id -u)/$LABEL"
      sleep 1
      if pid="$(running_pid)"; then
        echo "running pid=$pid"
        exit 0
      fi
    fi
    nohup /usr/bin/python3 "$DAEMON" >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "started pid=$!"
    ;;
  stop)
    if [[ -f "$PLIST" ]]; then
      launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
    fi
    if pid="$(cat "$PID_FILE" 2>/dev/null || true)" && [[ -n "$pid" ]]; then
      kill "$pid" 2>/dev/null || true
      sleep 1
    fi
    rm -f "$PID_FILE"
    echo "stopped"
    ;;
  restart)
    "$0" stop
    "$0" start
    ;;
  status)
    if pid="$(running_pid)"; then
      echo "running pid=$pid"
    else
      echo "not_running"
    fi
    ;;
  logs)
    tail -f "$LOG_FILE"
    ;;
  *)
    echo "usage: $0 {start|stop|restart|status|logs}"
    exit 1
    ;;
esac
