# Estimate

## Scope Bands

### 1. Bootstrap MVP

Target: prove installable packaging and document the system.

Expected work:

- repository structure
- CLI skeleton
- installer design
- docs and config templates

Estimate:

- 4 to 7 days

### 2. Usable Public Alpha

Target: another developer can install it on macOS with guided setup.

Expected work:

- `asot init`
- `asot doctor`
- `asot start|stop|restart`
- shell patching with backups
- launchd install
- Claude settings patching
- Codex watcher install
- config migration from hardcoded paths and secrets

Estimate:

- 2 to 3 weeks

### 3. Stable Open Source Product

Target: repeatable installs, upgrades, and issue handling.

Expected work:

- tests
- rollback or uninstall
- versioned config migration
- release process
- troubleshooting docs
- sample screenshots and demo flow

Estimate:

- 4 to 6 weeks

## Main Risks

- local path assumptions
- safe patching of user dotfiles
- launchd behavior on different macOS setups
- Codex watcher coupling to local session file formats
- Telegram security and secret handling

