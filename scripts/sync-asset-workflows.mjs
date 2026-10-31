import { createHash } from "node:crypto";
import { isUtf8 } from "node:buffer";
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const target = path.join(root, "SKILLS", "produce-2d-assets", "workflows");
const families = ["spritesheet-expert", "build-static-game-assets", "build-game-backgrounds", "build-game-ui-kits", "compose-asset-mockups"];
const mode = process.argv.slice(2);
if (mode.length !== 1 || !["--check", "--write"].includes(mode[0])) {
  throw new Error("Usage: node scripts/sync-asset-workflows.mjs --check|--write");
}

const tracked = execFileSync("git", ["ls-files", "-z", "--", ...families.map((name) => `SKILLS/${name}/`)], { cwd: root, encoding: "utf8" }).split("\0").filter(Boolean).sort();
const expected = new Set(["manifest.json"]);
const files = [];
const errors = [];
for (const source of tracked) {
  const relative = source.slice("SKILLS/".length);
  if (relative.split("/").includes("agents")) continue;
  const destination = relative.endsWith("/SKILL.md") ? relative.replace(/SKILL\.md$/, "WORKFLOW.md") : relative;
  const sourcePath = path.join(root, source);
  if (!(await fs.lstat(sourcePath)).isFile()) throw new Error(`Workflow source must be a regular file: ${source}`);
  const sourceBytes = await fs.readFile(sourcePath);
  const bytes = isUtf8(sourceBytes) && !sourceBytes.includes(0)
    ? Buffer.from(sourceBytes.toString("utf8").replace(/\r\n/g, "\n"))
    : sourceBytes;
  expected.add(destination);
  files.push({ source, path: destination, sha256: createHash("sha256").update(bytes).digest("hex") });
  const destinationPath = path.join(target, destination);
  if (mode[0] === "--write") {
    await fs.mkdir(path.dirname(destinationPath), { recursive: true });
    await fs.writeFile(destinationPath, bytes);
  } else {
    const installed = await fs.readFile(destinationPath).catch(() => null);
    if (!installed?.equals(bytes)) errors.push(`Missing or stale bundled workflow: ${destination}`);
  }
}
const manifest = Buffer.from(`${JSON.stringify({ schema_version: 1, families, files }, null, 2)}\n`);
if (mode[0] === "--write") {
  await fs.writeFile(path.join(target, "manifest.json"), manifest);
} else {
  const installed = await fs.readFile(path.join(target, "manifest.json")).catch(() => null);
  if (!installed?.equals(manifest)) errors.push("Bundled workflow manifest is missing or stale");
}
for (const entry of await fs.readdir(target, { recursive: true, withFileTypes: true })) {
  if (!entry.isFile() && !entry.isSymbolicLink()) continue;
  const relative = path.relative(target, path.join(entry.parentPath, entry.name)).split(path.sep).join("/");
  if (relative.split("/").includes("__pycache__") || relative.endsWith(".pyc")) continue;
  if (!expected.has(relative) || entry.isSymbolicLink()) errors.push(`Unexpected bundled workflow path: ${relative}`);
}
if (errors.length) throw new Error(errors.join("\n"));
console.log(`Bundled asset workflows ${mode[0] === "--write" ? "written" : "verified"}: ${families.length} families, ${files.length} files.`);
