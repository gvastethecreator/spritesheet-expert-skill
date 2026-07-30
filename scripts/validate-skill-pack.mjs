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
  await checkProductionMediaContracts();
  await checkSourceProvenanceSchemas();
  await checkCrossSkillEvidence();
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

async function checkProductionMediaContracts() {
  const contracts = {
    "spritesheet-expert": [
      "Mandatory Imagegen Rule And Grok Exception",
      "Optional Grok Imagine Provider",
      "Failure Prevention Contract",
      "gray, black, or white",
      "green, blue, cyan, or magenta",
      "model-backed",
      "representative production art",
      "contact sheet proves inventory and order",
    ],
    "build-static-game-assets": [
      "$imagegen",
      "$grok-imagine",
      "gray, black, or white",
      "green, blue, cyan, or magenta",
      "BiRefNet/BEN2",
      "source.provenance",
      "representative",
      "checker/black/gray/white",
      "must not draw replacement production art",
    ],
    "build-game-backgrounds": [
      "$imagegen",
      "$grok-imagine",
      "Full-bleed scene layers",
      "green, blue, cyan, or magenta",
      "provenance for every layer",
      "representative",
      "composite proves layer order",
      "must not paint replacement production scenery",
    ],
    "build-game-ui-kits": [
      "$imagegen",
      "$grok-imagine",
      "flat gray, black, or white",
      "green, blue, cyan, or magenta",
      "BiRefNet/BEN2",
      "provenance on every state/density variant",
      "representative",
      "state board proves state/density comparison",
      "must not draw replacement production UI",
    ],
    "compose-asset-mockups": [
      "marked non-representative",
      "placeholder",
      "must not invent missing character, prop, background, or UI art",
      "Runtime-captured claims require hash-backed capture evidence",
    ],
    "produce-2d-assets": [
      "$imagegen",
      "$grok-imagine",
      "evidence.production_media",
      "provenance_verified: true",
      "neutral gray/black/white",
      "single contact sheet cannot certify all families",
      "may not replace the failed semantic art",
    ],
  };
  for (const [skill, markers] of Object.entries(contracts)) {
    const content = await readText(path.join(root, "SKILLS", skill, "SKILL.md"));
    for (const marker of markers) {
      if (!content.includes(marker)) errors.push(`${skill}: missing production-media contract marker: ${marker}`);
    }
  }
}

async function checkSourceProvenanceSchemas() {
  const schemas = [
    ["build-static-game-assets", "references/schemas/static-asset-pack-v1.schema.json", ["$defs", "asset", "properties", "source", "required"]],
    ["build-game-backgrounds", "references/schemas/background-pack-v1.schema.json", ["$defs", "layer", "required"]],
    ["build-game-ui-kits", "references/schemas/ui-kit-v1.schema.json", ["$defs", "variant", "required"]],
  ];
  for (const [skill, relativePath, requiredPath] of schemas) {
    const file = path.join(root, "SKILLS", skill, relativePath);
    let schema;
    try {
      schema = JSON.parse(await readText(file));
    } catch (error) {
      errors.push(`${skill}: cannot parse source provenance schema: ${error.message}`);
      continue;
    }
    const sourceContract = schema?.$defs?.sourceProvenance;
    const types = sourceContract?.properties?.source_type?.enum;
    const engines = sourceContract?.properties?.art_engine?.enum;
    if (JSON.stringify(types) !== JSON.stringify(["imagegen", "grok-imagine-image", "imported", "fixture"])) {
      errors.push(`${skill}: source_type contract drifted`);
    }
    if (JSON.stringify(engines) !== JSON.stringify(["imagegen", "grok-imagine", "imported", "fixture"])) {
      errors.push(`${skill}: art_engine contract drifted`);
    }
    let required = schema;
    for (const segment of requiredPath) required = required?.[segment];
    if (!Array.isArray(required) || !required.includes("provenance")) {
      errors.push(`${skill}: every produced source must require provenance`);
    }
    const validationModule = skill === "build-static-game-assets"
      ? "scripts/static_assets/validation.py"
      : skill === "build-game-backgrounds"
        ? "scripts/background_pack/validation.py"
        : "scripts/ui_kit/validation.py";
    const implementation = await readText(path.join(root, "SKILLS", skill, validationModule));
    for (const marker of ['"representative"', '"production_media"', '"source_types"', "provider record sha256 mismatch"]) {
      if (!implementation.includes(marker)) errors.push(`${skill}: validator missing ${marker}`);
    }
  }
}

async function checkCrossSkillEvidence() {
  const files = {
    "spritesheet-expert": ["SKILLS/spritesheet-expert/scripts/spritecore/orchestrator.py", '"production_media"'],
    "produce-2d-assets": ["SKILLS/produce-2d-assets/scripts/assetpack/aggregate.py", "_PRODUCTION_SOURCE_TYPES"],
    "compose-asset-mockups": ["SKILLS/compose-asset-mockups/scripts/presentation_pipeline/preparation.py", "_verified_production_media"],
  };
  for (const [skill, [relativePath, marker]] of Object.entries(files)) {
    const content = await readText(path.join(root, relativePath));
    if (!content.includes(marker)) errors.push(`${skill}: executable production-media evidence gate is missing`);
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
