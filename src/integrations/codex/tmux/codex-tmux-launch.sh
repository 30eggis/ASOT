#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGISTER_SCRIPT="$BASE_DIR/codex-tmux-register.sh"
CODEX_BIN="${CODEX_BIN:-/opt/homebrew/bin/codex}"

cwd="$PWD"
session_name=""
attach_mode=0
declare -a codex_args
codex_args=()

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
      codex_args=("$@")
      break
      ;;
    *)
      echo "usage: $0 [--cwd DIR] [--session NAME] [--attach] [-- codex args...]" >&2
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

sanitize_name() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '_' | sed 's/^_\\+//; s/_\\+$//'
}

if [[ -z "$session_name" ]]; then
  base_name="$(sanitize_name "$(basename "$cwd")")"
  [[ -n "$base_name" ]] || base_name="codex"
  session_name="codex_${base_name}"
else
  session_name="$(sanitize_name "$session_name")"
fi

cmd="$CODEX_BIN"
for arg in "${codex_args[@]}"; do
  cmd+=" $(printf '%q' "$arg")"
done

if tmux has-session -t "$session_name" 2>/dev/null; then
  target="$(tmux list-panes -t "$session_name" -F '#S:#I.#P' | head -n 1)"
  "$REGISTER_SCRIPT" --cwd "$cwd" --target "$target" >/dev/null 2>&1 || true
  echo "session already exists: $session_name" >&2
  echo "attach: tmux attach -t $session_name"
  if [[ "$attach_mode" == "1" ]]; then
    exec tmux attach -t "$session_name"
  fi
  exit 0
fi

tmux new-session -d -s "$session_name" -c "$cwd" "$cmd"
target="$(tmux list-panes -t "$session_name" -F '#S:#I.#P' | head -n 1)"
"$REGISTER_SCRIPT" --cwd "$cwd" --target "$target" >/dev/null

echo "started tmux session=$session_name target=$target cwd=$cwd"
echo "attach: tmux attach -t $session_name"

if [[ "$attach_mode" == "1" ]]; then
  exec tmux attach -t "$session_name"
fi
