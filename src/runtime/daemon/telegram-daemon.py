#!/usr/bin/env python3
"""
Shared Telegram daemon for Codex and Claude.

- Polls Telegram updates once per unique bot token
- Routes replies to Codex or Claude by message mapping or forum topic binding
- Keeps Codex session-watch notifications active
"""
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

HOME = Path.home()
CONFIG_DIR = Path(os.environ.get("ASOT_CONFIG_DIR", HOME / ".config" / "asot"))
SHARE_DIR = Path(os.environ.get("ASOT_SHARE_DIR", HOME / ".local" / "share" / "asot"))
STATE_DIR = Path(os.environ.get("ASOT_STATE_DIR", HOME / ".local" / "state" / "asot"))
PID_FILE = STATE_DIR / "daemon.pid"
LOCK_FILE = STATE_DIR / "daemon.lock"
DEFAULT_PATH = "/opt/homebrew/opt/node@22/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
CLAUDE_HISTORY_FILE = HOME / ".claude" / "history.jsonl"
ASOT_ENV_FILE = CONFIG_DIR / "asot.env"
CLAUDE_BASE_DIR = HOME / ".claude" / "hooks" / "asot"
CODEX_BASE_DIR = HOME / ".codex" / "asot"


@dataclass
class Bridge:
    agent: str
    base_dir: Path
    state_dir: Path
    env_file: Path
    mapping_file: Path
    topic_state_file: Path
    tmux_state_file: Path
    bot_token: str
    chat_id: str
    env: dict
    tmux_bin: str
    cli_bin: str = ""
    sessions_dir: Optional[Path] = None
    watch_state_file: Optional[Path] = None


LOCK_HANDLE = None


def read_env_file(path):
    values = {}
    if not path.exists():
        return values

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def resolve_bin(env, env_name, *candidates):
    explicit = env.get(env_name, "").strip() or os.environ.get(env_name, "").strip()
    if explicit:
        return explicit

    search_path = os.environ.get("PATH", "")
    if DEFAULT_PATH not in search_path:
        search_path = f"{DEFAULT_PATH}:{search_path}" if search_path else DEFAULT_PATH

    for candidate in candidates:
        resolved = shutil.which(candidate, path=search_path)
        if resolved:
            return resolved

    return candidates[0]


def build_bridges():
    bridges = []

    env = read_env_file(ASOT_ENV_FILE)
    bot_token = env.get("ASOT_TELEGRAM_BOT_TOKEN") or env.get("TELEGRAM_BOT_TOKEN")
    chat_id = env.get("ASOT_TELEGRAM_CHAT_ID") or env.get("TELEGRAM_CHAT_ID")

    if bot_token and chat_id and env_enabled_bridge(env, "ASOT_ENABLE_CODEX", True):
        codex_state = STATE_DIR / "codex"
        bridges.append(
            Bridge(
                agent="codex",
                base_dir=CODEX_BASE_DIR,
                state_dir=codex_state,
                env_file=ASOT_ENV_FILE,
                mapping_file=codex_state / "msg_session_map.json",
                topic_state_file=codex_state / "topic_sessions.json",
                tmux_state_file=codex_state / "tmux_sessions.json",
                bot_token=bot_token,
                chat_id=chat_id,
                env=env,
                tmux_bin=resolve_bin(env, "TMUX_BIN", "tmux"),
                cli_bin=resolve_bin(env, "CODEX_BIN", "codex"),
                sessions_dir=HOME / ".codex" / "sessions",
                watch_state_file=codex_state / "session_watch_state.json",
            )
        )

    if bot_token and chat_id and env_enabled_bridge(env, "ASOT_ENABLE_CLAUDE", True):
        claude_state = STATE_DIR / "claude"
        bridges.append(
            Bridge(
                agent="claude",
                base_dir=CLAUDE_BASE_DIR,
                state_dir=claude_state,
                env_file=ASOT_ENV_FILE,
                mapping_file=claude_state / "msg_session_map.json",
                topic_state_file=claude_state / "topic_sessions.json",
                tmux_state_file=claude_state / "tmux_sessions.json",
                bot_token=bot_token,
                chat_id=chat_id,
                env=env,
                tmux_bin=resolve_bin(env, "TMUX_BIN", "tmux"),
                cli_bin=resolve_bin(env, "CLAUDE_BIN", str(HOME / ".local" / "bin" / "claude"), "claude"),
            )
        )

    return bridges


def env_enabled_bridge(env, name, default=True):
    raw = env.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def env_enabled(bridge, name, default=True):
    raw = bridge.env.get(name)
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


def get_folder_name(cwd):
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


def extract_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [extract_text(item) for item in value]
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        value_type = value.get("type")
        if value_type == "text":
            return extract_text(value.get("text"))
        if "content" in value:
            return extract_text(value.get("content"))
        if "message" in value:
            return extract_text(value.get("message"))
        if "text" in value:
            return extract_text(value.get("text"))
    return str(value)


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def iter_claude_history_reverse():
    try:
        lines = CLAUDE_HISTORY_FILE.read_text(encoding="utf-8").splitlines()
    except Exception:
        return

    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except Exception:
            continue
        yield record


def resolve_claude_project_dir(session_id, fallback_cwd):
    normalized_session_id = str(session_id or "").strip()
    if normalized_session_id:
        for record in iter_claude_history_reverse() or []:
            if str(record.get("sessionId", "")).strip() != normalized_session_id:
                continue
            project_dir = normalize_cwd(record.get("project", ""))
            if project_dir and os.path.isdir(project_dir):
                return project_dir

    normalized_fallback = normalize_cwd(fallback_cwd)
    if normalized_fallback and os.path.isdir(normalized_fallback):
        return normalized_fallback
    return str(HOME)


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
    if len(text) <= 4000:
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


def load_mapping(bridge):
    return load_json(bridge.mapping_file, {})


