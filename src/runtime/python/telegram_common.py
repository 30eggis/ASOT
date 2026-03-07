"""
Shared Telegram utilities for ASOT integrations.
"""
import json
import os
import time
import urllib.request
from pathlib import Path

HOME = Path.home()
CONFIG_DIR = Path(os.environ.get("ASOT_CONFIG_DIR", HOME / ".config" / "asot"))
STATE_ROOT = Path(os.environ.get("ASOT_STATE_DIR", HOME / ".local" / "state" / "asot"))
AGENT = os.environ.get("ASOT_AGENT", "generic").strip() or "generic"
STATE_DIR = STATE_ROOT / AGENT
MAPPING_FILE = STATE_DIR / "msg_session_map.json"
TOPIC_STATE_FILE = STATE_DIR / "topic_sessions.json"
CHAT_LOG_FILE = STATE_DIR / "chat.log"
MAX_MSG_LENGTH = 4000


def get_env():
    bot_token = os.environ.get("ASOT_TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("ASOT_TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID", "")
    return bot_token, chat_id


def env_enabled(name, default=True):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def normalize_chat_id(chat_id):
    return str(chat_id or "").strip()


def normalize_thread_id(message_thread_id):
    if message_thread_id in (None, ""):
        return None
    try:
        return int(message_thread_id)
    except Exception:
        return None


def normalize_cwd(cwd):
    if not cwd:
        return ""
    try:
        return str(Path(cwd).expanduser().resolve())
    except Exception:
        return str(Path(cwd).expanduser())


def get_folder_name(data_or_cwd):
    if isinstance(data_or_cwd, dict):
        cwd = (
            data_or_cwd.get("cwd", "")
            or os.environ.get("ASOT_PROJECT_DIR", "")
            or os.environ.get("CLAUDE_PROJECT_DIR", "")
        )
    else:
        cwd = data_or_cwd or os.environ.get("ASOT_PROJECT_DIR", "") or os.environ.get("CLAUDE_PROJECT_DIR", "")

    if not cwd:
        return "unknown"

    try:
        return Path(cwd).name or str(cwd)
    except Exception:
        return str(cwd)


def trim_text(text, limit):
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def send_telegram(text, bot_token, chat_id, disable_notification=False, message_thread_id=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_notification": disable_notification,
    }
    if message_thread_id not in (None, ""):
        payload["message_thread_id"] = int(message_thread_id)

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=8)
        result = json.loads(resp.read().decode("utf-8"))
        return result.get("result", {}).get("message_id")
    except Exception:
        return None


def send_telegram_file(text, bot_token, chat_id, caption="", filename="response.txt", message_thread_id=None):
    boundary = "----FormBoundary7MA4YWxkTrZu0gW"
    body = []

    body.append(f"--{boundary}")
    body.append('Content-Disposition: form-data; name="chat_id"')
    body.append("")
    body.append(chat_id)

    if message_thread_id not in (None, ""):
        body.append(f"--{boundary}")
        body.append('Content-Disposition: form-data; name="message_thread_id"')
        body.append("")
        body.append(str(int(message_thread_id)))

    if caption:
        body.append(f"--{boundary}")
        body.append('Content-Disposition: form-data; name="caption"')
        body.append("")
        body.append(caption[:1024])

    body.append(f"--{boundary}")
    body.append(f'Content-Disposition: form-data; name="document"; filename="{filename}"')
    body.append("Content-Type: text/plain")
    body.append("")
    body.append(text)
    body.append(f"--{boundary}--")
    body.append("")

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendDocument",
        data="\r\n".join(body).encode("utf-8"),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read().decode("utf-8"))
        return result.get("result", {}).get("message_id")
    except Exception:
        return None


def send_telegram_auto(text, bot_token, chat_id, caption="", disable_notification=False, message_thread_id=None):
    if len(text) <= MAX_MSG_LENGTH:
        return send_telegram(
            text,
            bot_token,
            chat_id,
            disable_notification=disable_notification,
            message_thread_id=message_thread_id,
        )
    return send_telegram_file(
        text,
        bot_token,
        chat_id,
        caption=caption,
        message_thread_id=message_thread_id,
    )


def load_mapping():
    try:
        return json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_mapping(message_id, session_id, cwd, chat_id="", message_thread_id=None):
    if not message_id:
        return

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    mapping = load_mapping()
    entry = {
        "session_id": str(session_id or "").strip(),
        "cwd": str(cwd or "").strip(),
    }
    if chat_id:
        entry["chat_id"] = normalize_chat_id(chat_id)
    if message_thread_id not in (None, ""):
        entry["message_thread_id"] = int(message_thread_id)
    mapping[str(message_id)] = entry

    if len(mapping) > 200:
        keys = sorted(mapping.keys(), key=int)
        mapping = {key: mapping[key] for key in keys[-200:]}

    MAPPING_FILE.write_text(json.dumps(mapping), encoding="utf-8")


def log_chat(role, text, folder=""):
    from datetime import datetime

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H:%M:%S")
    prefix = f"[{folder}] " if folder else ""
    label = "TG User" if role == "user" else AGENT.capitalize()
    separator = ">" if role == "user" else " "
    lines = str(text or "").strip().split("\n")
    with CHAT_LOG_FILE.open("a", encoding="utf-8") as file_handle:
        file_handle.write(
            f"\n\033[90m{ts}\033[0m {prefix}\033[{'36' if role == 'user' else '32'}m[{label}]\033[0m\n"
        )
        for line in lines:
            file_handle.write(f"  {separator} {line}\n")


def topic_thread_key(chat_id, message_thread_id):
    normalized_chat_id = normalize_chat_id(chat_id)
    normalized_thread_id = normalize_thread_id(message_thread_id)
    if not normalized_chat_id or normalized_thread_id is None:
        return ""
    return f"{normalized_chat_id}:{normalized_thread_id}"


