#!/usr/bin/env bash
set -euo pipefail

session_name="${1:-}"
pane_target="${2:-}"
dry_run="${3:-}"

if [[ -z "$session_name" ]]; then
  echo "usage: $0 <tmux-session-name> [pane-target] [--dry-run]" >&2
  exit 1
fi

if [[ -n "$pane_target" && "$pane_target" != "--dry-run" ]]; then
  tmux_command="unset TMUX; tmux select-pane -t ${pane_target} >/dev/null 2>&1; tmux attach -t ${session_name}"
else
  tmux_command="unset TMUX; tmux attach -t ${session_name}"
fi

if [[ "$pane_target" == "--dry-run" || "$dry_run" == "--dry-run" ]]; then
  printf '%s\n' "$tmux_command"
  exit 0
fi

/usr/bin/osascript - "$tmux_command" <<'OSA'
on run argv
  set tmuxCommand to item 1 of argv
  tell application "iTerm"
    activate
    create window with default profile
    delay 0.2
    tell current session of current window
      write text tmuxCommand
    end tell
  end tell
end run
OSA
