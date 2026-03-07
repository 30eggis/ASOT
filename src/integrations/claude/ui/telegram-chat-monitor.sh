#!/bin/bash
# Telegram Chat Monitor - shows real-time telegram conversation in a tmux pane
# Usage:
#   telegram-chat-monitor.sh          # open in a new tmux split pane
#   telegram-chat-monitor.sh --tail   # just tail the log (used internally)

STATE_ROOT="${ASOT_STATE_DIR:-$HOME/.local/state/asot}"
CHAT_LOG="$STATE_ROOT/claude/chat.log"

if [ "$1" = "--tail" ]; then
    clear
    echo "=== Telegram Chat Monitor ==="
    echo "Waiting for messages..."
    echo ""
    touch "$CHAT_LOG"
    tail -f "$CHAT_LOG"
    exit 0
fi

# Check tmux
if [ -z "$TMUX" ]; then
    echo "tmux session not detected."
    echo "Option 1: Run inside tmux first"
    echo "Option 2: tail -f $CHAT_LOG"
    exit 1
fi

SCRIPT_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"

# Create a horizontal split (bottom pane, 30% height)
tmux split-window -v -l 30% "bash '$SCRIPT_PATH' --tail"

echo "Chat monitor opened in bottom pane."
