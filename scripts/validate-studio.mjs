import fs from "node:fs/promises";
import path from "node:path";

const root = process.cwd();
const errors = [];

const requiredFiles = [
  "studio/index.html",
  "studio/styles.css",
  "studio/app.js",
  "studio/workflows.json",
  "studio/README.md",
  "docs/architecture/agent-first-studio.md",
  "SKILLS/spritesheet-expert/references/agent-first-studio.md",
  "SKILLS/spritesheet-expert/references/deterministic-item-atlas.md",
  "SKILLS/spritesheet-expert/references/taxonomies/generic-props-v1.json",
  "SKILLS/spritesheet-expert/references/schemas/deterministic-item-sheet-v1.schema.json",
  "SKILLS/spritesheet-expert/references/schemas/item-classification-v1.schema.json",
  "SKILLS/spritesheet-expert/references/schemas/item-review-v1.schema.json",
  "SKILLS/spritesheet-expert/references/schemas/studio-workflow-v1.schema.json",
  "SKILLS/spritesheet-expert/references/schemas/studio-session-v1.schema.json",
  "SKILLS/spritesheet-expert/scripts/build_deterministic_item_atlas.py",
  "SKILLS/spritesheet-expert/scripts/prepare_item_classification.py",
  "SKILLS/spritesheet-expert/scripts/apply_item_classification.py",
  "SKILLS/spritesheet-expert/scripts/apply_item_review.py",
  "SKILLS/spritesheet-expert/scripts/spritecore/item_sheet.py",
];

for (const relative of requiredFiles) {
  const stat = await fs.stat(path.join(root, relative)).catch(() => null);
  if (!stat?.isFile()) errors.push(`missing Studio file: ${relative}`);
}

const registryPath = path.join(root, "studio/workflows.json");
let registry;
try {
  registry = JSON.parse(await fs.readFile(registryPath, "utf8"));
} catch (error) {
  errors.push(`studio/workflows.json is invalid: ${error.message}`);
}

if (registry) {
  if (registry.schemaVersion !== "studio-workflow-registry-v1") {
    errors.push("workflow registry must use studio-workflow-registry-v1");
  }
  if (!Array.isArray(registry.workflows) || registry.workflows.length < 6) {
    errors.push("workflow registry must expose the initial production workflows");
  } else {
    const ids = new Set();
    for (const workflow of registry.workflows) {
      if (!workflow || typeof workflow !== "object") {
        errors.push("every workflow must be an object");
        continue;
      }
      if (typeof workflow.id !== "string" || !workflow.id) {
        errors.push("every workflow needs an id");
      } else if (ids.has(workflow.id)) {
        errors.push(`duplicate workflow id: ${workflow.id}`);
      } else {
        ids.add(workflow.id);
      }
      for (const field of ["title", "description", "ownerSkill", "mode", "promptTemplate", "commandTemplate"]) {
        if (typeof workflow[field] !== "string" || workflow[field].trim() === "") {
          errors.push(`${workflow.id ?? "<unknown>"}: missing ${field}`);
        }
      }
      if (!Array.isArray(workflow.fields)) {
        errors.push(`${workflow.id ?? "<unknown>"}: fields must be an array`);
      }
      const placeholders = new Set(
        [...String(workflow.promptTemplate ?? "").matchAll(/\{\{([a-zA-Z0-9_-]+)\}\}/g)]
          .map((match) => match[1]),
      );
      const fieldIds = new Set((workflow.fields ?? []).map((field) => field.id));
      for (const placeholder of placeholders) {
        if (!fieldIds.has(placeholder)) {
          errors.push(`${workflow.id}: prompt placeholder has no field: ${placeholder}`);
        }
      }
    }

    const regeneration = registry.workflows.find((workflow) => workflow.id === "regenerate-single-item");
    if (!regeneration) {
      errors.push("regenerate-single-item workflow is required");
    } else {
      const prompt = regeneration.promptTemplate.toLowerCase();
      for (const marker of [
        "exactly one image",
        "do not include another object category",
        "collage",
        "contact sheet",
        "concept sheet",
        "do not reuse a failed multi-object image",
      ]) {
        if (!prompt.includes(marker)) {
          errors.push(`regenerate-single-item is missing isolation marker: ${marker}`);
        }
      }
      if (regeneration.batchPolicy?.requestedCount !== 1) {
        errors.push("regenerate-single-item must request exactly one result");
      }
      if (regeneration.requiresExplicitExecution !== true) {
        errors.push("provider handoff must require explicit execution");
      }
    }
  }
}

const html = await fs.readFile(path.join(root, "studio/index.html"), "utf8").catch(() => "");
const css = await fs.readFile(path.join(root, "studio/styles.css"), "utf8").catch(() => "");
const app = await fs.readFile(path.join(root, "studio/app.js"), "utf8").catch(() => "");

for (const [name, content] of [["index.html", html], ["styles.css", css], ["app.js", app]]) {
  if (/https?:\/\//i.test(content)) {
    errors.push(`studio/${name} must not require remote runtime resources`);
  }
}

for (const marker of [
  "Workflow Launcher",
  "Atlas Lab",
  "Agent Queue",
  "Contracts",
  "manifest-input",
  "run-folder-input",
  "export-review",
]) {
  if (!html.includes(marker)) errors.push(`studio/index.html missing marker: ${marker}`);
}

for (const marker of [
  "loadWorkflowRegistry",
  "reviewDocument",
  "regenerate-single-item",
  "studio-handoff-v1",
  "item-review-v1",
  "sha256Hex",
]) {
  if (!app.includes(marker)) errors.push(`studio/app.js missing marker: ${marker}`);
}

if (errors.length) {
  for (const error of errors) console.error(`- ${error}`);
  process.exitCode = 1;
} else {
  console.log("spritesheet-expert Studio validation ok");
}
