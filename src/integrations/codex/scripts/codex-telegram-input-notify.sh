#!/usr/bin/env bash
set -euo pipefail

ASOT_CONFIG_DIR="${ASOT_CONFIG_DIR:-$HOME/.config/asot}"
ASOT_SHARE_DIR="${ASOT_SHARE_DIR:-$HOME/.local/share/asot}"
ASOT_STATE_DIR="${ASOT_STATE_DIR:-$HOME/.local/state/asot}"
ENV_FILE="$ASOT_CONFIG_DIR/asot.env"
[[ -f "$ENV_FILE" ]] && source "$ENV_FILE"
export ASOT_AGENT="codex"
export ASOT_SHARE_DIR ASOT_STATE_DIR ASOT_CONFIG_DIR

INPUT="$(cat)"
export TELEGRAM_NOTIFY_INPUT="$INPUT"

python3 - <<'PY'
import json
import os
import sys
from pathlib import Path

base = Path(os.environ.get("ASOT_SHARE_DIR", str(Path.home() / ".local" / "share" / "asot"))) / "runtime" / "python"
sys.path.insert(0, str(base))
from telegram_common import get_env, save_mapping, send_telegram

bot_token, chat_id = get_env()
if not bot_token or not chat_id:
    raise SystemExit(0)

try:
    d = json.loads(os.environ.get("TELEGRAM_NOTIFY_INPUT", ""))
except Exception:
    raise SystemExit(0)

session_id = str(d.get("session_id", "")).strip()
cwd = str(d.get("cwd", "")).strip()
title = str(d.get("title", "입력 요청")).strip()
message = str(d.get("message", "사용자 입력이 필요합니다.")).strip()

text = f"❓ [Codex] {title}\n{message}\n\n💬 Reply to this message to respond"
msg_id = send_telegram(text, bot_token, chat_id)
if msg_id and session_id:
    save_mapping(msg_id, session_id, cwd)
PY
