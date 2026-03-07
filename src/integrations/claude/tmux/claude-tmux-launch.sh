#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGISTER_SCRIPT="$BASE_DIR/claude-tmux-register.sh"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude || true)}"

if [[ -z "$CLAUDE_BIN" ]]; then
  CLAUDE_BIN="$HOME/.local/bin/claude"
fi

cwd="$PWD"
session_name=""
attach_mode=0
declare -a claude_args
claude_args=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cwd)
      cwd="${2:-}"
      shift 2
      ;;
    --session)
      session_name="${2:-}"
      shift 2
      ;;
    --attach)
      attach_mode=1
      shift
      ;;
    --)
      shift
      claude_args=("$@")
      break
      ;;
    *)
      echo "usage: $0 [--cwd DIR] [--session NAME] [--attach] [-- claude args...]" >&2
      exit 1
      ;;
  esac
done

cwd="$(python3 - <<'PY' "$cwd"
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"

if [[ -z "$session_name" ]]; then
  base_name="$(basename "$cwd" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '_')"
  session_name="claude_${base_name}"
fi

has_skip_permissions=0
for arg in "${claude_args[@]}"; do
  if [[ "$arg" == "--dangerously-skip-permissions" ]]; then
    has_skip_permissions=1
    break
  fi
done
if [[ "$has_skip_permissions" == "0" ]]; then
  claude_args=(--dangerously-skip-permissions "${claude_args[@]}")
fi

if tmux has-session -t "$session_name" 2>/dev/null; then
  echo "session already exists: $session_name" >&2
  exit 1
fi

tmux new-session -d -s "$session_name" -c "$cwd" "$CLAUDE_BIN" "${claude_args[@]}"
main_target="$(tmux list-panes -t "$session_name" -F '#{pane_id}' | head -n 1)"
"$REGISTER_SCRIPT" --cwd "$cwd" --target "$main_target" >/dev/null

echo "started tmux session=$session_name target=$main_target cwd=$cwd"
echo "attach: tmux attach -t $session_name"

if [[ "$attach_mode" == "1" ]]; then
  exec tmux attach -t "$session_name"
fi
