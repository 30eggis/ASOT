#!/usr/bin/env node

import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

import { runInit } from "./lib/init.js";
import { resolvePaths } from "./lib/paths.js";
import { runUninstall } from "./lib/uninstall.js";

function parseArgs(argv) {
  const result = {
    _: []
  };

  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (!value.startsWith("--")) {
      result._.push(value);
      continue;
    }

    const [key, inlineValue] = value.slice(2).split("=", 2);
    if (inlineValue !== undefined) {
      result[key] = inlineValue;
      continue;
    }

    const next = argv[index + 1];
    if (!next || next.startsWith("--")) {
      result[key] = true;
      continue;
    }

    result[key] = next;
    index += 1;
  }

  return result;
}

function printHelp() {
  console.log(`ASOT

Usage:
  asot init [--home DIR] [--bot-token TOKEN] [--chat-id CHAT_ID]
  asot uninstall [--home DIR]
  asot doctor [--home DIR]
  asot start [--home DIR]
  asot stop [--home DIR]
  asot restart [--home DIR]
  asot help

Examples:
  asot init --bot-token 123:abc --chat-id -100999
  asot init --home /tmp/asot-home --bot-token test --chat-id 1 --launchd=false
`);
}

function parseBoolean(value, fallback = false) {
  if (value === undefined) {
    return fallback;
  }
  if (typeof value === "boolean") {
    return value;
  }
  return !["0", "false", "no", "off"].includes(String(value).trim().toLowerCase());
}

async function runDoctor(args) {
  const paths = resolvePaths({ homeDir: args.home, shellRc: args["shell-rc"] });
  const checks = [
    ["env", paths.envFile],
    ["config", paths.configFile],
    ["install", paths.installFile],
    ["shell", paths.shellRc],
    ["claude-hooks", paths.claudeHooksDir],
    ["codex", paths.codexDir],
    ["runtime-python", path.join(paths.runtimePythonDir, "telegram_common.py")],
    ["runtime-daemon", path.join(paths.runtimeDaemonDir, "telegram-daemon.py")]
  ];

  for (const [label, targetPath] of checks) {
    try {
      await fs.access(targetPath);
      console.log(`ok   ${label} ${targetPath}`);
    } catch {
      console.log(`miss ${label} ${targetPath}`);
    }
  }

  if (process.platform === "darwin") {
    try {
      await fs.access(paths.launchAgentPath);
      console.log(`ok   launchd ${paths.launchAgentPath}`);
    } catch {
      console.log(`miss launchd ${paths.launchAgentPath}`);
    }
  }
}

async function runDaemonCommand(command, args) {
  const paths = resolvePaths({ homeDir: args.home, shellRc: args["shell-rc"] });
  const ctlPath = path.join(paths.runtimeDaemonDir, "daemon-ctl.sh");

  const child = spawn("bash", [ctlPath, command], {
    stdio: "inherit",
    env: {
      ...process.env,
      HOME: paths.homeDir,
      ASOT_CONFIG_DIR: paths.configDir,
      ASOT_SHARE_DIR: paths.shareDir,
      ASOT_STATE_DIR: paths.stateDir
    }
  });

  await new Promise((resolve, reject) => {
    child.on("exit", (code) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(`daemon command failed: ${command}`));
    });
    child.on("error", reject);
  });
}

async function main() {
  const argv = parseArgs(process.argv.slice(2));
  const command = argv._[0] || "help";

  switch (command) {
    case "help":
    case "--help":
    case "-h":
      printHelp();
      return;
    case "init": {
      const result = await runInit({
        homeDir: argv.home,
        shellRc: argv["shell-rc"],
        botToken: argv["bot-token"],
        chatId: argv["chat-id"],
        enableClaude: argv.claude,
        enableCodex: argv.codex,
        useTopics: argv.topics,
        autoCreateTopics: argv["topic-auto-create"],
        topicPrefix: argv["topic-prefix"],
        notifyCommentary: argv.commentary,
        notifyFinal: argv.final,
        notifyComplete: argv.complete,
        notifyPermission: argv.permission,
        notifyInput: argv.input,
        notifySandboxError: argv["sandbox-error"],
        installLaunchd: argv.launchd,
        yes: parseBoolean(argv.yes, false)
      });
      console.log(`ASOT init complete`);
      console.log(`config: ${result.paths.configDir}`);
      console.log(`share: ${result.paths.shareDir}`);
      console.log(`state: ${result.paths.stateDir}`);
      console.log(`shell: ${result.paths.shellRc}`);
      if (result.values.installLaunchd) {
        console.log(`launchd: ${result.paths.launchAgentPath}`);
      }
      return;
    }
    case "uninstall": {
      const result = await runUninstall({
        homeDir: argv.home,
        shellRc: argv["shell-rc"]
      });
      console.log(`ASOT uninstall complete`);
      console.log(`config removed: ${result.paths.configDir}`);
      console.log(`share removed: ${result.paths.shareDir}`);
      console.log(`state removed: ${result.paths.stateDir}`);
      console.log(`shell cleaned: ${result.paths.shellRc}`);
      return;
    }
    case "doctor":
      await runDoctor(argv);
      return;
    case "start":
    case "stop":
    case "restart":
      await runDaemonCommand(command, argv);
      return;
    default:
      console.error(`Unknown command: ${command}`);
      printHelp();
      process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
