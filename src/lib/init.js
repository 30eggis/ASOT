import fs from "node:fs/promises";
import path from "node:path";
import readline from "node:readline/promises";
import { fileURLToPath } from "node:url";

import { backupIfNeeded, copyFileEnsured, ensureDir, patchManagedBlock, pathExists, writeFileEnsured } from "./fs.js";
import { resolvePaths } from "./paths.js";
import {
  buildClaudeHooksConfig,
  renderConfigFile,
  renderEnvFile,
  renderInstallRecord,
  renderLaunchAgentPlist,
  renderShellBlock
} from "./templates.js";

const START_MARKER = "# >>> ASOT START >>>";
const END_MARKER = "# <<< ASOT END <<<";
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..", "..");

function parseBoolean(value, fallback) {
  if (value === undefined || value === null || value === "") {
    return fallback;
  }
  const normalized = String(value).trim().toLowerCase();
  return !["0", "false", "no", "off"].includes(normalized);
}

async function promptIfMissing(question, fallback) {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout
  });
  try {
    const suffix = fallback ? ` [${fallback}]` : "";
    const answer = (await rl.question(`${question}${suffix}: `)).trim();
    return answer || fallback || "";
  } finally {
    rl.close();
  }
}

async function readLegacyDefaults(homeDir) {
  const candidates = [
    path.join(homeDir, ".codex", "telegram-hooks", "telegram.env"),
    path.join(homeDir, ".claude", "hooks", "telegram.env")
  ];
  const result = {};
  for (const filePath of candidates) {
    if (!(await pathExists(filePath))) {
      continue;
    }
    const text = await fs.readFile(filePath, "utf8");
    for (const rawLine of text.split("\n")) {
      let line = rawLine.trim();
      if (!line || line.startsWith("#")) {
        continue;
      }
      if (line.startsWith("export ")) {
        line = line.slice(7);
      }
      const idx = line.indexOf("=");
      if (idx === -1) {
        continue;
      }
      const key = line.slice(0, idx).trim();
      const value = line.slice(idx + 1).trim();
      if (!(key in result)) {
        result[key] = value;
      }
    }
  }
  return result;
}

function resolveSource(relativePath) {
  return path.join(repoRoot, relativePath);
}

function stripLegacyShellAliases(content) {
  return content
    .split("\n")
    .filter((line) => {
      const trimmed = line.trim();
      return !/^(?:alias|unalias)\s+(?:cl|cld|cdx|tg-history|tg-monitor)(?:\b|=)/.test(trimmed);
    })
    .join("\n");
}

async function sanitizeShellRc(shellRcPath) {
  if (!(await pathExists(shellRcPath))) {
    return;
  }

  const content = await fs.readFile(shellRcPath, "utf8");
  const cleaned = stripLegacyShellAliases(content);
  if (cleaned !== content) {
    await writeFileEnsured(shellRcPath, cleaned);
  }
}

async function copyInstallFiles(paths) {
  const copies = [
    ["src/runtime/daemon/telegram-daemon.py", path.join(paths.runtimeDaemonDir, "telegram-daemon.py"), 0o755],
    ["src/runtime/daemon/daemon-ctl.sh", path.join(paths.runtimeDaemonDir, "daemon-ctl.sh"), 0o755],
    ["src/runtime/python/telegram_common.py", path.join(paths.runtimePythonDir, "telegram_common.py"), 0o644],
    ["src/integrations/claude/hooks/telegram-notify.sh", path.join(paths.claudeHooksDir, "telegram-notify.sh"), 0o755],
    ["src/integrations/claude/hooks/telegram-permission-notify.sh", path.join(paths.claudeHooksDir, "telegram-permission-notify.sh"), 0o755],
    ["src/integrations/claude/hooks/telegram-input-notify.sh", path.join(paths.claudeHooksDir, "telegram-input-notify.sh"), 0o755],
    ["src/integrations/claude/tmux/claude-tmux-launch.sh", path.join(paths.claudeHooksDir, "claude-tmux-launch.sh"), 0o755],
    ["src/integrations/claude/tmux/claude-tmux-register.sh", path.join(paths.claudeHooksDir, "claude-tmux-register.sh"), 0o755],
    ["src/integrations/claude/ui/telegram-chat-monitor.sh", path.join(paths.claudeHooksDir, "telegram-chat-monitor.sh"), 0o755],
    ["src/integrations/claude/ui/telegram-history.sh", path.join(paths.claudeHooksDir, "telegram-history.sh"), 0o755],
    ["src/integrations/codex/scripts/codex-telegram-notify.sh", path.join(paths.codexDir, "codex-telegram-notify.sh"), 0o755],
    ["src/integrations/codex/scripts/codex-telegram-input-notify.sh", path.join(paths.codexDir, "codex-telegram-input-notify.sh"), 0o755],
    ["src/integrations/codex/tmux/codex-tmux-launch.sh", path.join(paths.codexDir, "codex-tmux-launch.sh"), 0o755],
    ["src/integrations/codex/tmux/codex-tmux-register.sh", path.join(paths.codexDir, "codex-tmux-register.sh"), 0o755],
    ["src/platform/macos/open-tmux-session-in-iterm.sh", path.join(paths.runtimePlatformMacosDir, "open-tmux-session-in-iterm.sh"), 0o755],
    ["src/integrations/playwright/screenshot-to-telegram.sh", path.join(paths.runtimePlaywrightDir, "screenshot-to-telegram.sh"), 0o755]
  ];

  for (const [sourceRel, targetPath, mode] of copies) {
    await copyFileEnsured(resolveSource(sourceRel), targetPath, mode);
  }
}