def save_mapping(bridge, message_id, session_id, cwd, chat_id="", message_thread_id=None):
    if not message_id:
        return

    mapping = load_mapping(bridge)
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

    save_json(bridge.mapping_file, mapping)


def topic_thread_key(chat_id, message_thread_id):
    normalized_chat_id = normalize_chat_id(chat_id)
    normalized_thread_id = normalize_thread_id(message_thread_id)
    if not normalized_chat_id or normalized_thread_id is None:
        return ""
    return f"{normalized_chat_id}:{normalized_thread_id}"


def load_topic_state(bridge):
    state = load_json(bridge.topic_state_file, {})
    state.setdefault("by_session", {})
    state.setdefault("by_thread", {})
    state.setdefault("by_cwd", {})
    return state


def save_topic_state(bridge, state):
    save_json(bridge.topic_state_file, state)


def build_topic_entry(session_id, cwd, chat_id, message_thread_id, topic_name=""):
    return {
        "session_id": str(session_id or "").strip(),
        "cwd": str(cwd or "").strip(),
        "chat_id": normalize_chat_id(chat_id),
        "message_thread_id": normalize_thread_id(message_thread_id),
        "topic_name": str(topic_name or "").strip(),
        "updated_at": int(time.time()),
    }


def register_topic_binding(bridge, session_id, cwd, chat_id, message_thread_id, topic_name=""):
    thread_key = topic_thread_key(chat_id, message_thread_id)
    if not thread_key:
        return None

    entry = build_topic_entry(session_id, cwd, chat_id, message_thread_id, topic_name=topic_name)
    state = load_topic_state(bridge)
    state["by_thread"][thread_key] = entry

    normalized_cwd = normalize_cwd(cwd)
    if normalized_cwd:
        state["by_cwd"][normalized_cwd] = entry

    normalized_session_id = str(session_id or "").strip()
    if normalized_session_id:
        state["by_session"][normalized_session_id] = entry

    save_topic_state(bridge, state)
    return entry


def get_topic_binding_for_session(bridge, session_id, cwd="", allow_cwd_fallback=True):
    state = load_topic_state(bridge)

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


def get_topic_binding_for_thread(bridge, chat_id, message_thread_id):
    return load_topic_state(bridge)["by_thread"].get(topic_thread_key(chat_id, message_thread_id))


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
        rel_parts = list(Path(normalized).relative_to(HOME).parts)
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


def build_topic_name(bridge, session_id, cwd):
    folder = format_topic_cwd(cwd)
    short_session = str(session_id or "").strip()[:8]
    if short_session:
        return trim_text(f"{folder} {short_session}", 120)
    return trim_text(folder, 120)


def ensure_session_topic(bridge, session_id, cwd):
    if not env_enabled(bridge, "TELEGRAM_USE_TOPICS", True):
        return None

    entry = get_topic_binding_for_session(bridge, session_id, cwd, allow_cwd_fallback=False)
    if entry:
        return entry

    if not env_enabled(bridge, "TELEGRAM_TOPIC_AUTO_CREATE", True):
        return None

    normalized_session_id = str(session_id or "").strip()
    normalized_chat_id = normalize_chat_id(bridge.chat_id)
    if not normalized_session_id or not normalized_chat_id:
        return None

    topic_name = build_topic_name(bridge, normalized_session_id, cwd)
    try:
        result = telegram_api_request(
            bridge.bot_token,
            "createForumTopic",
            {
                "chat_id": normalized_chat_id,
                "name": topic_name,
            },
        )
    except Exception as exc:
        print(f"[TOPIC] {bridge.agent} create failed session={normalized_session_id}: {exc}", flush=True)
        return None

    message_thread_id = normalize_thread_id(result.get("message_thread_id"))
    if message_thread_id is None:
        return None

    print(
        f"[TOPIC] {bridge.agent} created session={normalized_session_id} thread={message_thread_id} name={topic_name}",
        flush=True,
    )
    return register_topic_binding(
        bridge,
        normalized_session_id,
        cwd,
        normalized_chat_id,
        message_thread_id,
        topic_name=topic_name,
    )


def resolve_destination(bridge, session_id="", cwd="", preferred_thread_id=None):
    message_thread_id = normalize_thread_id(preferred_thread_id)
    if message_thread_id is not None:
        return normalize_chat_id(bridge.chat_id), message_thread_id

    normalized_session_id = str(session_id or "").strip()
    if normalized_session_id:
        entry = get_topic_binding_for_session(bridge, normalized_session_id, cwd, allow_cwd_fallback=False)
        if not entry:
            entry = ensure_session_topic(bridge, normalized_session_id, cwd)
    else:
        entry = get_topic_binding_for_session(bridge, "", cwd, allow_cwd_fallback=True)

    if entry:
        return normalize_chat_id(entry.get("chat_id") or bridge.chat_id), normalize_thread_id(entry.get("message_thread_id"))

    return normalize_chat_id(bridge.chat_id), None


def load_tmux_state(bridge):
    state = load_json(bridge.tmux_state_file, {})
    state.setdefault("by_cwd", {})
    return state


def save_tmux_state(bridge, state):
    save_json(bridge.tmux_state_file, state)


