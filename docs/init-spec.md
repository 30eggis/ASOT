# Init Specification

## Command

`asot init`

## Purpose

Turn a clean local machine into a configured ASOT environment without requiring manual edits across multiple dotfiles.

## Inputs Collected

- Telegram bot token
- Telegram chat id
- Whether Telegram topics should be used
- Whether commentary notifications should be enabled
- Preferred shell rc file
- Whether Claude integration should be installed
- Whether Codex integration should be installed
- Whether launchd should be installed on macOS

## Files Generated

### ASOT-owned config

- `~/.config/asot/asot.env`
- `~/.config/asot/config.json`
- `~/.config/asot/install.json`

### ASOT runtime

- `~/.local/share/asot/bin/*`
- `~/.local/share/asot/runtime/*`
- `~/.local/state/asot/*`

### Claude generated files

- `~/.claude/hooks/asot/telegram-notify.sh`
- `~/.claude/hooks/asot/telegram-permission-notify.sh`
- `~/.claude/hooks/asot/telegram-input-notify.sh`
- `~/.claude/hooks/asot/claude-tmux-launch.sh`
- `~/.claude/hooks/asot/claude-tmux-register.sh`
- `~/.claude/hooks/asot/telegram-chat-monitor.sh`

### Codex generated files

- `~/.codex/asot/codex-tmux-launch.sh`
- `~/.codex/asot/codex-tmux-register.sh`
- `~/.codex/asot/codex-telegram-notify.sh`
- `~/.codex/asot/codex-telegram-input-notify.sh`

### macOS generated files

- `~/Library/LaunchAgents/com.asot.daemon.plist`

## Files Patched

- `~/.claude/settings.json`
- `~/.zshrc`

Optional future support:

- `~/.bashrc`
- `~/.zprofile`
- `~/.codex/config.toml`

## Patch Rules

### General

- create a timestamped backup before first patch
- be idempotent on repeated runs
- only modify ASOT-owned sections
- preserve comments and ordering where possible
- fail with a clear diff preview if safe patching is not possible

### Shell patching

Use markers:

- `# >>> ASOT START >>>`
- `# <<< ASOT END <<<`

Rules:

- if the block exists, replace only that block
- if the block does not exist, append at end of file
- never rewrite the full shell rc file

### Claude settings patching

Rules:

- parse JSON
- merge only the required hook entries
- do not remove user hooks outside ASOT-owned commands
- store ASOT hook commands under a stable path such as `~/.claude/hooks/asot/*`

### Launchd patching

Rules:

- write a dedicated ASOT plist only
- never mutate unrelated launch agents
- support `install`, `uninstall`, and `doctor`

## Doctor Checks After Init

- `tmux` exists
- `claude` exists
- `codex` exists
- `python3` exists
- ASOT env file exists and is readable
- Claude settings contain ASOT hook entries
- shell block exists
- launchd plist exists
- daemon can start

