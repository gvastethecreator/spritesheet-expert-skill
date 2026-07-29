import fs from "node:fs/promises";
import path from "node:path";

const root = process.cwd();
const evalPath = path.resolve(root, process.argv[2] ?? "evals/skill-routing.json");
const expectedCandidates = [
  "produce-2d-assets",
  "spritesheet-expert",
  "build-static-game-assets",
  "build-game-backgrounds",
  "build-game-ui-kits",
  "compose-asset-mockups",
];
const singleFamilySkills = new Set([
  "spritesheet-expert",
  "build-static-game-assets",
  "build-game-backgrounds",
  "build-game-ui-kits",
]);
const validScopes = new Set([
  "production-single-family",
  "production-multi-family",
  "presentation-only",
  "outside-suite",
]);

const errors = [];
let suite;
try {
  suite = JSON.parse(await fs.readFile(evalPath, "utf8"));
} catch (error) {
  fail(`cannot parse routing evals: ${error.message}`);
}

if (suite) validateSuite(suite);

if (errors.length) {
  for (const error of errors) console.error(`- ${error}`);
  process.exitCode = 1;
} else {
  console.log(`routing eval validation ok: ${suite.cases.length} cases, ${expectedCandidates.length} candidates`);
}

function validateSuite(value) {
  if (value.version !== 1) fail("routing eval version must be 1");
  if (JSON.stringify(value.candidates) !== JSON.stringify(expectedCandidates)) {
    fail(`routing candidates must be exactly: ${expectedCandidates.join(", ")}`);
  }
  if (!Array.isArray(value.cases)) {
    fail("routing evals must contain a cases array");
    return;
  }

  const ids = new Set();
  const selectedCounts = new Map(expectedCandidates.map((skill) => [skill, 0]));
  const scopeCounts = new Map([...validScopes].map((scope) => [scope, 0]));

  for (const testCase of value.cases) {
    const label = typeof testCase?.id === "string" ? testCase.id : "<missing-id>";
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(label)) fail(`${label}: id must be unique kebab-case`);
    if (ids.has(label)) fail(`${label}: duplicate id`);
    ids.add(label);

    if (typeof testCase.prompt !== "string" || testCase.prompt.trim().length < 40) {
      fail(`${label}: prompt must be a realistic request of at least 40 characters`);
    }
    if (typeof testCase.rationale !== "string" || testCase.rationale.trim().length < 30) {
      fail(`${label}: rationale must explain the routing boundary`);
    }
    if (!validScopes.has(testCase.scope)) {
      fail(`${label}: invalid scope ${String(testCase.scope)}`);
      continue;
    }
    scopeCounts.set(testCase.scope, scopeCounts.get(testCase.scope) + 1);

    const selected = testCase.expectedSkill;
    if (selected !== null && !expectedCandidates.includes(selected)) {
      fail(`${label}: expectedSkill must be a published candidate or null`);
    }
    const excluded = Array.isArray(testCase.excludedSkills) ? testCase.excludedSkills : [];
    if (new Set(excluded).size !== excluded.length || excluded.some((skill) => !expectedCandidates.includes(skill))) {
      fail(`${label}: excludedSkills must contain unique published candidates`);
    }
    const expectedExcluded = expectedCandidates.filter((skill) => skill !== selected);
    if (JSON.stringify([...excluded].sort()) !== JSON.stringify([...expectedExcluded].sort())) {
      fail(`${label}: excludedSkills must name every non-selected candidate`);
    }
    if (selected) selectedCounts.set(selected, selectedCounts.get(selected) + 1);

    if (testCase.scope === "production-single-family") {
      if (!singleFamilySkills.has(selected)) fail(`${label}: a single-family production case must select a leaf producer`);
      if (testCase.familyCount !== 1 || !Array.isArray(testCase.families) || testCase.families.length !== 1) {
        fail(`${label}: single-family cases require exactly one declared family`);
      }
    }
    if (testCase.scope === "production-multi-family") {
      if (selected !== "produce-2d-assets") fail(`${label}: two or more production families must select produce-2d-assets`);
      if (!Number.isInteger(testCase.familyCount) || testCase.familyCount < 2) {
        fail(`${label}: multi-family cases require familyCount >= 2`);
      }
      if (!Array.isArray(testCase.families) || new Set(testCase.families).size !== testCase.familyCount) {
        fail(`${label}: families must be unique and match familyCount`);
      }
    }
    if (testCase.scope === "presentation-only") {
      if (selected !== "compose-asset-mockups") fail(`${label}: presentation-only cases must select compose-asset-mockups`);
      if (testCase.sourceMode !== "approved-existing-assets") {
        fail(`${label}: presentation-only cases must preserve approved existing sources`);
      }
    }
    if (testCase.scope === "outside-suite" && selected !== null) {
      fail(`${label}: outside-suite cases must select no suite skill`);
    }
  }

  for (const skill of expectedCandidates) {
    if (selectedCounts.get(skill) < 2) fail(`${skill}: require at least two positive routing cases`);
  }
  for (const scope of validScopes) {
    if (scopeCounts.get(scope) < 2) fail(`${scope}: require at least two routing cases`);
  }
}

function fail(message) {
  errors.push(message);
}