def load_topic_state():
    try:
        state = json.loads(TOPIC_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        state = {}
    state.setdefault("by_session", {})
    state.setdefault("by_thread", {})
    state.setdefault("by_cwd", {})
    return state


def save_topic_state(state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    TOPIC_STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def log_topic_error(message):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log_file = STATE_DIR / "topic-errors.log"
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with log_file.open("a", encoding="utf-8") as file_handle:
        file_handle.write(f"{timestamp} {message}\n")


def build_topic_entry(session_id, cwd, chat_id, message_thread_id, topic_name=""):
    return {
        "session_id": str(session_id or "").strip(),
        "cwd": str(cwd or "").strip(),
        "chat_id": normalize_chat_id(chat_id),
        "message_thread_id": normalize_thread_id(message_thread_id),
        "topic_name": str(topic_name or "").strip(),
        "updated_at": int(time.time()),
    }


def register_topic_binding(session_id, cwd, chat_id, message_thread_id, topic_name=""):
    thread_key = topic_thread_key(chat_id, message_thread_id)
    if not thread_key:
        return None

    entry = build_topic_entry(session_id, cwd, chat_id, message_thread_id, topic_name=topic_name)
    state = load_topic_state()
    state["by_thread"][thread_key] = entry

    normalized_cwd = normalize_cwd(cwd)
    if normalized_cwd:
        state["by_cwd"][normalized_cwd] = entry

    normalized_session_id = str(session_id or "").strip()
    if normalized_session_id:
        state["by_session"][normalized_session_id] = entry

    save_topic_state(state)
    return entry


def get_topic_binding_for_session(session_id, cwd="", allow_cwd_fallback=True):
    state = load_topic_state()
    normalized_session_id = str(session_id or "").strip()
    if normalized_session_id:
        entry = state["by_session"].get(normalized_session_id)
        if entry:
            return entry

    if allow_cwd_fallback:
        normalized_cwd = normalize_cwd(cwd)
        if normalized_cwd:
            entry = state["by_cwd"].get(normalized_cwd)
            if entry:
                return entry

    return None


def get_topic_binding_for_thread(chat_id, message_thread_id):
    entry = load_topic_state()["by_thread"].get(topic_thread_key(chat_id, message_thread_id))
    return entry if entry else None


def telegram_api_request(bot_token, method, payload):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError(f"{method} failed: {result}")
    return result.get("result", {})


def sanitize_topic_part(value, fallback):
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", " ", "/", "."} else " " for ch in str(value or ""))
    cleaned = " ".join(cleaned.split())
    return cleaned[:64] or fallback


def format_topic_cwd(cwd):
    normalized = normalize_cwd(cwd)
    if not normalized:
        return "session"

    try:
        rel_parts = list(Path(normalized).relative_to(Path.home()).parts)
    except Exception:
        rel_parts = [part for part in Path(normalized).parts if part not in {"", os.sep}]

    if not rel_parts:
        return "session"
    if len(rel_parts) == 1:
        display = rel_parts[0]
    elif len(rel_parts) == 2:
        display = "/".join(rel_parts)
    else:
        display = "../" + "/".join(rel_parts[-2:])

    return sanitize_topic_part(display, "session")


def build_topic_name(session_id, cwd):
    folder = format_topic_cwd(cwd)
    short_session = str(session_id or "").strip()[:8]
    if short_session:
        return trim_text(f"{folder} {short_session}", 120)
    return trim_text(folder, 120)


def ensure_session_topic(bot_token, chat_id, session_id, cwd):
    if not env_enabled("TELEGRAM_USE_TOPICS", True):
        return None

    entry = get_topic_binding_for_session(session_id, cwd, allow_cwd_fallback=False)
    if entry:
        return entry

    if not env_enabled("TELEGRAM_TOPIC_AUTO_CREATE", True):
        return None

    normalized_session_id = str(session_id or "").strip()
    normalized_chat_id = normalize_chat_id(chat_id)
    if not normalized_session_id or not normalized_chat_id:
        return None

    topic_name = build_topic_name(normalized_session_id, cwd)
    try:
        result = telegram_api_request(
            bot_token,
            "createForumTopic",
            {
                "chat_id": normalized_chat_id,
                "name": topic_name,
            },
        )
    except Exception as exc:
        log_topic_error(
            f"createForumTopic failed session={normalized_session_id} chat_id={normalized_chat_id} topic={topic_name} error={exc}"
        )
        return None

    message_thread_id = normalize_thread_id(result.get("message_thread_id"))
    if message_thread_id is None:
        log_topic_error(
            f"createForumTopic missing thread session={normalized_session_id} chat_id={normalized_chat_id} topic={topic_name}"
        )
        return None

    return register_topic_binding(
        normalized_session_id,
        cwd,
        normalized_chat_id,
        message_thread_id,
        topic_name=topic_name,
    )


def resolve_destination(bot_token, chat_id, session_id="", cwd="", preferred_thread_id=None):
    message_thread_id = normalize_thread_id(preferred_thread_id)
    if message_thread_id is not None:
        return normalize_chat_id(chat_id), message_thread_id

    normalized_session_id = str(session_id or "").strip()
    if normalized_session_id:
        entry = get_topic_binding_for_session(normalized_session_id, cwd, allow_cwd_fallback=False)
        if not entry:
            entry = ensure_session_topic(bot_token, chat_id, normalized_session_id, cwd)
    else:
        entry = get_topic_binding_for_session("", cwd, allow_cwd_fallback=True)

    if entry:
        return normalize_chat_id(entry.get("chat_id") or chat_id), normalize_thread_id(entry.get("message_thread_id"))

    return normalize_chat_id(chat_id), None

