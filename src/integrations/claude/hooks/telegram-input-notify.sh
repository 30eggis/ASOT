#!/usr/bin/env bash
set -euo pipefail

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASOT_CONFIG_DIR="${ASOT_CONFIG_DIR:-$HOME/.config/asot}"
ASOT_SHARE_DIR="${ASOT_SHARE_DIR:-$HOME/.local/share/asot}"
ASOT_STATE_DIR="${ASOT_STATE_DIR:-$HOME/.local/state/asot}"
ENV_FILE="$ASOT_CONFIG_DIR/asot.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi
export ASOT_AGENT="claude"
export ASOT_SHARE_DIR ASOT_STATE_DIR ASOT_CONFIG_DIR

INPUT="$(cat)"
export TELEGRAM_NOTIFY_INPUT="$INPUT"

python3 - <<'PY'
import json
import os
import sys

sys.path.insert(0, os.path.join(os.environ.get("ASOT_SHARE_DIR", os.path.expanduser("~/.local/share/asot")), "runtime", "python"))
from telegram_common import (
    extract_claude_session_info,
    get_env,
    get_folder_name,
    log_chat,
    register_topic_binding,
    resolve_destination,
    save_mapping,
    send_telegram,
)

bot_token, chat_id = get_env()
if not bot_token or not chat_id:
    raise SystemExit(0)

try:
    data = json.loads(os.environ.get("TELEGRAM_NOTIFY_INPUT", ""))
except Exception:
    raise SystemExit(0)

session_id, cwd = extract_claude_session_info(data)
folder_name = get_folder_name(data)
tool_name = str(data.get("tool_name", "unknown")).strip()
tool_input = data.get("tool_input", {})

lines = []

if tool_name == "AskUserQuestion":
    lines.append(f"❓ [Claude Code] [{folder_name}] Question")
    questions = tool_input.get("questions", []) if isinstance(tool_input, dict) else []
    for question in questions[:3]:
        question_text = str(question.get("question", "")).strip()
        if question_text:
            lines.append(question_text[:200])
        options = question.get("options", [])
        labels = [item.get("label", "") for item in options if isinstance(item, dict) and item.get("label")]
        if labels:
            lines.append("  -> " + " | ".join(labels))
elif tool_name == "ExitPlanMode":
    lines.append(f"📋 [Claude Code] [{folder_name}] Plan Approval")
    lines.append("Plan is ready for review.")
else:
    lines.append(f"⏸️ [Claude Code] [{folder_name}] Waiting")
    lines.append(f"Tool: {tool_name}")

if not lines:
    raise SystemExit(0)

lines.append("\n💬 Reply to this message to respond")
text = "\n".join(lines)

dest_chat_id, dest_thread_id = resolve_destination(
    bot_token,
    chat_id,
    session_id=session_id,
    cwd=cwd,
)

log_chat("assistant", "\n".join(lines[:-1]), folder_name)
msg_id = send_telegram(
    text,
    bot_token,
    dest_chat_id,
    message_thread_id=dest_thread_id,
)
if msg_id and session_id:
    save_mapping(
        msg_id,
        session_id,
        cwd,
        chat_id=dest_chat_id,
        message_thread_id=dest_thread_id,
    )
if session_id and dest_thread_id is not None:
    register_topic_binding(session_id, cwd, dest_chat_id, dest_thread_id)
PY

exit 0
