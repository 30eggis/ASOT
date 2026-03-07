#!/usr/bin/env bash
set -euo pipefail

STATE_ROOT="${ASOT_STATE_DIR:-$HOME/.local/state/asot}"
STATE_FILE="$STATE_ROOT/claude/tmux_sessions.json"

cwd_override=""
target_override=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cwd)
      cwd_override="${2:-}"
      shift 2
      ;;
    --target)
      target_override="${2:-}"
      shift 2
      ;;
    *)
      echo "usage: $0 [--cwd DIR] [--target TMUX_TARGET]" >&2
      exit 1
      ;;
  esac
done

if [[ -n "$target_override" ]]; then
  target="$target_override"
else
  target="$(tmux display-message -p '#{pane_id}')"
fi

if [[ -n "$cwd_override" ]]; then
  cwd="$cwd_override"
else
  cwd="$(tmux display-message -p -t "$target" '#{pane_current_path}')"
fi

session_name="$(tmux display-message -p -t "$target" '#S')"
cwd="$(python3 - <<'PY' "$cwd"
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"

python3 - <<'PY' "$STATE_FILE" "$cwd" "$target" "$session_name"
import json
import sys
import time
from pathlib import Path

state_file = Path(sys.argv[1])
cwd = sys.argv[2]
target = sys.argv[3]
session_name = sys.argv[4]

try:
    state = json.loads(state_file.read_text(encoding="utf-8"))
except Exception:
    state = {"by_cwd": {}}

state.setdefault("by_cwd", {})[cwd] = {
    "target": target,
    "session_name": session_name,
    "updated_at": int(time.time()),
}

state_file.parent.mkdir(parents=True, exist_ok=True)
state_file.write_text(json.dumps(state), encoding="utf-8")
print(json.dumps(state["by_cwd"][cwd], ensure_ascii=False))
PY

echo "registered cwd=$cwd target=$target session=$session_name"
