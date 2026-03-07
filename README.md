# ASOT

AI Sessions On Telegram.

ASOT is a local-first runtime and installer for running Claude Code and OpenAI Codex with Telegram, tmux, and a background daemon.

It solves one specific problem:

- send Claude and Codex outputs to Telegram
- let you reply from Telegram back into the live agent session
- keep tmux-backed sessions attachable on your local machine
- install the shell aliases, Claude hooks, Codex helpers, and launchd files needed for that workflow

## What ASOT Does

ASOT is not another chat client. It is an installer and runtime bridge for a local development workflow.

Main features:

- Telegram notifications for Claude Code and Codex
- reply routing from Telegram back into tmux sessions
- Claude hook installation
- Codex session watcher installation
- shell alias installation for `cl`, `cld`, `cdx`, `tg-history`, and `tg-monitor`
- macOS daemon file generation
- `init`, `doctor`, `start`, `stop`, `restart` commands

## Current Status

This repository is in bootstrap alpha.

Implemented now:

- `asot init`
- `asot doctor`
- `asot start`
- `asot stop`
- `asot restart`
- Claude settings patching
- shell block patching
- ASOT-managed install layout under `~/.config/asot`, `~/.local/share/asot`, and `~/.local/state/asot`

Not finalized yet:

- npm publication
- uninstall flow
- migration from older personal layouts
- production-grade test coverage

## Target Environment

The first supported target is:

- macOS
- zsh
- tmux
- Claude Code
- OpenAI Codex CLI

Linux support may be possible later, but it is not the first target.

## Prerequisites

Before installing ASOT, prepare the following:

- `python3`
- `node`
- `tmux`
- macOS with `launchd`
- `zsh`
- Claude Code CLI installed and working
- Codex CLI installed and working
- iTerm2 or another terminal that can run tmux comfortably
- a Telegram bot
- a Telegram group or supergroup where the bot can post

## Telegram Setup

ASOT expects Telegram to be prepared before `asot init`.

Recommended setup:

1. Create a Telegram bot with BotFather.
2. Save the bot token.
3. Create a Telegram group or supergroup for agent notifications.
4. Add the bot to that group.
5. Allow the bot to send messages in that chat.
6. If you want per-session topics, convert the chat to a forum-enabled supergroup.
7. If topics are enabled, promote the bot so it can manage topics.
8. For the most reliable inbound reply handling, disable BotFather privacy mode or confirm your reply pattern is delivered to the bot.
9. Obtain the target chat id for the group or supergroup.

What ASOT needs from Telegram:

- bot token
- target chat id
- optional topic usage

Telegram notes:

- Plain group mode works if you mainly reply directly to bot messages.
- Topic mode is better for long-running sessions because ASOT can bind one session to one thread.
- If ASOT creates forum topics automatically, the bot must have the Telegram permission needed to create topics in that supergroup.
- If the bot cannot see inbound replies, check BotFather privacy mode first.
- Chat ids for supergroups usually look like `-100...`.

## Installation

### Today, from this repository

ASOT is not published to npm yet.

For local development:

```bash
git clone git@github.com:30eggis/ASOT.git
cd ASOT
npm install
npm link
```

Then run:

```bash
asot init --bot-token YOUR_BOT_TOKEN --chat-id YOUR_CHAT_ID
```

If you want ASOT to skip launchd file generation during development:

```bash
asot init --bot-token YOUR_BOT_TOKEN --chat-id YOUR_CHAT_ID --launchd=false
```

After init, start the daemon:

```bash
asot start
```

### Later, after npm publish

The intended install flow is:

```bash
npm install -g asot
asot init --bot-token YOUR_BOT_TOKEN --chat-id YOUR_CHAT_ID
```

## What `asot init` Generates

ASOT writes managed files into these locations:

- `~/.config/asot/asot.env`
- `~/.config/asot/config.json`
- `~/.config/asot/install.json`
- `~/.local/share/asot/runtime/...`
- `~/.local/state/asot/...`
- `~/.claude/hooks/asot/...`
- `~/.codex/asot/...`

It also patches:

- `~/.claude/settings.json`
- `~/.zshrc`

Patch safety rules:

- ASOT only writes its own managed block in shell rc files
- ASOT backs up patched files on first write
- ASOT does not rewrite your whole `.zshrc`
- ASOT merges Claude hooks instead of replacing the whole hook config

## Commands

```bash
asot init --bot-token TOKEN --chat-id CHAT_ID
asot doctor
asot start
asot stop
asot restart
```

Useful options:

- `--home DIR` for testing in an isolated fake home
- `--launchd=false` to skip macOS launchd plist generation
- `--topics=true|false`
- `--commentary=true|false`
- `--claude=true|false`
- `--codex=true|false`

## Shell Commands Installed

ASOT installs a managed shell block that defines:

- `cl`
- `cld`
- `cdx`
- `tg-history`
- `tg-monitor`

These are installed into an ASOT-owned block inside `~/.zshrc`.

## Safety

ASOT is designed to avoid touching a running personal setup unless you explicitly run its installer against your real home directory.

Repository work in this repo does not modify:

- your live Telegram daemon
- your current `~/.claude/hooks`
- your current `~/.codex/telegram-hooks`
- your current launchd setup

For development, prefer:

- `asot init --home /tmp/asot-home-test ...`
- `asot doctor --home /tmp/asot-home-test`
- `HOME=/tmp/asot-home-test asot start --home /tmp/asot-home-test`

## Repository Layout

- `src/cli.js` CLI entrypoint
- `src/lib/` installer and patch utilities
- `src/runtime/` shared daemon and Python runtime
- `src/integrations/claude/` Claude-specific scripts
- `src/integrations/codex/` Codex-specific scripts
- `docs/` architecture and rollout notes
- `templates/` sample env and future install templates

Key planning docs:

- `docs/module-map.md`
- `docs/init-spec.md`
- `docs/portability.md`
- `docs/architecture.md`
- `docs/estimate.md`

## Development Notes

The product direction is:

- npm as the primary distribution channel
- GitHub as the source of truth
- later optional plugin-style onboarding where useful

The central design rule is:

- keep product code in the repository
- generate machine-specific integration files during install
- never commit bot tokens, chat ids, logs, or runtime state
