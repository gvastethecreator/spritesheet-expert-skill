import fs from "node:fs/promises";
import path from "node:path";

const root = process.cwd();

const publishedSkills = [
  "produce-2d-assets",
  "spritesheet-expert",
  "build-static-game-assets",
  "build-game-backgrounds",
  "build-game-ui-kits",
  "compose-asset-mockups",
];

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
  "SKILLS/spritesheet-expert/references/grok-video-animation.md",
  "SKILLS/spritesheet-expert/references/pixel-animation-workflows.md",
  "SKILLS/spritesheet-expert/references/pixel-art-direction.md",
  "SKILLS/spritesheet-expert/references/presets.json",
  "SKILLS/spritesheet-expert/references/professional-sprite-animation.md",
  "SKILLS/spritesheet-expert/references/qa-and-outputs.md",
  "SKILLS/spritesheet-expert/references/workflows.md",
  "SKILLS/spritesheet-expert/scripts/smoke_pipeline.py",
  "SKILLS/spritesheet-expert/scripts/check_python_env.py",
  "SKILLS/spritesheet-expert/scripts/requirements-core.txt",
  "SKILLS/spritesheet-expert/scripts/requirements-video.txt",
  "SKILLS/spritesheet-expert/scripts/build_preview_workbench.py",
  "SKILLS/spritesheet-expert/scripts/ingest_source.py",
  "SKILLS/spritesheet-expert/scripts/prepare_grok_video_animation.py",
  "SKILLS/spritesheet-expert/scripts/ingest_grok_video_animation.py",
  "SKILLS/spritesheet-expert/references/schemas/source-intake-v1.schema.json",
  "SKILLS/spritesheet-expert/references/schemas/source-provenance-v2.schema.json",
  "SKILLS/spritesheet-expert/references/schemas/grok-video-animation-job-v1.schema.json",
  "SKILLS/compose-asset-mockups/scripts/prepare_presentation.py",
  "SKILLS/build-game-backgrounds/requirements-runtime.txt",
  "SKILLS/build-game-ui-kits/requirements-runtime.txt",
  "SKILLS/build-static-game-assets/requirements-runtime.txt",
  "SKILLS/compose-asset-mockups/requirements-runtime.txt",
  "SKILLS/produce-2d-assets/requirements-runtime.txt",
  "evals/skill-routing.json",
  "scripts/check_python_env.py",
  "scripts/validate-routing-evals.mjs",
  ...publishedSkills.flatMap((skill) => [
    `SKILLS/${skill}/SKILL.md`,
    `SKILLS/${skill}/agents/openai.yaml`,
  ]),
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
  await checkAgentMetadata();
  await checkCatalog();
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
  const skillRoot = path.join(root, "SKILLS");
  const entries = [skillRoot, ...(await walk(skillRoot))];
  for (const file of entries) {
    const stat = await fs.lstat(file).catch(() => null);
    if (stat?.isSymbolicLink()) {
      errors.push(`linked path is not public-repo safe: ${relative(file)}`);
    }
  }
}

async function checkSkillFrontmatter() {
  for (const skill of publishedSkills) {
    const file = path.join(root, "SKILLS", skill, "SKILL.md");
    const content = await readText(file);
    const match = content.match(/^---\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)/);
    if (!match) {
      errors.push(`${skill}: SKILL.md missing YAML frontmatter`);
      continue;
    }
    const frontmatter = match[1];
    if (!new RegExp(`^name:\\s*${skill}\\s*$`, "m").test(frontmatter)) {
      errors.push(`${skill}: frontmatter name must match its folder`);
    }
    if (!/^description:\s*".+"\s*$/m.test(frontmatter)) {
      errors.push(`${skill}: frontmatter needs one quoted description`);
    }
    if (/\bTODO\b/i.test(content)) {
      errors.push(`${skill}: published SKILL.md contains TODO text`);
    }
  }

  const main = await readText(path.join(root, "SKILLS", "spritesheet-expert", "SKILL.md"));
  if (!main.includes("Mandatory Imagegen Rule")) {
    errors.push("spritesheet-expert: missing imagegen provenance contract");
  }
  if (!main.includes("check_generation_provenance.py")) {
    errors.push("spritesheet-expert: missing generation provenance gate");
  }
}

async function checkAgentMetadata() {
  for (const skill of publishedSkills) {
    const file = path.join(root, "SKILLS", skill, "agents", "openai.yaml");
    const content = await readText(file);
    const short = content.match(/^\s*short_description:\s*"([^"]+)"\s*$/m)?.[1] ?? "";
    const prompt = content.match(/^\s*default_prompt:\s*"([^"]+)"\s*$/m)?.[1] ?? "";
    if (short.length < 25 || short.length > 64) {
      errors.push(`${skill}: short_description must be 25-64 characters`);
    }
    if (!prompt.includes(`$${skill}`)) {
      errors.push(`${skill}: default_prompt must mention $${skill}`);
    }
  }
}

async function checkCatalog() {
  const file = path.join(root, "skills.sh.json");
  let catalog;
  try {
    catalog = JSON.parse(await readText(file));
  } catch (error) {
    errors.push(`skills.sh.json invalid JSON: ${error.message}`);
    return;
  }
  const listed = catalog.groupings?.flatMap((group) => group.skills ?? []) ?? [];
  if (JSON.stringify(listed) !== JSON.stringify(publishedSkills)) {
    errors.push(`skills.sh.json must publish exactly: ${publishedSkills.join(", ")}`);
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