function mergeClaudeHooks(settings, hooksConfig) {
  const next = settings || {};
  next.hooks ||= {};

  for (const [eventName, entries] of Object.entries(hooksConfig)) {
    next.hooks[eventName] ||= [];
    for (const entry of entries) {
      const existing = next.hooks[eventName].find((item) => item.matcher === entry.matcher);
      if (!existing) {
        next.hooks[eventName].push(entry);
        continue;
      }
      existing.hooks ||= [];
      for (const hook of entry.hooks) {
        const found = existing.hooks.some(
          (candidate) =>
            candidate.type === hook.type &&
            candidate.command === hook.command &&
            candidate.timeout === hook.timeout
        );
        if (!found) {
          existing.hooks.push(hook);
        }
      }
    }
  }

  return next;
}

async function patchClaudeSettings(paths) {
  const settingsPath = path.join(paths.homeDir, ".claude", "settings.json");
  await ensureDir(path.dirname(settingsPath));
  await backupIfNeeded(settingsPath);

  let settings = {};
  if (await pathExists(settingsPath)) {
    settings = JSON.parse(await fs.readFile(settingsPath, "utf8"));
  }

  const merged = mergeClaudeHooks(settings, buildClaudeHooksConfig(paths));
  await writeFileEnsured(settingsPath, `${JSON.stringify(merged, null, 2)}\n`);
}

async function resetRuntimeState(paths) {
  const resetFiles = [
    path.join(paths.claudeStateDir, "msg_session_map.json"),
    path.join(paths.claudeStateDir, "topic_sessions.json"),
    path.join(paths.claudeStateDir, "tmux_sessions.json"),
    path.join(paths.codexStateDir, "msg_session_map.json"),
    path.join(paths.codexStateDir, "topic_sessions.json"),
    path.join(paths.codexStateDir, "tmux_sessions.json"),
    path.join(paths.stateDir, "daemon.pid")
  ];

  await Promise.all(resetFiles.map((filePath) => fs.rm(filePath, { force: true })));

  const stateEntries = await fs.readdir(paths.stateDir, { withFileTypes: true }).catch(() => []);
  await Promise.all(
    stateEntries
      .filter((entry) => entry.isFile() && /^offset_[a-f0-9]{16}\.txt$/.test(entry.name))
      .map((entry) => fs.rm(path.join(paths.stateDir, entry.name), { force: true }))
  );
}

export async function runInit(args = {}) {
  const paths = resolvePaths({ homeDir: args.homeDir, shellRc: args.shellRc });
  const legacy = await readLegacyDefaults(paths.homeDir);

  let botToken = args.botToken || legacy.TELEGRAM_BOT_TOKEN || legacy.ASOT_TELEGRAM_BOT_TOKEN || "";
  let chatId = args.chatId || legacy.TELEGRAM_CHAT_ID || legacy.ASOT_TELEGRAM_CHAT_ID || "";

  const interactive = process.stdin.isTTY && !args.yes;
  if (!botToken && interactive) {
    botToken = await promptIfMissing("Telegram bot token");
  }
  if (!chatId && interactive) {
    chatId = await promptIfMissing("Telegram chat id");
  }
  if (!botToken || !chatId) {
    throw new Error("Missing Telegram bot token or chat id. Pass --bot-token and --chat-id.");
  }

  const values = {
    botToken,
    chatId,
    enableClaude: parseBoolean(args.enableClaude, true),
    enableCodex: parseBoolean(args.enableCodex, true),
    useTopics: parseBoolean(args.useTopics ?? legacy.TELEGRAM_USE_TOPICS, true),
    autoCreateTopics: parseBoolean(
      args.autoCreateTopics ?? legacy.TELEGRAM_TOPIC_AUTO_CREATE,
      true
    ),
    topicPrefix: args.topicPrefix || legacy.TELEGRAM_TOPIC_PREFIX || "asot",
    notifyCommentary: parseBoolean(args.notifyCommentary, false),
    notifyFinal: parseBoolean(args.notifyFinal, true),
    notifyComplete: parseBoolean(args.notifyComplete, true),
    notifyPermission: parseBoolean(args.notifyPermission, true),
    notifyInput: parseBoolean(args.notifyInput, true),
    notifySandboxError: parseBoolean(args.notifySandboxError, true),
    installLaunchd: parseBoolean(args.installLaunchd, process.platform === "darwin")
  };

  await Promise.all([
    ensureDir(paths.configDir),
    ensureDir(paths.shareDir),
    ensureDir(paths.stateDir),
    ensureDir(paths.claudeStateDir),
    ensureDir(paths.codexStateDir),
    ensureDir(paths.claudeHooksDir),
    ensureDir(paths.codexDir)
  ]);

  await writeFileEnsured(paths.envFile, renderEnvFile(values), 0o600);
  await writeFileEnsured(paths.configFile, `${renderConfigFile(paths, values)}\n`);
  await writeFileEnsured(paths.installFile, `${renderInstallRecord(paths, values)}\n`);
  await copyInstallFiles(paths);
  await resetRuntimeState(paths);
  await patchClaudeSettings(paths);
  await backupIfNeeded(paths.shellRc);
  await sanitizeShellRc(paths.shellRc);
  await patchManagedBlock(
    paths.shellRc,
    START_MARKER,
    END_MARKER,
    renderShellBlock(paths)
  );

  if (values.installLaunchd) {
    await ensureDir(path.dirname(paths.launchAgentPath));
    await writeFileEnsured(paths.launchAgentPath, renderLaunchAgentPlist(paths));
  }

  return { paths, values };
}
