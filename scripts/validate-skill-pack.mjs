import fs from "node:fs/promises";
import path from "node:path";

const root = process.cwd();

const requiredFiles = [
  ".gitignore",
  "README.md",
  "LICENSE",
  "SKILLS/README.md",
  "SKILLS/spritesheet-expert/LICENSE.sprite-gen",
  "SKILLS/spritesheet-expert/NOTICE.sprite-gen",
  "SKILLS/spritesheet-expert/SKILL.md",
  "SKILLS/spritesheet-expert/agents/openai.yaml",
  "SKILLS/spritesheet-expert/references/atlas-reference.md",
  "SKILLS/spritesheet-expert/references/isometric-tilesets.md",
  "SKILLS/spritesheet-expert/references/pixel-animation-workflows.md",
  "SKILLS/spritesheet-expert/references/pixel-art-direction.md",
  "SKILLS/spritesheet-expert/references/presets.json",
  "SKILLS/spritesheet-expert/references/professional-sprite-animation.md",
  "SKILLS/spritesheet-expert/references/qa-and-outputs.md",
  "SKILLS/spritesheet-expert/references/workflows.md",
  "SKILLS/spritesheet-expert/scripts/smoke_pipeline.py",
  "assets/readme-banner.png"
];

const publicDocs = [
  "README.md",
  "SKILLS/README.md"
];

const errors = [];

async function main() {
  await checkRequiredFiles();
  await checkNoLinkedSkillFolders();
  await checkSkillFrontmatter();
  await checkPresetsJson();
  await checkPublicDocs();
  await checkLocalPathLeaks();

  if (errors.length) {
    for (const error of errors) console.error(`- ${error}`);
    process.exitCode = 1;
    return;
  }

  console.log("spritesheet-expert-skill validation ok");
}

async function checkRequiredFiles() {
  for (const file of requiredFiles) {
    const absolute = path.join(root, file);
    const stat = await fs.stat(absolute).catch(() => null);
    if (!stat?.isFile()) errors.push(`missing required file: ${file}`);
  }
}

async function checkNoLinkedSkillFolders() {
  const skillRoot = path.join(root, "SKILLS", "spritesheet-expert");
  const entries = [skillRoot, ...(await walk(skillRoot))];
  for (const file of entries) {
    const stat = await fs.lstat(file).catch(() => null);
    if (stat?.isSymbolicLink()) {
      errors.push(`linked path is not public-repo safe: ${relative(file)}`);
    }
  }
}

async function checkSkillFrontmatter() {
  const file = path.join(root, "SKILLS", "spritesheet-expert", "SKILL.md");
  const content = await readText(file);
  const match = content.match(/^---\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)/);
  if (!match) {
    errors.push("SKILL.md missing YAML frontmatter");
    return;
  }

  const frontmatter = match[1];
  if (!/^name:\s*spritesheet-expert\s*$/m.test(frontmatter)) {
    errors.push("SKILL.md frontmatter missing name: spritesheet-expert");
  }
  if (!/^description:\s*".+"/m.test(frontmatter)) {
    errors.push("SKILL.md frontmatter needs a quoted description");
  }
  if (!content.includes("Mandatory Imagegen Rule")) {
    errors.push("SKILL.md missing imagegen provenance contract");
  }
  if (!content.includes("check_generation_provenance.py")) {
    errors.push("SKILL.md missing generation provenance gate");
  }
}

async function checkPresetsJson() {
  const file = path.join(root, "SKILLS", "spritesheet-expert", "references", "presets.json");
  const raw = await readText(file);
  try {
    JSON.parse(raw);
  } catch (error) {
    errors.push(`presets.json invalid JSON: ${error.message}`);
  }
}

async function checkPublicDocs() {
  for (const file of publicDocs) {
    const content = await readText(path.join(root, file));
    if (/sprite-atlas-builder/i.test(content)) {
      errors.push(`${file} still advertises old sprite-atlas-builder name`);
    }
    if (/SKILLS\/sprite-atlas-builder/i.test(content)) {
      errors.push(`${file} still points at old skill folder`);
    }
  }
}

async function checkLocalPathLeaks() {
  const textFiles = (await walk(root)).filter((file) => /\.(md|json|ya?ml|mjs|js|css|html|txt|py|gitignore)$/i.test(file));
  const localMarkers = [
    "[A-Z]:\\\\",
    "/" + "Users" + "/",
    "/" + "home" + "/",
    "agents-" + "matrix\\b"
  ];
  const localPathPattern = new RegExp(`\\b(?:${localMarkers.join("|")})`, "i");
  for (const file of textFiles) {
    if (file.includes(`${path.sep}.git${path.sep}`)) continue;
    if (relative(file).startsWith("tests/")) continue;
    const content = await readText(file);
    if (localPathPattern.test(content)) {
      errors.push(`possible local path leak: ${relative(file)}`);
    }
  }
}

async function walk(dir, output = []) {
  const entries = await fs.readdir(dir, { withFileTypes: true }).catch(() => []);
  for (const entry of entries) {
    if ([".git", ".local", ".scratch", ".vscode", "node_modules", "dist", "coverage"].includes(entry.name)) {
      continue;
    }
    const absolute = path.join(dir, entry.name);
    output.push(absolute);
    if (entry.isDirectory()) await walk(absolute, output);
  }
  return output;
}

async function readText(file) {
  return fs.readFile(file, "utf8").catch(() => "");
}

function relative(file) {
  return path.relative(root, file).replace(/\\/g, "/");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
