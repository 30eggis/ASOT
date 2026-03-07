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

session_id = str(data.get("session_id", os.environ.get("CLAUDE_SESSION_ID", ""))).strip()
cwd = str(data.get("cwd", os.environ.get("CLAUDE_PROJECT_DIR", ""))).strip()
folder_name = get_folder_name(data)

tool_name = str(data.get("tool_name", "")).strip()
tool_input = data.get("tool_input", {})
message = data.get("message", "")
title = str(data.get("title", "")).strip()

command = ""
if isinstance(tool_input, dict):
    command = tool_input.get("command", tool_input.get("description", ""))
if isinstance(command, str):
    command = command[:200]

if not tool_name and not title and not message and not command:
    raise SystemExit(0)

lines = [f"⏳ [Claude Code] [{folder_name}] Permission Required"]
if tool_name:
    lines.append(f"Tool: {tool_name}")
if title:
    lines.append(f"Title: {title}")
if command:
    lines.append(f"Command: {command}")
if isinstance(message, str) and message:
    lines.append(message[:200])

text = "\n".join(lines)

dest_chat_id, dest_thread_id = resolve_destination(
    bot_token,
    chat_id,
    session_id=session_id,
    cwd=cwd,
)

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