def tmux_target_alive(bridge, target):
    if not target:
        return False
    try:
        result = subprocess.run(
            [bridge.tmux_bin, "list-panes", "-t", target],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def tmux_session_has_client(bridge, session_name):
    if not session_name:
        return False
    try:
        result = subprocess.run(
            [bridge.tmux_bin, "list-clients", "-F", "#{client_session}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False
        return any(line.strip() == session_name for line in result.stdout.splitlines())
    except Exception:
        return False


def resolve_tmux_target(bridge, cwd):
    normalized = normalize_cwd(cwd)
    state = load_tmux_state(bridge)
    by_cwd = state.setdefault("by_cwd", {})
    changed = False

    if normalized:
        info = by_cwd.get(normalized)
        if info:
            target = info.get("target", "")
            if tmux_target_alive(bridge, target):
                return target
            by_cwd.pop(normalized, None)
            changed = True

    live_targets = []
    for saved_cwd, info in list(by_cwd.items()):
        target = info.get("target", "")
        if tmux_target_alive(bridge, target):
            live_targets.append((saved_cwd, target))
        else:
            by_cwd.pop(saved_cwd, None)
            changed = True

    if changed:
        save_tmux_state(bridge, state)

    if normalized:
        best_target = ""
        best_len = -1
        for saved_cwd, target in live_targets:
            if not saved_cwd:
                continue
            if normalized == saved_cwd or normalized.startswith(saved_cwd + os.sep):
                if len(saved_cwd) > best_len:
                    best_target = target
                    best_len = len(saved_cwd)
        if best_target:
            return best_target

    if env_enabled(bridge, "TELEGRAM_TMUX_FALLBACK_SINGLE", True) and len(live_targets) == 1:
        return live_targets[0][1]

    return ""


def forward_reply_via_tmux(bridge, cwd, reply_text):
    if not env_enabled(bridge, "TELEGRAM_USE_TMUX", True):
        return False, ""

    target = resolve_tmux_target(bridge, cwd)
    if not target:
        return False, "no tmux target registered"

    if bridge.agent == "claude":
        try:
            pane_info = subprocess.run(
                [bridge.tmux_bin, "display-message", "-p", "-t", target, "#{pane_current_command}\t#{pane_title}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if pane_info.returncode != 0:
                return False, "tmux target is not a live Claude pane"
            current_command, _, pane_title = pane_info.stdout.partition("\t")
            current_command = current_command.strip().lower()
            pane_title = pane_title.strip().lower()
            if current_command != "claude" and "claude code" not in pane_title:
                state = load_tmux_state(bridge)
                by_cwd = state.setdefault("by_cwd", {})
                for saved_cwd, info in list(by_cwd.items()):
                    if str(info.get("target", "")).strip() == target:
                        by_cwd.pop(saved_cwd, None)
                save_tmux_state(bridge, state)
                return False, "tmux target is not a live Claude pane"
        except Exception:
            return False, "tmux target is not a live Claude pane"

    payload = f"[recv_msg_tg] {reply_text}"

    try:
        subprocess.run([bridge.tmux_bin, "set-buffer", "--", payload], check=True)
        subprocess.run([bridge.tmux_bin, "paste-buffer", "-t", target], check=True)
        time.sleep(0.05)
        subprocess.run([bridge.tmux_bin, "send-keys", "-t", target, "C-m"], check=True)
        return True, target
    except FileNotFoundError:
        return False, f"tmux binary missing: {bridge.tmux_bin}"
    except subprocess.CalledProcessError as exc:
        return False, f"tmux failed: {exc}"


def register_tmux_target(bridge, cwd, target, session_name=""):
    normalized_cwd = normalize_cwd(cwd)
    if not normalized_cwd or not target:
        return False

    state = load_tmux_state(bridge)
    state.setdefault("by_cwd", {})[normalized_cwd] = {
        "target": target,
        "session_name": session_name,
        "updated_at": int(time.time()),
    }
    save_tmux_state(bridge, state)
    return True


def get_registered_tmux_entry(bridge, cwd):
    normalized_cwd = normalize_cwd(cwd)
    if not normalized_cwd:
        return None

    state = load_tmux_state(bridge)
    by_cwd = state.setdefault("by_cwd", {})
    info = by_cwd.get(normalized_cwd)
    if info:
        return info

    best = None
    best_len = -1
    for saved_cwd, info in by_cwd.items():
        if normalized_cwd == saved_cwd or normalized_cwd.startswith(saved_cwd + os.sep):
            if len(saved_cwd) > best_len:
                best = info
                best_len = len(saved_cwd)
    return best


def build_claude_tmux_session_name(session_id, cwd):
    resume_cwd = resolve_claude_project_dir(session_id, cwd)
    base_name = Path(resume_cwd).name or "claude"
    safe_name = "".join(ch.lower() if ch.isalnum() else "_" for ch in base_name).strip("_") or "claude"
    return f"claude_{safe_name}_{str(session_id or '').strip()[:8]}"


def recover_existing_claude_tmux_session(bridge, session_id, cwd):
    session_name = build_claude_tmux_session_name(session_id, cwd)
    try:
        result = subprocess.run(
            [
                bridge.tmux_bin,
                "list-panes",
                "-t",
                session_name,
                "-F",
                "#{pane_id}\t#{pane_current_path}\t#{pane_current_command}\t#{pane_title}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        return False, f"tmux lookup failed: {exc}"

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "tmux session not found").strip()
        return False, trim_text(detail, 300)

    pane_lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not pane_lines:
        return False, "tmux session exists but no panes were found"

    selected = None
    fallback = None
    for line in pane_lines:
        parts = line.split("\t", 3)
        target = parts[0].strip()
        pane_cwd = parts[1].strip() if len(parts) > 1 else cwd
        current_command = parts[2].strip().lower() if len(parts) > 2 else ""
        pane_title = parts[3].strip().lower() if len(parts) > 3 else ""
        if fallback is None:
            fallback = (target, pane_cwd, current_command, pane_title)
        if current_command == "claude" or "claude code" in pane_title:
            selected = (target, pane_cwd, current_command, pane_title)
            break

    if selected is None:
        try:
            subprocess.run([bridge.tmux_bin, "kill-session", "-t", session_name], check=True, timeout=10)
        except Exception:
            pass
        return False, "existing tmux session had no live Claude pane"

    target, pane_cwd, _, _ = selected
    register_tmux_target(bridge, pane_cwd, target, session_name=session_name)
    maybe_reveal_tmux_session_in_iterm(bridge, session_name, target)
    return True, target


def launch_claude_tmux_resume(bridge, session_id, cwd, allow_retry=True):
    if bridge.agent != "claude":
        return False, ""

    launch_script = bridge.base_dir / "claude-tmux-launch.sh"
    if not launch_script.exists():
        return False, f"launch script missing: {launch_script}"

    resume_cwd = resolve_claude_project_dir(session_id, cwd)
    session_name = build_claude_tmux_session_name(session_id, cwd)

    env = os.environ.copy()
    env.update(bridge.env)
    env["HOME"] = str(HOME)
    env["PATH"] = f"{HOME / '.local' / 'bin'}:{DEFAULT_PATH}"
    env.pop("CLAUDECODE", None)

    cmd = [
        str(launch_script),
        "--cwd",
        resume_cwd,
        "--session",
        session_name,
        "--",
        "--resume",
        session_id,
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=resume_cwd,
            capture_output=True,
            text=True,
            env=env,
            timeout=45,
        )
    except subprocess.TimeoutExpired:
        return False, "claude tmux launch timed out"
    except Exception as exc:
        return False, f"claude tmux launch failed: {exc}"

    if result.returncode != 0:
        error_text = (result.stderr or result.stdout or "claude tmux launch failed").strip()
        if "session already exists" in error_text:
            recovered, target = recover_existing_claude_tmux_session(bridge, session_id, cwd)
            if recovered:
                return True, target
            if allow_retry:
                return launch_claude_tmux_resume(bridge, session_id, cwd, allow_retry=False)
        return False, trim_text(error_text, 300)

    time.sleep(1.0)
    target = resolve_tmux_target(bridge, cwd) or resolve_tmux_target(bridge, resume_cwd)
    maybe_reveal_tmux_session_in_iterm(bridge, session_name, target)
    if target:
        return True, target
    return False, "claude tmux launched but target was not registered"


def reveal_tmux_session_in_iterm(session_name, pane_target=""):
    helper_script = BASE_DIR / "open-tmux-session-in-iterm.sh"
    if not session_name or not helper_script.exists():
        return False, "iTerm helper missing"

    env = os.environ.copy()
    env["HOME"] = str(HOME)
    env["PATH"] = DEFAULT_PATH

    try:
        result = subprocess.run(
            [str(helper_script), str(session_name), str(pane_target or "")],
            capture_output=True,
            text=True,
            env=env,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        return False, "iTerm attach timed out"
    except Exception as exc:
        return False, f"iTerm attach failed: {exc}"

    if result.returncode == 0:
        detail = f"session={session_name}"
        if pane_target:
            detail += f" pane={pane_target}"
        print(f"[GUI] iTerm attached {detail}", flush=True)
        return True, session_name

    detail = (result.stderr or result.stdout or "iTerm attach failed").strip()
    print(f"[GUI] iTerm attach failed session={session_name}: {trim_text(detail, 300)}", flush=True)
    return False, trim_text(detail, 300)


def maybe_reveal_tmux_session_in_iterm(bridge, session_name, pane_target=""):
    if tmux_session_has_client(bridge, session_name):
        return False, "tmux session already has a client"
    return reveal_tmux_session_in_iterm(session_name, pane_target)


def reveal_registered_tmux_session(bridge, cwd):
    info = get_registered_tmux_entry(bridge, cwd)
    if not info:
        return
    session_name = str(info.get("session_name", "")).strip()
    target = str(info.get("target", "")).strip()
    if session_name:
        maybe_reveal_tmux_session_in_iterm(bridge, session_name, target)


def log_chat(bridge, role, text, folder=""):
    chat_log_file = bridge.state_dir / "chat.log"
    bridge.state_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%H:%M:%S")
    prefix = f"[{folder}] " if folder else ""
    label = "TG User" if role == "user" else bridge.agent.capitalize()
    separator = ">" if role == "user" else " "
    lines = str(text or "").strip().split("\n")
    with chat_log_file.open("a", encoding="utf-8") as file_handle:
        file_handle.write(f"\n{ts} {prefix}[{label}]\n")
        for line in lines:
            file_handle.write(f"  {separator} {line}\n")


def token_offset_file(bot_token):
    digest = hashlib.sha1(bot_token.encode("utf-8")).hexdigest()[:16]
    return STATE_DIR / f"offset_{digest}.txt"


def get_last_offset(bot_token):
    try:
        return int(token_offset_file(bot_token).read_text(encoding="utf-8").strip())
    except Exception:
        return 0


def save_offset(bot_token, offset):
    path = token_offset_file(bot_token)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(offset), encoding="utf-8")


def get_updates(bot_token, offset):
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates?offset={offset}&timeout=30"
    try:
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=35)
        data = json.loads(resp.read().decode("utf-8"))
        return data.get("result", [])
    except Exception as exc:
        print(f"[ERROR] getUpdates failed: {exc}", flush=True)
        return []


def run_codex_and_send(bridge, cmd, cwd, fallback_msg, session_id="", message_thread_id=None):
    with tempfile.NamedTemporaryFile(prefix="codex_reply_", suffix=".txt", delete=False) as tmp:
        out_file = tmp.name

    full_cmd = cmd + ["-o", out_file]
    run_cwd = cwd if cwd and os.path.isdir(cwd) else str(HOME)

    try:
        env = os.environ.copy()
        env.update(bridge.env)
        env["PATH"] = DEFAULT_PATH
        env.pop("CLAUDECODE", None)

        result = subprocess.run(
            full_cmd,
            cwd=run_cwd,
            capture_output=True,
            text=True,
            timeout=600,
            env=env,
        )

        if result.returncode != 0:
            error_text = (result.stderr or result.stdout or "codex command failed").strip()
            dest_chat_id, dest_thread_id = resolve_destination(
                bridge,
                session_id=session_id,
                cwd=run_cwd,
                preferred_thread_id=message_thread_id,
            )
            send_telegram_auto(
                f"⚠️ [Codex] Execution failed\n{error_text[:1200]}",
                bridge.bot_token,
                dest_chat_id,
                message_thread_id=dest_thread_id,
            )
            return

        try:
            output = Path(out_file).read_text(encoding="utf-8").strip()
        except Exception:
            output = ""

        dest_chat_id, dest_thread_id = resolve_destination(
            bridge,
            session_id=session_id,
            cwd=run_cwd,
            preferred_thread_id=message_thread_id,
        )
        if output:
            header = "✅ [Codex] Reply"
            sent_msg_id = send_telegram_auto(
                f"{header}\n{output}",
                bridge.bot_token,
                dest_chat_id,
                caption=header,
                message_thread_id=dest_thread_id,
            )
        else:
            sent_msg_id = send_telegram_auto(
                fallback_msg,
                bridge.bot_token,
                dest_chat_id,
                message_thread_id=dest_thread_id,
            )

        if sent_msg_id and session_id:
            save_mapping(
                bridge,
                sent_msg_id,
                session_id,
                run_cwd,
                chat_id=dest_chat_id,
                message_thread_id=dest_thread_id,
            )
    except subprocess.TimeoutExpired:
        dest_chat_id, dest_thread_id = resolve_destination(
            bridge,
            session_id=session_id,
            cwd=run_cwd,
            preferred_thread_id=message_thread_id,
        )
        send_telegram_auto(
            "⏰ [Codex] Session timed out (10min).",
            bridge.bot_token,
            dest_chat_id,
            message_thread_id=dest_thread_id,
        )
    except Exception as exc:
        dest_chat_id, dest_thread_id = resolve_destination(
            bridge,
            session_id=session_id,
            cwd=run_cwd,
            preferred_thread_id=message_thread_id,
        )
        send_telegram_auto(
            f"❌ [Codex] Execution error: {str(exc)[:400]}",
            bridge.bot_token,
            dest_chat_id,
            message_thread_id=dest_thread_id,
        )
    finally:
        try:
            os.unlink(out_file)
        except Exception:
            pass


def resume_codex_session(bridge, session_id, cwd, reply_text, message_thread_id=None):
    tagged_text = f"[{cwd or os.getcwd()}] [recv_msg_tg] {reply_text}"
    cmd = [
        bridge.cli_bin,
        "exec",
        "resume",
        session_id,
        tagged_text,
        "--full-auto",
        "--skip-git-repo-check",
    ]
    run_codex_and_send(
        bridge,
        cmd,
        cwd,
        "ℹ️ [Codex] Empty response.",
        session_id=session_id,
        message_thread_id=message_thread_id,
    )


def resume_codex_last(bridge, reply_text, message_thread_id=None):
    default_cwd = bridge.env.get("CODEX_DEFAULT_CWD", str(HOME))
    tagged_text = f"[{default_cwd or os.getcwd()}] [recv_msg_tg] {reply_text}"
    cmd = [
        bridge.cli_bin,
        "exec",
        "resume",
        "--last",
        tagged_text,
        "--full-auto",
        "--skip-git-repo-check",
    ]
    run_codex_and_send(
        bridge,
        cmd,
        default_cwd,
        "ℹ️ [Codex] Processed on last session but response was empty.",
        message_thread_id=message_thread_id,
    )


def resume_claude_session(bridge, session_id, cwd, reply_text, chat_id, message_thread_id=None):
    tagged_text = f"[recv_msg_tg] {reply_text}"
    resume_cwd = resolve_claude_project_dir(session_id, cwd)
    cmd = [
        bridge.cli_bin,
        "--dangerously-skip-permissions",
        "--resume",
        session_id,
        "--print",
        "--permission-mode",
        "acceptEdits",
        tagged_text,
    ]

    env = os.environ.copy()
    env.update(bridge.env)
    env["HOME"] = str(HOME)
    env["PATH"] = f"{HOME / '.local' / 'bin'}:{DEFAULT_PATH}"
    env.pop("CLAUDECODE", None)

    try:
        result = subprocess.run(
            cmd,
            cwd=resume_cwd,
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
        )
        if result.stdout.strip():
            print(
                f"[OK] Claude responded ({len(result.stdout.strip())} chars) cwd={resume_cwd}",
                flush=True,
            )
            return

        stderr = result.stderr.strip()
        if stderr:
            print(
                f"[CLAUDE ERR] session={session_id} cwd={resume_cwd} stderr={trim_text(stderr, 300)}",
                flush=True,
            )
            if "Not logged in" in stderr:
                send_telegram(
                    "⚠️ [Claude Code] Telegram resume is unavailable in the daemon environment.\n"
                    "Reason: Claude CLI is not logged in for launchd.\n"
                    "Use a tmux Claude session registered with ~/.claude/hooks/asot/claude-tmux-register.sh, "
                    "or provide Claude auth to the daemon environment.",
                    bridge.bot_token,
                    chat_id,
                    message_thread_id=message_thread_id,
                )
                return
            send_telegram(
                f"⚠️ [Claude Code] Error: {stderr[:500]}",
                bridge.bot_token,
                chat_id,
                message_thread_id=message_thread_id,
            )
    except subprocess.TimeoutExpired:
        send_telegram(
            "⏰ [Claude Code] Session timed out (5min)",
            bridge.bot_token,
            chat_id,
            message_thread_id=message_thread_id,
        )
    except Exception as exc:
        send_telegram(
            f"❌ [Claude Code] Resume failed: {str(exc)[:200]}",
            bridge.bot_token,
            chat_id,
            message_thread_id=message_thread_id,
        )


def handle_mapped_reply(bridge, reply_msg_id, reply_text, in_chat, message_thread_id):
    mapping = load_mapping(bridge)
    info = mapping.get(reply_msg_id)
    if not info:
        return False

    session_id = str(info.get("session_id", "")).strip()
    cwd = str(info.get("cwd", "")).strip()
    mapped_chat_id = normalize_chat_id(info.get("chat_id", in_chat) or in_chat)
    mapped_thread_id = normalize_thread_id(info.get("message_thread_id", message_thread_id))
    incoming_thread_id = normalize_thread_id(message_thread_id)

    if mapped_chat_id != normalize_chat_id(in_chat):
        return False

    if mapped_thread_id is not None or incoming_thread_id is not None:
        if mapped_thread_id != incoming_thread_id:
            return False

    if mapped_thread_id is not None:
        register_topic_binding(bridge, session_id, cwd, mapped_chat_id, mapped_thread_id)

    log_chat(bridge, "user", reply_text, get_folder_name(cwd))

    ok, detail = forward_reply_via_tmux(bridge, cwd, reply_text)
    if ok:
        reveal_registered_tmux_session(bridge, cwd)
        print(f"[TMUX] {bridge.agent} forwarded reply target={detail}", flush=True)
        return True

    if bridge.agent == "claude" and detail in {"no tmux target registered", "tmux target is not a live Claude pane"}:
        launched, launch_detail = launch_claude_tmux_resume(bridge, session_id, cwd)
        if launched:
            ok, detail = forward_reply_via_tmux(bridge, cwd, reply_text)
            if ok:
                print(f"[TMUX] claude auto-resumed reply target={detail}", flush=True)
                return True
        if launch_detail:
            print(f"[TMUX] claude auto-resume failed: {launch_detail}", flush=True)

    if detail:
        print(f"[TMUX] {bridge.agent} fallback session resume: {detail}", flush=True)

    if bridge.agent == "codex":
        resume_codex_session(bridge, session_id, cwd, reply_text, message_thread_id=mapped_thread_id)
    else:
        resume_claude_session(bridge, session_id, cwd, reply_text, mapped_chat_id, message_thread_id=mapped_thread_id)
    return True


def handle_thread_reply(bridge, reply_text, in_chat, message_thread_id):
    thread_info = get_topic_binding_for_thread(bridge, in_chat, message_thread_id)
    if not thread_info or not thread_info.get("session_id"):
        return False

    session_id = str(thread_info.get("session_id", "")).strip()
    cwd = str(thread_info.get("cwd", "")).strip()
    log_chat(bridge, "user", reply_text, get_folder_name(cwd))

    ok, detail = forward_reply_via_tmux(bridge, cwd, reply_text)
    if ok:
        reveal_registered_tmux_session(bridge, cwd)
        print(f"[TMUX] {bridge.agent} forwarded thread reply target={detail}", flush=True)
        return True

    if bridge.agent == "claude" and detail in {"no tmux target registered", "tmux target is not a live Claude pane"}:
        launched, launch_detail = launch_claude_tmux_resume(bridge, session_id, cwd)
        if launched:
            ok, detail = forward_reply_via_tmux(bridge, cwd, reply_text)
            if ok:
                print(f"[TMUX] claude auto-resumed thread reply target={detail}", flush=True)
                return True
        if launch_detail:
            print(f"[TMUX] claude auto-resume failed: {launch_detail}", flush=True)

    if detail:
        print(f"[TMUX] {bridge.agent} fallback thread session resume: {detail}", flush=True)

    if bridge.agent == "codex":
        resume_codex_session(bridge, session_id, cwd, reply_text, message_thread_id=message_thread_id)
    else:
        resume_claude_session(bridge, session_id, cwd, reply_text, in_chat, message_thread_id=message_thread_id)
    return True


def handle_bridge_fallback(bridge, reply_text, in_chat, message_thread_id, candidate_count):
    if bridge.agent != "codex" or candidate_count != 1:
        return False

    default_cwd = bridge.env.get("CODEX_DEFAULT_CWD", str(HOME))
    if message_thread_id is not None:
        register_topic_binding(bridge, "", default_cwd, in_chat, message_thread_id)

    ok, detail = forward_reply_via_tmux(bridge, default_cwd, reply_text)
    if ok:
        reveal_registered_tmux_session(bridge, default_cwd)
        print(f"[TMUX] codex forwarded fallback reply target={detail}", flush=True)
        return True

    if detail:
        print(f"[TMUX] codex fallback last resume: {detail}", flush=True)

    resume_codex_last(bridge, reply_text, message_thread_id=message_thread_id)
    return True


def reply_loop_for_token(bot_token, bridges, chat_token_counts, stop_event):
    offset = get_last_offset(bot_token)

    while not stop_event.is_set():
        try:
            updates = get_updates(bot_token, offset + 1)
            for update in updates:
                offset = update.get("update_id", offset)
                save_offset(bot_token, offset)

                msg = update.get("message", {})
                in_chat = normalize_chat_id(msg.get("chat", {}).get("id", ""))
                reply_text = (msg.get("text") or "").strip()
                if not in_chat or not reply_text:
                    continue

                reply_to = msg.get("reply_to_message", {})
                reply_msg_id = str(reply_to.get("message_id", ""))
                message_thread_id = normalize_thread_id(
                    msg.get("message_thread_id", reply_to.get("message_thread_id"))
                )

                candidates = [bridge for bridge in bridges if normalize_chat_id(bridge.chat_id) == in_chat]
                if not candidates:
                    continue

                print(
                    f"[INBOUND] chat={in_chat} thread={message_thread_id or '-'} reply_to={reply_msg_id or '-'} text={trim_text(reply_text, 120)}",
                    flush=True,
                )

                consumed = False
                if message_thread_id is not None:
                    for bridge in candidates:
                        if handle_thread_reply(bridge, reply_text, in_chat, message_thread_id):
                            consumed = True
                            break

                if not consumed and reply_msg_id:
                    for bridge in candidates:
                        if handle_mapped_reply(bridge, reply_msg_id, reply_text, in_chat, message_thread_id):
                            consumed = True
                            break

                if not consumed:
                    for bridge in candidates:
                        if handle_thread_reply(bridge, reply_text, in_chat, message_thread_id):
                            consumed = True
                            break

                if not consumed:
                    for bridge in candidates:
                        if handle_bridge_fallback(bridge, reply_text, in_chat, message_thread_id, len(candidates)):
                            consumed = True
                            break

                if not consumed and chat_token_counts.get(in_chat, 0) <= 1:
                    print(
                        f"[UNMATCHED] chat={in_chat} thread={message_thread_id or '-'} reply_to={reply_msg_id or '-'}",
                        flush=True,
                    )
                    send_telegram(
                        "⚠️ Session not found for this message or topic.",
                        bot_token,
                        in_chat,
                        message_thread_id=message_thread_id,
                    )

            if not updates:
                stop_event.wait(2)
        except Exception as exc:
            print(f"[ERROR] reply loop: {exc}", flush=True)
            stop_event.wait(10)


def load_watch_state(bridge):
    return load_json(bridge.watch_state_file, {"offsets": {}})


def save_watch_state(bridge, state):
    save_json(bridge.watch_state_file, state)


def iter_session_files(bridge):
    if not bridge.sessions_dir or not bridge.sessions_dir.exists():
        return []
    return sorted(bridge.sessions_dir.rglob("*.jsonl"), key=lambda path: path.stat().st_mtime)


def parse_json_string(value):
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return {}
    return {}


def session_info_for(path, session_cache):
    key = str(path)
    info = session_cache.get(key)
    if info:
        return info

    try:
        with path.open("r", encoding="utf-8") as file_handle:
            first_line = file_handle.readline()
    except Exception:
        return {"session_id": "", "cwd": ""}

    try:
        record = json.loads(first_line)
    except Exception:
        return {"session_id": "", "cwd": ""}

    if record.get("type") == "session_meta":
        payload = record.get("payload", {})
        info = {
            "session_id": str(payload.get("id", "")).strip(),
            "cwd": str(payload.get("cwd", "")).strip(),
        }
        session_cache[key] = info
        return info

    return {"session_id": "", "cwd": ""}


def send_event_notification(bridge, kind, session_id, cwd, title, body):
    header = f"{title} [{get_folder_name(cwd)}]"
    text = f"{header}\n{body}".strip()
    if session_id:
        text += "\n\n💬 Reply to this message to continue"
    caption = header if len(text) > 200 else ""
    dest_chat_id, dest_thread_id = resolve_destination(bridge, session_id=session_id, cwd=cwd)
    message_id = send_telegram_auto(
        text,
        bridge.bot_token,
        dest_chat_id,
        caption=caption,
        message_thread_id=dest_thread_id,
    )
    if message_id and session_id:
        save_mapping(
            bridge,
            message_id,
            session_id,
            cwd,
            chat_id=dest_chat_id,
            message_thread_id=dest_thread_id,
        )
    if session_id and dest_thread_id is not None:
        register_topic_binding(bridge, session_id, cwd, dest_chat_id, dest_thread_id)
    print(f"[NOTIFY] {bridge.agent}:{kind} session={session_id or '-'} folder={get_folder_name(cwd)}", flush=True)


def notify_agent_message(bridge, payload, session_id, cwd):
    phase = payload.get("phase", "")
    message = trim_text(extract_text(payload.get("message", "")), 7000)
    if not message:
        return

    if phase == "commentary":
        if env_enabled(bridge, "TELEGRAM_NOTIFY_COMMENTARY", True):
            send_event_notification(bridge, "commentary", session_id, cwd, "ℹ️ [Codex]", message)
        return

    if phase == "final_answer":
        if env_enabled(bridge, "TELEGRAM_NOTIFY_FINAL", True):
            send_event_notification(bridge, "final", session_id, cwd, "✅ [Codex]", message)
        return

    if env_enabled(bridge, "TELEGRAM_NOTIFY_MESSAGES", False):
        send_event_notification(bridge, "message", session_id, cwd, "💬 [Codex]", message)


def notify_permission_request(bridge, payload, session_id, cwd):
    if not env_enabled(bridge, "TELEGRAM_NOTIFY_PERMISSION", True):
        return

    arguments = parse_json_string(payload.get("arguments"))
    if arguments.get("sandbox_permissions") != "require_escalated":
        return

    tool_name = payload.get("name", "")
    justification = trim_text(arguments.get("justification", ""), 400)
    command = trim_text(arguments.get("cmd") or arguments.get("command") or "", 400)
    lines = []
    if tool_name:
        lines.append(f"Tool: {tool_name}")
    if justification:
        lines.append(f"Why: {justification}")
    if command:
        lines.append(f"Command: {command}")
    if not lines:
        lines.append("Escalated permission is required.")

    send_event_notification(
        bridge,
        "permission",
        session_id,
        cwd,
        "⏳ [Codex] Permission Required",
        "\n".join(lines),
    )


def notify_input_request(bridge, payload, session_id, cwd):
    if not env_enabled(bridge, "TELEGRAM_NOTIFY_INPUT", True):
        return

    if payload.get("name") != "request_user_input":
        return

    arguments = parse_json_string(payload.get("arguments"))
    questions = arguments.get("questions") or []
    if questions:
        first = questions[0] if isinstance(questions[0], dict) else {}
        title = trim_text(first.get("header", "Input Required"), 80)
        body = trim_text(first.get("question", "User input is required."), 500)
    else:
        title = "Input Required"
        body = "User input is required."

    send_event_notification(bridge, "input", session_id, cwd, f"❓ [Codex] {title}", body)


def notify_function_output(bridge, payload, session_id, cwd):
    if not env_enabled(bridge, "TELEGRAM_NOTIFY_SANDBOX_ERROR", True):
        return

    output = str(payload.get("output", "")).strip()
    if not output:
        return

    lower = output.lower()
    markers = ["operation not permitted", "sandbox(denied", "network policy", "require_escalated"]
    if not any(marker in lower for marker in markers):
        return

    send_event_notification(
        bridge,
        "sandbox_error",
        session_id,
        cwd,
        "⚠️ [Codex] Sandbox/Error",
        trim_text(output, 1200),
    )


def notify_event_msg(bridge, payload, session_id, cwd):
    event_type = payload.get("type", "")
    if event_type == "agent_message":
        notify_agent_message(bridge, payload, session_id, cwd)
        return

    if event_type == "task_complete":
        if env_enabled(bridge, "TELEGRAM_NOTIFY_COMPLETE", True):
            send_event_notification(
                bridge,
                "complete",
                session_id,
                cwd,
                "🏁 [Codex] Task Complete",
                trim_text(payload.get("last_agent_message", "Task complete"), 500),
            )
        return

    if event_type == "turn_aborted" and env_enabled(bridge, "TELEGRAM_NOTIFY_ABORTED", True):
        send_event_notification(
            bridge,
            "aborted",
            session_id,
            cwd,
            "🛑 [Codex] Turn Aborted",
            "The current turn was aborted.",
        )


def process_record(bridge, path, record, session_cache):
    record_type = record.get("type")
    payload = record.get("payload", {})
    path_key = str(path)

    if record_type == "session_meta":
        session_cache[path_key] = {
            "session_id": str(payload.get("id", "")).strip(),
            "cwd": str(payload.get("cwd", "")).strip(),
        }
        return

    info = session_info_for(path, session_cache)
    session_id = info.get("session_id", "")
    cwd = info.get("cwd", "")

    if record_type == "event_msg":
        notify_event_msg(bridge, payload, session_id, cwd)
        return

    if record_type != "response_item":
        return

    payload_type = payload.get("type", "")
    if payload_type == "function_call":
        notify_permission_request(bridge, payload, session_id, cwd)
        notify_input_request(bridge, payload, session_id, cwd)
        return

    if payload_type == "function_call_output":
        notify_function_output(bridge, payload, session_id, cwd)


def prime_existing_files(bridge, state):
    offsets = state.setdefault("offsets", {})
    if offsets:
        return
    for path in iter_session_files(bridge):
        try:
            offsets[str(path)] = path.stat().st_size
        except Exception:
            continue
    save_watch_state(bridge, state)


def watch_sessions(bridge, stop_event):
    state = load_watch_state(bridge)
    prime_existing_files(bridge, state)
    offsets = state.setdefault("offsets", {})
    session_cache = {}

    while not stop_event.is_set():
        try:
            changed = False
            for path in iter_session_files(bridge):
                path_key = str(path)
                if path_key not in offsets:
                    offsets[path_key] = 0
                    changed = True

                current_size = path.stat().st_size
                start_offset = offsets.get(path_key, 0)
                if start_offset > current_size:
                    start_offset = 0

                if current_size == start_offset:
                    session_info_for(path, session_cache)
                    continue

                with path.open("r", encoding="utf-8") as file_handle:
                    file_handle.seek(start_offset)
                    while True:
                        line = file_handle.readline()
                        if not line:
                            break
                        try:
                            record = json.loads(line)
                        except Exception:
                            continue
                        process_record(bridge, path, record, session_cache)
                    offsets[path_key] = file_handle.tell()
                    changed = True

            if changed:
                save_watch_state(bridge, state)
        except Exception as exc:
            print(f"[ERROR] {bridge.agent} session watch: {exc}", flush=True)

        stop_event.wait(2)


def write_pid():
    global LOCK_HANDLE

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOCK_HANDLE = open(LOCK_FILE, "w", encoding="utf-8")
    try:
        fcntl.flock(LOCK_HANDLE.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("[EXIT] Another telegram-daemon instance is already running", flush=True)
        sys.exit(0)

    LOCK_HANDLE.write(str(os.getpid()))
    LOCK_HANDLE.flush()
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")


def main():
    bridges = build_bridges()
    if not bridges:
        print("[ERROR] No configured Telegram bridges found", flush=True)
        return 1

    os.environ.pop("CLAUDECODE", None)
    write_pid()
    print(f"[START] Shared Telegram Daemon PID={os.getpid()}", flush=True)
    for bridge in bridges:
        print(
            f"[BRIDGE] agent={bridge.agent} chat={bridge.chat_id} token_hash={hashlib.sha1(bridge.bot_token.encode('utf-8')).hexdigest()[:8]}",
            flush=True,
        )

    stop_event = threading.Event()
    threads = []

    by_token = {}
    chat_tokens = {}
    for bridge in bridges:
        by_token.setdefault(bridge.bot_token, []).append(bridge)
        chat_id = normalize_chat_id(bridge.chat_id)
        chat_tokens.setdefault(chat_id, set()).add(bridge.bot_token)

    chat_token_counts = {chat_id: len(tokens) for chat_id, tokens in chat_tokens.items()}

    for bot_token, token_bridges in by_token.items():
        thread = threading.Thread(
            target=reply_loop_for_token,
            args=(bot_token, token_bridges, chat_token_counts, stop_event),
            daemon=True,
            name=f"reply-{hashlib.sha1(bot_token.encode('utf-8')).hexdigest()[:8]}",
        )
        thread.start()
        threads.append(thread)

    for bridge in bridges:
        if bridge.agent == "codex" and bridge.sessions_dir and bridge.watch_state_file:
            thread = threading.Thread(
                target=watch_sessions,
                args=(bridge, stop_event),
                daemon=True,
                name=f"watch-{bridge.agent}",
            )
            thread.start()
            threads.append(thread)

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("[STOP] interrupted", flush=True)
    finally:
        stop_event.set()
        for thread in threads:
            thread.join(timeout=1)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
