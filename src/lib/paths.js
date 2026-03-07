import os from "node:os";
import path from "node:path";

export function resolvePaths(options = {}) {
  const homeDir = path.resolve(options.homeDir || os.homedir());
  const configDir = path.join(homeDir, ".config", "asot");
  const shareDir = path.join(homeDir, ".local", "share", "asot");
  const stateDir = path.join(homeDir, ".local", "state", "asot");
  const claudeHooksDir = path.join(homeDir, ".claude", "hooks", "asot");
  const codexDir = path.join(homeDir, ".codex", "asot");
  const shellRc = options.shellRc
    ? path.resolve(options.shellRc)
    : path.join(homeDir, ".zshrc");
  const launchAgentPath = path.join(
    homeDir,
    "Library",
    "LaunchAgents",
    "com.asot.daemon.plist"
  );

  return {
    homeDir,
    configDir,
    shareDir,
    stateDir,
    claudeHooksDir,
    codexDir,
    shellRc,
    launchAgentPath,
    runtimeDir: path.join(shareDir, "runtime"),
    runtimePythonDir: path.join(shareDir, "runtime", "python"),
    runtimeDaemonDir: path.join(shareDir, "runtime", "daemon"),
    runtimePlatformMacosDir: path.join(shareDir, "runtime", "platform", "macos"),
    runtimePlaywrightDir: path.join(shareDir, "runtime", "integrations", "playwright"),
    claudeStateDir: path.join(stateDir, "claude"),
    codexStateDir: path.join(stateDir, "codex"),
    envFile: path.join(configDir, "asot.env"),
    configFile: path.join(configDir, "config.json"),
    installFile: path.join(configDir, "install.json")
  };
}

