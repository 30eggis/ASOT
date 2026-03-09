import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

import { backupIfNeeded, pathExists, removeManagedBlock } from "./fs.js";
import { resolvePaths } from "./paths.js";

const START_MARKER = "# >>> ASOT START >>>";
const END_MARKER = "# <<< ASOT END <<<";

function removeClaudeHooksConfig(settings, paths) {
  if (!settings || typeof settings !== "object" || !settings.hooks || typeof settings.hooks !== "object") {
    return settings || {};
  }

  const next = { ...settings, hooks: { ...settings.hooks } };

  for (const [eventName, entries] of Object.entries(next.hooks)) {
    if (!Array.isArray(entries)) {
      delete next.hooks[eventName];
      continue;
    }

    const keptEntries = entries
      .map((entry) => {
        const hooks = Array.isArray(entry?.hooks) ? entry.hooks : [];
        const keptHooks = hooks.filter((hook) => {
          const command = String(hook?.command || "");
          return !command.includes(paths.claudeHooksDir);
        });
        if (!keptHooks.length) {
          return null;
        }
        return { ...entry, hooks: keptHooks };
      })
      .filter(Boolean);

    if (keptEntries.length) {
      next.hooks[eventName] = keptEntries;
    } else {
      delete next.hooks[eventName];
    }
  }

  if (!Object.keys(next.hooks).length) {
    delete next.hooks;
  }

  return next;
}

async function patchClaudeSettingsForUninstall(paths) {
  const settingsPath = path.join(paths.homeDir, ".claude", "settings.json");
  if (!(await pathExists(settingsPath))) {
    return false;
  }

  const raw = await fs.readFile(settingsPath, "utf8");
  let settings;
  try {
    settings = JSON.parse(raw);
  } catch {
    return false;
  }

  const cleaned = removeClaudeHooksConfig(settings, paths);
  const next = `${JSON.stringify(cleaned, null, 2)}\n`;
  if (next === raw) {
    return false;
  }

  await backupIfNeeded(settingsPath);
  await fs.writeFile(settingsPath, next, "utf8");
  return true;
}

async function stopDaemon(paths) {
  const ctlPath = path.join(paths.runtimeDaemonDir, "daemon-ctl.sh");
  if (!(await pathExists(ctlPath))) {
    return;
  }

  await new Promise((resolve) => {
    const child = spawn("bash", [ctlPath, "stop"], {
      stdio: "ignore",
      env: {
        ...process.env,
        HOME: paths.homeDir,
        ASOT_CONFIG_DIR: paths.configDir,
        ASOT_SHARE_DIR: paths.shareDir,
        ASOT_STATE_DIR: paths.stateDir
      }
    });
    child.on("exit", () => resolve());
    child.on("error", () => resolve());
  });
}

export async function runUninstall(args = {}) {
  const paths = resolvePaths({ homeDir: args.homeDir, shellRc: args.shellRc });

  await stopDaemon(paths);

  await backupIfNeeded(paths.shellRc);
  await removeManagedBlock(paths.shellRc, START_MARKER, END_MARKER);
  await patchClaudeSettingsForUninstall(paths);

  await Promise.all([
    fs.rm(paths.launchAgentPath, { force: true }),
    fs.rm(paths.claudeHooksDir, { recursive: true, force: true }),
    fs.rm(paths.codexDir, { recursive: true, force: true }),
    fs.rm(paths.shareDir, { recursive: true, force: true }),
    fs.rm(paths.stateDir, { recursive: true, force: true }),
    fs.rm(paths.configDir, { recursive: true, force: true })
  ]);

  return { paths };
}
