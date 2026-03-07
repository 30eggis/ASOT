# Architecture

## Goal

Turn a private local setup for Telegram + Claude + Codex into an installable product.

## Current Reality

The original setup is distributed across:

- Claude hook files
- Codex watcher scripts
- Telegram daemon process
- tmux launcher/register helpers
- shell aliases in `.zshrc`
- launchd registration on macOS
- multiple env files with bot secrets and chat routing

## Product Boundary

ASOT should own:

- runtime daemon
- generated env files
- generated shell integration
- Claude integration templates
- Codex integration templates
- install and diagnostic CLI

ASOT should not own:

- Claude binary
- Codex binary
- tmux installation
- Telegram bot creation

## Integration Model

### Claude

Claude supports explicit hook registration in settings JSON.

ASOT should generate:

- hook scripts
- settings fragments or safe patch operations
- env file references

### Codex

Codex currently relies on session log watching rather than a first-class local hook model.

ASOT should provide:

- session watcher
- event filters
- tmux reply forwarding
- Telegram topic routing

## First Public Release

The first release should target:

- macOS
- zsh
- tmux
- Telegram topics
- Claude Code
- OpenAI Codex CLI

