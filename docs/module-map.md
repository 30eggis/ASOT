# Module Map

## Goal

Map the current local implementation into a publishable repository layout.

## Source Inventory

### Shared daemon and macOS runtime

Current sources:

- `~/.telegram-daemon/telegram-daemon.py`
- `~/.telegram-daemon/telegram-daemon-ctl.sh`
- `~/.telegram-daemon/open-tmux-session-in-iterm.sh`
- `~/.telegram-daemon/playwright-screenshot-to-telegram.sh`

Target modules:

- `src/runtime/daemon/telegram-daemon.py`
- `src/runtime/daemon/daemon-ctl.sh`
- `src/platform/macos/open-tmux-session-in-iterm.sh`
- `src/integrations/playwright/screenshot-to-telegram.sh`

### Shared Telegram utilities

Current sources:

- `~/.claude/hooks/telegram_common.py`
- `~/.codex/telegram-hooks/telegram_common.py`

Target module:

- `src/runtime/python/telegram_common.py`

Notes:

- keep one shared implementation
- generate thin wrappers per integration

### Claude integration

Current sources:

- `~/.claude/hooks/telegram-notify.sh`
- `~/.claude/hooks/telegram-permission-notify.sh`
- `~/.claude/hooks/telegram-input-notify.sh`
- `~/.claude/hooks/claude-tmux-launch.sh`
- `~/.claude/hooks/claude-tmux-register.sh`
- `~/.claude/hooks/telegram-chat-monitor.sh`
- `~/.claude/settings.json` hook registration

Target modules:

- `src/integrations/claude/hooks/telegram-notify.sh`
- `src/integrations/claude/hooks/telegram-permission-notify.sh`
- `src/integrations/claude/hooks/telegram-input-notify.sh`
- `src/integrations/claude/tmux/claude-tmux-launch.sh`
- `src/integrations/claude/tmux/claude-tmux-register.sh`
- `src/integrations/claude/ui/telegram-chat-monitor.sh`
- `templates/claude/settings.fragment.json`

Installer behavior:

- generate scripts into a managed install location
- patch Claude settings with ASOT-owned hook entries only

### Codex integration

Current sources:

- `~/.codex/telegram-hooks/codex-telegram-notify.sh`
- `~/.codex/telegram-hooks/codex-telegram-input-notify.sh`
- `~/.codex/telegram-hooks/codex-tmux-launch.sh`
- `~/.codex/telegram-hooks/codex-tmux-register.sh`
- `~/.codex/config.toml`

Target modules:

- `src/integrations/codex/scripts/codex-telegram-notify.sh`
- `src/integrations/codex/scripts/codex-telegram-input-notify.sh`
- `src/integrations/codex/tmux/codex-tmux-launch.sh`
- `src/integrations/codex/tmux/codex-tmux-register.sh`
- `templates/codex/config.fragment.toml`

Installer behavior:

- install helper scripts
- optionally patch `~/.zshrc`
- use ASOT watcher rather than pretending Codex has the same hook model as Claude

### Shell integration

Current sources:

- `~/.zshrc` entries for `cl`, `cld`, `cdx`, `tg-history`, `tg-monitor`

Target modules:

- `templates/shell/zshrc.block.zsh`
- `src/install/shell/install-shell.js`

Installer behavior:

- append a managed block between markers
- never edit unrelated shell content

### Runtime state

Current sources:

- `~/.claude/hooks/telegram-state/*`
- `~/.codex/telegram-hooks/state/*`
- `~/.telegram-daemon/state/*`

Target design:

- `~/.local/state/asot/`
  - `daemon.pid`
  - `daemon.log`
  - `msg_session_map.json`
  - `topic_sessions.json`
  - `tmux_sessions.json`
  - `session_watch_state.json`

Notes:

- centralize runtime state
- keep agent-specific subdirectories only if separation is required

## Files To Exclude From Product

- any `*.log`
- any `*.pid`
- any live state files
- local bot tokens and chat IDs
- project-specific experiments such as `~/.claude/hooks/spec-it/telegram-config.js`

