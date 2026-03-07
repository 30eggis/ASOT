#!/usr/bin/env bash
set -euo pipefail

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASOT_CONFIG_DIR="${ASOT_CONFIG_DIR:-$HOME/.config/asot}"
ASOT_SHARE_DIR="${ASOT_SHARE_DIR:-$HOME/.local/share/asot}"
ASOT_STATE_DIR="${ASOT_STATE_DIR:-$HOME/.local/state/asot}"
ENV_FILE="$ASOT_CONFIG_DIR/asot.env"
[[ -f "$ENV_FILE" ]] && source "$ENV_FILE"
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
    get_env,
    get_folder_name,
    log_chat,
    register_topic_binding,
    resolve_destination,
    save_mapping,
    send_telegram_auto,
)

bot_token, chat_id = get_env()
if not bot_token or not chat_id:
    raise SystemExit(0)

try:
    data = json.loads(os.environ.get("TELEGRAM_NOTIFY_INPUT", ""))
except Exception:
    raise SystemExit(0)

folder_name = get_folder_name(data)
session_id = str(data.get("session_id", "")).strip()
cwd = str(data.get("cwd", "")).strip()
stop_reason = str(data.get("stop_reason", "")).strip()

last_msg = data.get("last_assistant_message", "")
if isinstance(last_msg, dict):
    content = last_msg.get("content", "")
    if isinstance(content, list):
        texts = [item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text"]
        last_msg = "\n".join(text for text in texts if text)
    else:
        last_msg = str(content)

last_msg = str(last_msg).strip()
if not last_msg:
    last_msg = json.dumps(data, ensure_ascii=False, default=str)[:1000]

emoji = "✅" if stop_reason == "end_turn" else "🔔"
header = f"{emoji} [Claude Code] [{folder_name}]"
footer = "\n💬 Reply to this message to continue the session"
text = f"{header}\n{last_msg}\n{footer}"
caption = f"{header}\n{last_msg[:200]}...\n{footer}" if len(last_msg) > 200 else ""

dest_chat_id, dest_thread_id = resolve_destination(
    bot_token,
    chat_id,
    session_id=session_id,
    cwd=cwd,
)

log_chat("assistant", last_msg, folder_name)
msg_id = send_telegram_auto(
    text,
    bot_token,
    dest_chat_id,
    caption=caption,
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
