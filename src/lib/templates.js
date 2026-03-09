export function renderEnvFile(values) {
  const lines = [
    `export ASOT_TELEGRAM_BOT_TOKEN=${values.botToken}`,
    `export ASOT_TELEGRAM_CHAT_ID=${values.chatId}`,
    `export TELEGRAM_BOT_TOKEN=${values.botToken}`,
    `export TELEGRAM_CHAT_ID=${values.chatId}`,
    `export ASOT_ENABLE_CLAUDE=${values.enableClaude ? "1" : "0"}`,
    `export ASOT_ENABLE_CODEX=${values.enableCodex ? "1" : "0"}`,
    `export TELEGRAM_USE_TOPICS=${values.useTopics ? "1" : "0"}`,
    `export TELEGRAM_TOPIC_AUTO_CREATE=${values.autoCreateTopics ? "1" : "0"}`,
    `export TELEGRAM_TOPIC_PREFIX=${values.topicPrefix}`,
    `export TELEGRAM_NOTIFY_COMMENTARY=${values.notifyCommentary ? "1" : "0"}`,
    `export TELEGRAM_NOTIFY_FINAL=${values.notifyFinal ? "1" : "0"}`,
    `export TELEGRAM_NOTIFY_COMPLETE=${values.notifyComplete ? "1" : "0"}`,
    `export TELEGRAM_NOTIFY_PERMISSION=${values.notifyPermission ? "1" : "0"}`,
    `export TELEGRAM_NOTIFY_INPUT=${values.notifyInput ? "1" : "0"}`,
    `export TELEGRAM_NOTIFY_SANDBOX_ERROR=${values.notifySandboxError ? "1" : "0"}`
  ];
  return `${lines.join("\n")}\n`;
}

export function renderShellBlock(paths) {
  return `
cl() {
  if [ -n "$TMUX" ]; then
    bash "${paths.claudeHooksDir}/claude-tmux-register.sh" >/dev/null 2>&1 || true
    claude --dangerously-skip-permissions "$@"
  else
    "${paths.claudeHooksDir}/claude-tmux-launch.sh" --cwd "$PWD" --session "claude_$(basename "$PWD" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '_')" --attach -- "$@"
  fi
}

alias cld='cl --dangerously-skip-permissions'
alias cdx='${paths.codexDir}/codex-tmux-launch.sh --attach --'
alias tg-history='bash ${paths.claudeHooksDir}/telegram-history.sh'
alias tg-monitor='tail -f ${paths.claudeStateDir}/chat.log'
`.trim();
}

export function renderLaunchAgentPlist(paths) {
  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>com.asot.daemon</string>
    <key>ProgramArguments</key>
    <array>
      <string>/usr/bin/python3</string>
      <string>${paths.runtimeDaemonDir}/telegram-daemon.py</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
      <key>ASOT_CONFIG_DIR</key>
      <string>${paths.configDir}</string>
      <key>ASOT_SHARE_DIR</key>
      <string>${paths.shareDir}</string>
      <key>ASOT_STATE_DIR</key>
      <string>${paths.stateDir}</string>
      <key>PATH</key>
      <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${paths.stateDir}/daemon.log</string>
    <key>StandardErrorPath</key>
    <string>${paths.stateDir}/daemon.log</string>
  </dict>
</plist>
`;
}

export function renderInstallRecord(paths, values) {
  return JSON.stringify(
    {
      version: 1,
      installedAt: new Date().toISOString(),
      paths,
      options: values
    },
    null,
    2
  );
}

export function renderConfigFile(paths, values) {
  return JSON.stringify(
    {
      schemaVersion: 1,
      homeDir: paths.homeDir,
      configDir: paths.configDir,
      shareDir: paths.shareDir,
      stateDir: paths.stateDir,
      claudeHooksDir: paths.claudeHooksDir,
      codexDir: paths.codexDir,
      shellRc: paths.shellRc,
      launchAgentPath: paths.launchAgentPath,
      enableClaude: values.enableClaude,
      enableCodex: values.enableCodex
    },
    null,
    2
  );
}

export function buildClaudeHooksConfig(paths) {
  return {
    Stop: [
      {
        matcher: "",
        hooks: [
          {
            type: "command",
            command: `bash ${paths.claudeHooksDir}/telegram-notify.sh`,
            timeout: 10
          }
        ]
      }
    ],
    Notification: [
      {
        matcher: "permission_prompt",
        hooks: [
          {
            type: "command",
            command: `bash ${paths.claudeHooksDir}/telegram-permission-notify.sh`,
            timeout: 10
          }
        ]
      }
    ],
    PreToolUse: [
      {
        matcher: "AskUserQuestion|ExitPlanMode",
        hooks: [
          {
            type: "command",
            command: `bash ${paths.claudeHooksDir}/telegram-input-notify.sh`,
            timeout: 10
          }
        ]
      }
    ]
  };
}
