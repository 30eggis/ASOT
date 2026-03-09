import fs from "node:fs/promises";
import path from "node:path";

export async function ensureDir(dirPath) {
  await fs.mkdir(dirPath, { recursive: true });
}

export async function pathExists(targetPath) {
  try {
    await fs.access(targetPath);
    return true;
  } catch {
    return false;
  }
}

export async function writeFileEnsured(targetPath, content, mode) {
  await ensureDir(path.dirname(targetPath));
  await fs.writeFile(targetPath, content, "utf8");
  if (mode) {
    await fs.chmod(targetPath, mode);
  }
}

export async function copyFileEnsured(sourcePath, targetPath, mode) {
  await ensureDir(path.dirname(targetPath));
  await fs.copyFile(sourcePath, targetPath);
  if (mode) {
    await fs.chmod(targetPath, mode);
  }
}

export async function backupIfNeeded(targetPath) {
  if (!(await pathExists(targetPath))) {
    return null;
  }
  const backupPath = `${targetPath}.asot.bak`;
  if (await pathExists(backupPath)) {
    return backupPath;
  }
  await ensureDir(path.dirname(backupPath));
  await fs.copyFile(targetPath, backupPath);
  return backupPath;
}

export async function patchManagedBlock(targetPath, startMarker, endMarker, block) {
  const content = (await pathExists(targetPath))
    ? await fs.readFile(targetPath, "utf8")
    : "";

  const managed = `${startMarker}\n${block.trimEnd()}\n${endMarker}\n`;
  const escapedStart = startMarker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const escapedEnd = endMarker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pattern = new RegExp(`${escapedStart}[\\s\\S]*?${escapedEnd}\\n?`, "m");

  const next = pattern.test(content)
    ? content.replace(pattern, managed)
    : content.trim()
      ? `${content.replace(/\s*$/, "\n\n")}${managed}`
      : managed;

  await writeFileEnsured(targetPath, next);
}

export async function removeManagedBlock(targetPath, startMarker, endMarker) {
  if (!(await pathExists(targetPath))) {
    return false;
  }

  const content = await fs.readFile(targetPath, "utf8");
  const escapedStart = startMarker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const escapedEnd = endMarker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pattern = new RegExp(`${escapedStart}[\\s\\S]*?${escapedEnd}\\n?`, "m");

  if (!pattern.test(content)) {
    return false;
  }

  const next = content.replace(pattern, "").replace(/\n{3,}/g, "\n\n").replace(/^\s+$/gm, "");
  await writeFileEnsured(targetPath, next.trim() ? `${next.trimEnd()}\n` : "");
  return true;
}
