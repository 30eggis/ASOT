# Portability and Secret Removal

## Problem

The current implementation is highly local-machine specific.

Examples:

- absolute paths under `/Users/ted`
- secrets stored directly in env files
- shell aliases hardcoded in `.zshrc`
- daemon state spread across multiple folders
- direct references to `~/.claude` and `~/.codex`

## Required Cleanup

### 1. Remove secrets from tracked files

Do not track:

- Telegram bot tokens
- Telegram chat ids
- API keys
- personal GitHub tokens
- local project paths that reveal private structure

Replace with:

- `templates/env.example`
- generated `~/.config/asot/asot.env`
- optional interactive prompts during `asot init`

### 2. Remove hardcoded home paths

Do not ship:

- `/Users/ted/...`

Replace with:

- `$HOME`
- `os.homedir()`
- XDG-style defaults:
  - config: `~/.config/asot`
  - data: `~/.local/share/asot`
  - state: `~/.local/state/asot`

### 3. Separate product code from generated integration files

Do not treat generated files as the source of truth.

Source of truth:

- repository code under `src/`
- templates under `templates/`

Generated integration:

- `~/.claude/hooks/asot/*`
- `~/.codex/asot/*`
- shell blocks
- launchd plist

### 4. Split stable code from machine state

Do not version:

- pid files
- logs
- runtime offsets
- session maps
- topic maps

Keep them under:

- `~/.local/state/asot`

### 5. Standardize naming

Use one product prefix:

- `asot`

Avoid mixed naming such as:

- `telegram-daemon`
- `codex-telegram-*`
- `telegram-hooks`

Those names can remain as compatibility shims, but the public product name should be consistent.

## Refactor Order

1. centralize shared python utilities
2. centralize daemon runtime
3. move agent-specific wrappers into `src/integrations/`
4. generate user-machine files from templates
5. delete hardcoded secrets and personal paths from committed content

