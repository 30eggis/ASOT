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
from telegram_common import get_env, save_mapping, send_telegram_auto

bot_token, chat_id = get_env()
if not bot_token or not chat_id:
    raise SystemExit(0)

try:
    d = json.loads(os.environ.get("TELEGRAM_NOTIFY_INPUT", ""))
except Exception:
    raise SystemExit(0)

session_id = str(d.get("session_id", "")).strip()
cwd = str(d.get("cwd", "")).strip()
msg = d.get("last_assistant_message", d.get("message", ""))

if isinstance(msg, dict):
    content = msg.get("content", "")
    if isinstance(content, list):
        texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
        msg = "\n".join(t for t in texts if t)
    else:
        msg = str(content)

msg = str(msg).strip()
if not msg:
    msg = json.dumps(d, ensure_ascii=False, default=str)[:1500]

header = "✅ [Codex]"
footer = "\n💬 Reply to this message to continue"
text = f"{header}\n{msg}{footer}"
caption = f"{header}\n{msg[:200]}...{footer}" if len(msg) > 200 else ""

msg_id = send_telegram_auto(text, bot_token, chat_id, caption=caption)
if msg_id and session_id:
    save_mapping(msg_id, session_id, cwd)
PY
