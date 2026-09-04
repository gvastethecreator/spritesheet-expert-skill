const state = {
  registry: null,
  workflow: null,
  outputMode: "prompt",
  formValues: {},
  manifest: null,
  manifestFile: null,
  manifestSha256: null,
  runFiles: new Map(),
  objectUrls: new Map(),
  reviews: new Map(),
  selectedItemId: null,
  replacementDrafts: new Map(),
  queue: loadQueue(),
};

const elements = {
  navItems: [...document.querySelectorAll("[data-view]")],
  viewPanels: [...document.querySelectorAll("[data-view-panel]")],
  workflowSelect: document.querySelector("#workflow-select"),
  workflowDescription: document.querySelector("#workflow-description"),
  workflowMode: document.querySelector("#workflow-mode"),
  workflowOwner: document.querySelector("#workflow-owner"),
  workflowVersion: document.querySelector("#workflow-version"),
  workflowProvider: document.querySelector("#workflow-provider"),
  workflowForm: document.querySelector("#workflow-form"),
  workflowOutput: document.querySelector("#workflow-output"),
  outputFeedback: document.querySelector("#output-feedback"),
  outputModeButtons: [...document.querySelectorAll("[data-output-mode]")],
  resetWorkflow: document.querySelector("#reset-workflow"),
  copyOutput: document.querySelector("#copy-output"),
  downloadOutput: document.querySelector("#download-output"),
  queueOutput: document.querySelector("#queue-output"),
  manifestInput: document.querySelector("#manifest-input"),
  runFolderInput: document.querySelector("#run-folder-input"),
  manifestFileName: document.querySelector("#manifest-file-name"),
  runFolderName: document.querySelector("#run-folder-name"),
  runSummary: document.querySelector("#run-summary"),
  clearAtlas: document.querySelector("#clear-atlas"),
  itemSearch: document.querySelector("#item-search"),
  statusFilter: document.querySelector("#status-filter"),
  itemSort: document.querySelector("#item-sort"),
  visibleCount: document.querySelector("#visible-count"),
  itemGrid: document.querySelector("#item-grid"),
  itemCardTemplate: document.querySelector("#item-card-template"),
  emptyInspector: document.querySelector("#empty-inspector"),
  itemInspector: document.querySelector("#item-inspector"),
  selectedItemStatus: document.querySelector("#selected-item-status"),
  itemPreview: document.querySelector("#item-preview"),
  itemPreviewImage: document.querySelector("#item-preview-image"),
  previewBackgroundButtons: [...document.querySelectorAll("[data-preview-background]")],
  inspectorItemId: document.querySelector("#inspector-item-id"),
  copyItemId: document.querySelector("#copy-item-id"),
  geometryData: document.querySelector("#geometry-data"),
  qaFlags: document.querySelector("#qa-flags"),
  itemStatusButtons: [...document.querySelectorAll("[data-item-status]")],
  classificationFamily: document.querySelector("#classification-family"),
  classificationType: document.querySelector("#classification-type"),
  classificationTags: document.querySelector("#classification-tags"),
  reviewNotes: document.querySelector("#review-notes"),
  replacementInput: document.querySelector("#replacement-input"),
  replacementPreview: document.querySelector("#replacement-preview"),
  replacementPreviewImage: document.querySelector("#replacement-preview-image"),
  replacementFileName: document.querySelector("#replacement-file-name"),
  removeReplacement: document.querySelector("#remove-replacement"),
  saveItem: document.querySelector("#save-item"),
  queueRegeneration: document.querySelector("#queue-regeneration"),
  exportReview: document.querySelector("#export-review"),
  copyReview: document.querySelector("#copy-review"),
  reviewProgress: document.querySelector("#review-progress"),
  queueList: document.querySelector("#queue-list"),
  queueEmpty: document.querySelector("#queue-empty"),
  queueCount: document.querySelector("#queue-count"),
  queueItemTemplate: document.querySelector("#queue-item-template"),
  downloadQueue: document.querySelector("#download-queue"),
  copyQueue: document.querySelector("#copy-queue"),
  clearQueue: document.querySelector("#clear-queue"),
};

function loadQueue() {
  try {
    const raw = localStorage.getItem("spritesheet-expert-studio-queue-v1");
    const value = raw ? JSON.parse(raw) : [];
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

function persistQueue() {
  localStorage.setItem(
    "spritesheet-expert-studio-queue-v1",
    JSON.stringify(state.queue),
  );
}

function setView(view) {
  for (const item of elements.navItems) {
    item.classList.toggle("is-active", item.dataset.view === view);
  }
  for (const panel of elements.viewPanels) {
    panel.classList.toggle("is-active", panel.dataset.viewPanel === view);
  }
  const target = document.querySelector(`#${CSS.escape(view)}`);
  if (target) history.replaceState(null, "", `#${view}`);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

for (const item of elements.navItems) {
  item.addEventListener("click", () => setView(item.dataset.view));
}

function escapeTemplateValue(value) {
  if (value === undefined || value === null) return "";
  return String(value);
}

function interpolate(template, values) {
  return String(template ?? "").replace(/\{\{([a-zA-Z0-9_-]+)\}\}/g, (_, key) =>
    escapeTemplateValue(values[key]),
  );
}

function currentWorkflowValues() {
  const values = {};
  if (!state.workflow) return values;
  for (const field of state.workflow.fields ?? []) {
    const control = elements.workflowForm.elements.namedItem(field.id);
    if (!control) continue;
    if (field.type === "number") {
      const parsed = Number(control.value);
      values[field.id] = Number.isFinite(parsed) ? parsed : control.value;
    } else if (field.type === "checkbox") {
      values[field.id] = control.checked;
    } else {
      values[field.id] = control.value;
    }
  }
  return values;
}

function makeJob(workflow, values = currentWorkflowValues()) {
  const prompt = interpolate(workflow.promptTemplate, values);
  const command = interpolate(workflow.commandTemplate, values);
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return {
    schemaVersion: "studio-handoff-v1",
    jobId: `studio-${random}`,
    workflowId: workflow.id,
    workflowVersion: workflow.version,
    ownerSkill: workflow.ownerSkill,
    mode: workflow.mode,
    inputs: values,
    prompt,
    command,
    expectedArtifacts: workflow.expectedArtifacts ?? [],
    providerBoundary: {
      requiresProvider: Boolean(workflow.requiresProvider),
      requiresExplicitExecution: Boolean(workflow.requiresExplicitExecution),
      executedByStudio: false,
    },
    batchPolicy: workflow.batchPolicy ?? null,
    status: "prepared",
    createdAt: new Date().toISOString(),
  };
}

function renderWorkflowOutput() {
  if (!state.workflow) return;
  state.formValues = currentWorkflowValues();
  const job = makeJob(state.workflow, state.formValues);
  if (state.outputMode === "command") {
    elements.workflowOutput.value = job.command;
  } else if (state.outputMode === "json") {
    elements.workflowOutput.value = JSON.stringify(job, null, 2);
  } else {
    elements.workflowOutput.value = job.prompt;
  }
}

function createField(field) {
  const label = document.createElement("label");
  label.className = "field";
  label.htmlFor = `workflow-field-${field.id}`;
  const title = document.createElement("span");
  title.textContent = field.required ? `${field.label} · required` : field.label;
  label.append(title);

  let control;
  if (field.type === "textarea") {
    control = document.createElement("textarea");
    control.rows = 4;
  } else if (field.type === "select") {
    control = document.createElement("select");
    for (const optionValue of field.options ?? []) {
      const option = document.createElement("option");
      option.value = optionValue;
      option.textContent = optionValue;
      control.append(option);
    }
  } else {
    control = document.createElement("input");
    control.type = field.type === "number" ? "number" : field.type === "checkbox" ? "checkbox" : "text";
  }
  control.id = `workflow-field-${field.id}`;
  control.name = field.id;
  control.required = Boolean(field.required);
  if (field.min !== undefined) control.min = String(field.min);
  if (field.max !== undefined) control.max = String(field.max);
  if (field.step !== undefined) control.step = String(field.step);
  if (field.type === "checkbox") {
    control.checked = Boolean(field.default);
  } else {
    control.value = field.default ?? "";
  }
  control.addEventListener("input", renderWorkflowOutput);
  control.addEventListener("change", renderWorkflowOutput);
  label.append(control);
  return label;
}

function selectWorkflow(workflowId) {
  if (!state.registry) return;
  const workflow = state.registry.workflows.find((entry) => entry.id === workflowId);
  if (!workflow) return;
  state.workflow = workflow;
  elements.workflowDescription.textContent = workflow.description;
  elements.workflowMode.textContent = workflow.mode;
  elements.workflowOwner.textContent = workflow.ownerSkill;
  elements.workflowVersion.textContent = `v${workflow.version}`;
  elements.workflowProvider.textContent = workflow.requiresProvider ? "external handoff" : "not required";
  elements.workflowForm.replaceChildren(...(workflow.fields ?? []).map(createField));
  renderWorkflowOutput();
}

async function loadWorkflowRegistry() {
  try {
    const response = await fetch("workflows.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const registry = await response.json();
    if (!registry || !Array.isArray(registry.workflows) || registry.workflows.length === 0) {
      throw new Error("registry contains no workflows");
    }
    state.registry = registry;
    const options = registry.workflows.map((workflow) => {
      const option = document.createElement("option");
      option.value = workflow.id;
      option.textContent = workflow.title;
      return option;
    });
    elements.workflowSelect.replaceChildren(...options);
    selectWorkflow(registry.workflows[0].id);
  } catch (error) {
    elements.workflowDescription.textContent =
      `Could not load workflows.json (${error.message}). Serve the studio directory through a local HTTP server instead of opening file:// directly.`;
    elements.workflowOutput.value = "python -m http.server 4173 --directory studio";
    elements.workflowMode.textContent = "blocked";
  }
}

elements.workflowSelect.addEventListener("change", () =>
  selectWorkflow(elements.workflowSelect.value),
);

elements.resetWorkflow.addEventListener("click", () => {
  if (state.workflow) selectWorkflow(state.workflow.id);
});

for (const button of elements.outputModeButtons) {
  button.addEventListener("click", () => {
    state.outputMode = button.dataset.outputMode;
    for (const candidate of elements.outputModeButtons) {
      candidate.setAttribute(
        "aria-selected",
        String(candidate === button),
      );
    }
    renderWorkflowOutput();
  });
}

async function copyText(text, feedback = elements.outputFeedback) {
  try {
    await navigator.clipboard.writeText(text);
    feedback.textContent = "Copied.";
  } catch {
    const helper = document.createElement("textarea");
    helper.value = text;
    helper.style.position = "fixed";
    helper.style.opacity = "0";
    document.body.append(helper);
    helper.select();
    document.execCommand("copy");
    helper.remove();
    feedback.textContent = "Copied with fallback clipboard support.";
  }
  window.setTimeout(() => {
    feedback.textContent = "";
  }, 2400);
}

function downloadBlob(filename, content, type = "application/json") {
  const blob = content instanceof Blob ? content : new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

elements.copyOutput.addEventListener("click", () =>
  copyText(elements.workflowOutput.value),
);

elements.downloadOutput.addEventListener("click", () => {
  if (!state.workflow) return;
  const extension = state.outputMode === "json" ? "json" : state.outputMode === "command" ? "txt" : "md";
  downloadBlob(
    `${state.workflow.id}.${extension}`,
    elements.workflowOutput.value,
    state.outputMode === "json" ? "application/json" : "text/plain",
  );
  elements.outputFeedback.textContent = "Downloaded.";
});

elements.queueOutput.addEventListener("click", () => {
  if (!state.workflow) return;
  const job = makeJob(state.workflow);
  state.queue.push(job);
  persistQueue();
  renderQueue();
  elements.outputFeedback.textContent = `Added ${job.jobId} to the queue.`;
});

function revokeObjectUrls() {
  for (const url of state.objectUrls.values()) URL.revokeObjectURL(url);
  state.objectUrls.clear();
  for (const draft of state.replacementDrafts.values()) {
    if (draft.objectUrl) URL.revokeObjectURL(draft.objectUrl);
  }
  state.replacementDrafts.clear();
}

async function sha256Hex(input) {
  const bytes = input instanceof ArrayBuffer ? input : await input.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

function normalizeRunPath(value) {
  return String(value ?? "")
    .replaceAll("\\", "/")
    .replace(/^\.\//, "")
    .replace(/^\/+/, "");
}

function indexRunFiles(fileList) {
  state.runFiles.clear();
  const files = [...fileList];
  for (const file of files) {
    const webkit = normalizeRunPath(file.webkitRelativePath || file.name);
    state.runFiles.set(webkit, file);
    state.runFiles.set(normalizeRunPath(file.name), file);
    const slash = webkit.indexOf("/");
    if (slash >= 0) state.runFiles.set(webkit.slice(slash + 1), file);
  }
  const first = files[0];
  const rootName = first?.webkitRelativePath?.split("/")[0] || `${files.length} files`;
  elements.runFolderName.textContent = `${rootName} · ${files.length} files`;
}

function resolveRunFile(relativePath) {
  const normalized = normalizeRunPath(relativePath);
  if (state.runFiles.has(normalized)) return state.runFiles.get(normalized);
  for (const [path, file] of state.runFiles) {
    if (path.endsWith(`/${normalized}`)) return file;
  }
  return null;
}

function itemImageUrl(item) {
  const path = item?.artifacts?.rgba;
  if (!path) return "";
  const existing = state.objectUrls.get(path);
  if (existing) return existing;
  const file = resolveRunFile(path);
  if (!file) return "";
  const url = URL.createObjectURL(file);
  state.objectUrls.set(path, url);
  return url;
}

function initialReview(item) {
  const source = item.review ?? {};
  return {
    itemId: item.id,
    status: _validStatus(source.status) ? source.status : "pending",
    notes: source.notes ?? "",
    classification: {
      family: item.classification?.family ?? "unknown",
      canonicalType: item.classification?.canonicalType ?? "unknown",
      tags: Array.isArray(item.classification?.tags) ? [...item.classification.tags] : [],
    },
    replacement: source.replacement ?? null,
  };
}

function _validStatus(value) {
  return ["pending", "approved", "rejected", "replace", "regenerate"].includes(value);
}

function hydrateReviews() {
  state.reviews.clear();
  for (const item of state.manifest?.items ?? []) {
    if (item && item.id) state.reviews.set(item.id, initialReview(item));
  }
}

async function loadManifestFile(file) {
  try {
    const text = await file.text();
    const manifest = JSON.parse(text);
    if (manifest?.kind !== "deterministic-item-atlas" || !Array.isArray(manifest.items)) {
      throw new Error("not a deterministic-item-atlas manifest");
    }
    state.manifest = manifest;
    state.manifestFile = file;
    state.manifestSha256 = await sha256Hex(file);
    state.selectedItemId = null;
    elements.manifestFileName.textContent = `${file.name} · ${manifest.items.length} items`;
    hydrateReviews();
    renderRunSummary();
    renderItems();
    renderInspector();
    updateReviewProgress();
  } catch (error) {
    elements.manifestFileName.textContent = `Could not load manifest: ${error.message}`;
  }
}

elements.manifestInput.addEventListener("change", async () => {
  const [file] = elements.manifestInput.files;
  if (file) await loadManifestFile(file);
});

elements.runFolderInput.addEventListener("change", () => {
  revokeObjectUrls();
  indexRunFiles(elements.runFolderInput.files);
  renderItems();
  renderInspector();
});

function renderRunSummary() {
  if (!state.manifest) {
    elements.runSummary.innerHTML = "<span>Waiting for a manifest</span>";
    return;
  }
  const data = [
    ["Run", state.manifest.runId ?? "unnamed"],
    ["Items", String(state.manifest.items.length)],
    ["Source", `${state.manifest.source?.width ?? "?"} × ${state.manifest.source?.height ?? "?"}`],
    ["Atlas", `${state.manifest.atlas?.width ?? "?"} × ${state.manifest.atlas?.height ?? "?"}`],
  ];
  elements.runSummary.replaceChildren(
    ...data.map(([label, value]) => {
      const wrapper = document.createElement("div");
      const small = document.createElement("small");
      const strong = document.createElement("strong");
      small.textContent = label;
      strong.textContent = value;
      wrapper.append(small, strong);
      return wrapper;
    }),
  );
}

function itemSearchText(item) {
  const review = state.reviews.get(item.id);
  return [
    item.id,
    item.classification?.family,
    item.classification?.canonicalType,
    ...(item.classification?.tags ?? []),
    review?.classification?.family,
    review?.classification?.canonicalType,
    ...(review?.classification?.tags ?? []),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function itemArea(item) {
  const size = item.geometry?.originalSize;
  return Array.isArray(size) ? Number(size[0] ?? 0) * Number(size[1] ?? 0) : 0;
}

function visibleItems() {
  if (!state.manifest) return [];
  const query = elements.itemSearch.value.trim().toLowerCase();
  const status = elements.statusFilter.value;
  const sort = elements.itemSort.value;
  const items = state.manifest.items.filter((item) => {
    const review = state.reviews.get(item.id);
    if (status !== "all" && review?.status !== status) return false;
    return !query || itemSearchText(item).includes(query);
  });
  if (sort === "area-desc") items.sort((a, b) => itemArea(b) - itemArea(a) || a.id.localeCompare(b.id));
  else if (sort === "area-asc") items.sort((a, b) => itemArea(a) - itemArea(b) || a.id.localeCompare(b.id));
  else if (sort === "type") items.sort((a, b) => {
    const left = state.reviews.get(a.id)?.classification?.canonicalType ?? "unknown";
    const right = state.reviews.get(b.id)?.classification?.canonicalType ?? "unknown";
    return left.localeCompare(right) || a.id.localeCompare(b.id);
  });
  else if (sort === "status") items.sort((a, b) => {
    const left = state.reviews.get(a.id)?.status ?? "pending";
    const right = state.reviews.get(b.id)?.status ?? "pending";
    return left.localeCompare(right) || a.id.localeCompare(b.id);
  });
  else items.sort((a, b) => {
    const left = a.source?.bbox ?? [0, 0];
    const right = b.source?.bbox ?? [0, 0];
    return Number(left[1]) - Number(right[1]) || Number(left[0]) - Number(right[0]) || a.id.localeCompare(b.id);
  });
  return items;
}

function renderItems() {
  const items = visibleItems();
  elements.visibleCount.textContent = `${items.length} visible`;
  const cards = items.map((item) => {
    const fragment = elements.itemCardTemplate.content.cloneNode(true);
    const card = fragment.querySelector(".item-card");
    const image = fragment.querySelector("img");
    const code = fragment.querySelector("code");
    const title = fragment.querySelector("strong");
    const meta = fragment.querySelector("small");
    const status = fragment.querySelector(".item-card-status");
    const review = state.reviews.get(item.id) ?? initialReview(item);
    card.dataset.status = review.status;
    card.classList.toggle("is-selected", item.id === state.selectedItemId);
    image.src = itemImageUrl(item);
    image.alt = `${review.classification.canonicalType || "Unknown item"} ${item.id}`;
    code.textContent = item.id;
    title.textContent = review.classification.canonicalType || "unknown";
    const size = item.geometry?.originalSize ?? ["?", "?"];
    meta.textContent = `${size[0]} × ${size[1]} · ${review.classification.family || "unknown"}`;
    status.textContent = review.status;
    card.addEventListener("click", () => {
      state.selectedItemId = item.id;
      renderItems();
      renderInspector();
    });
    return fragment;
  });
  elements.itemGrid.replaceChildren(...cards);
  if (!state.manifest) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "Load a deterministic item manifest to begin review.";
    elements.itemGrid.append(empty);
  } else if (items.length === 0) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "No items match the current filters.";
    elements.itemGrid.append(empty);
  }
}

for (const input of [elements.itemSearch, elements.statusFilter, elements.itemSort]) {
  input.addEventListener("input", renderItems);
  input.addEventListener("change", renderItems);
}

for (const button of document.querySelectorAll("[data-bulk-status]")) {
  button.addEventListener("click", () => {
    const next = button.dataset.bulkStatus;
    for (const item of visibleItems()) {
      const review = state.reviews.get(item.id);
      if (review) review.status = next;
    }
    renderItems();
    renderInspector();
    updateReviewProgress();
  });
}

function selectedItem() {
  return state.manifest?.items?.find((item) => item.id === state.selectedItemId) ?? null;
}

function geometryEntry(label, value) {
  const wrapper = document.createElement("div");
  const dt = document.createElement("dt");
  const dd = document.createElement("dd");
  dt.textContent = label;
  dd.textContent = Array.isArray(value) ? value.join(", ") : String(value ?? "—");
  wrapper.append(dt, dd);
  return wrapper;
}

function renderReplacement(itemId) {
  const draft = state.replacementDrafts.get(itemId);
  if (!draft) {
    elements.replacementPreview.hidden = true;
    elements.replacementPreviewImage.removeAttribute("src");
    elements.replacementFileName.textContent = "";
    return;
  }
  elements.replacementPreview.hidden = false;
  elements.replacementPreviewImage.src = draft.objectUrl;
  elements.replacementFileName.textContent = `${draft.file.name} · ${Math.ceil(draft.file.size / 1024)} KB`;
}

function renderInspector() {
  const item = selectedItem();
  if (!item) {
    elements.emptyInspector.hidden = false;
    elements.itemInspector.hidden = true;
    elements.selectedItemStatus.textContent = "none";
    return;
  }
  const review = state.reviews.get(item.id) ?? initialReview(item);
  elements.emptyInspector.hidden = true;
  elements.itemInspector.hidden = false;
  elements.selectedItemStatus.textContent = review.status;
  elements.inspectorItemId.textContent = item.id;
  elements.itemPreviewImage.src = itemImageUrl(item);
  elements.geometryData.replaceChildren(
    geometryEntry("Native size", item.geometry?.originalSize),
    geometryEntry("Source bbox", item.source?.bbox),
    geometryEntry("Cell rect", item.geometry?.cellRect),
    geometryEntry("Visible frame", item.geometry?.frame),
    geometryEntry("Scale", item.geometry?.scale),
    geometryEntry("Rotated", item.geometry?.rotated),
  );
  elements.qaFlags.replaceChildren(
    ...(item.qaFlags ?? []).map((flag) => {
      const element = document.createElement("span");
      element.textContent = flag;
      return element;
    }),
  );
  elements.classificationFamily.value = review.classification.family ?? "unknown";
  elements.classificationType.value = review.classification.canonicalType ?? "unknown";
  elements.classificationTags.value = (review.classification.tags ?? []).join(", ");
  elements.reviewNotes.value = review.notes ?? "";
  for (const button of elements.itemStatusButtons) {
    button.classList.toggle("is-selected", button.dataset.itemStatus === review.status);
  }
  renderReplacement(item.id);
}

for (const button of elements.previewBackgroundButtons) {
  button.addEventListener("click", () => {
    elements.itemPreview.dataset.background = button.dataset.previewBackground;
    for (const candidate of elements.previewBackgroundButtons) {
      candidate.setAttribute("aria-pressed", String(candidate === button));
    }
  });
}

for (const button of elements.itemStatusButtons) {
  button.addEventListener("click", () => {
    const review = state.reviews.get(state.selectedItemId);
    if (!review) return;
    review.status = button.dataset.itemStatus;
    elements.selectedItemStatus.textContent = review.status;
    for (const candidate of elements.itemStatusButtons) {
      candidate.classList.toggle("is-selected", candidate === button);
    }
    renderItems();
    updateReviewProgress();
  });
}

elements.copyItemId.addEventListener("click", () => {
  if (state.selectedItemId) copyText(state.selectedItemId, elements.outputFeedback);
});

elements.replacementInput.addEventListener("change", async () => {
  const [file] = elements.replacementInput.files;
  if (!file || !state.selectedItemId) return;
  const previous = state.replacementDrafts.get(state.selectedItemId);
  if (previous?.objectUrl) URL.revokeObjectURL(previous.objectUrl);
  const draft = {
    file,
    objectUrl: URL.createObjectURL(file),
    sha256: await sha256Hex(file),
  };
  state.replacementDrafts.set(state.selectedItemId, draft);
  const review = state.reviews.get(state.selectedItemId);
  if (review) review.status = "replace";
  renderInspector();
  renderItems();
  updateReviewProgress();
});

elements.removeReplacement.addEventListener("click", () => {
  const draft = state.replacementDrafts.get(state.selectedItemId);
  if (draft?.objectUrl) URL.revokeObjectURL(draft.objectUrl);
  state.replacementDrafts.delete(state.selectedItemId);
  elements.replacementInput.value = "";
  renderReplacement(state.selectedItemId);
});

function saveSelectedDecision() {
  const item = selectedItem();
  const review = state.reviews.get(state.selectedItemId);
  if (!item || !review) return;
  review.classification = {
    family: elements.classificationFamily.value.trim() || "unknown",
    canonicalType: elements.classificationType.value.trim() || "unknown",
    tags: elements.classificationTags.value
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean)
      .filter((value, index, values) => values.indexOf(value) === index),
  };
  review.notes = elements.reviewNotes.value.trim();
  const draft = state.replacementDrafts.get(item.id);
  review.replacement = draft
    ? {
        path: draft.file.name,
        sha256: draft.sha256,
        mediaType: draft.file.type || "application/octet-stream",
        sizeBytes: draft.file.size,
        provenance: "imported",
      }
    : null;
  if (review.replacement && review.status === "pending") review.status = "replace";
  renderItems();
  renderInspector();
  updateReviewProgress();
}

elements.saveItem.addEventListener("click", saveSelectedDecision);

function regenerationWorkflow() {
  return state.registry?.workflows?.find((workflow) => workflow.id === "regenerate-single-item") ?? null;
}

elements.queueRegeneration.addEventListener("click", () => {
  const item = selectedItem();
  const review = state.reviews.get(state.selectedItemId);
  const workflow = regenerationWorkflow();
  if (!item || !review || !workflow) return;
  saveSelectedDecision();
  review.status = "regenerate";
  const type = review.classification.canonicalType !== "unknown"
    ? review.classification.canonicalType.replaceAll("_", " ")
    : "one isolated replacement game prop";
  const values = {
    itemId: item.id,
    description: `${type}${review.notes ? `; ${review.notes}` : ""}`,
    style: "match the accepted source-sheet art direction, camera, lighting, outline, material treatment, and apparent native scale",
    background: "transparent",
    output: `handoffs/returned/${item.id}.png`,
  };
  const job = makeJob(workflow, values);
  job.sourceManifest = {
    runId: state.manifest.runId,
    sha256: state.manifestSha256,
  };
  job.targetItem = {
    id: item.id,
    sourceBbox: item.source?.bbox ?? null,
    nativeSize: item.geometry?.originalSize ?? null,
    classification: review.classification,
  };
  state.queue.push(job);
  persistQueue();
  renderItems();
  renderInspector();
  renderQueue();
  updateReviewProgress();
  setView("queue");
});

function reviewDocument() {
  if (!state.manifest) return null;
  const items = state.manifest.items.map((item) => {
    const review = state.reviews.get(item.id) ?? initialReview(item);
    const draft = state.replacementDrafts.get(item.id);
    const replacement = draft
      ? {
          path: draft.file.name,
          sha256: draft.sha256,
          mediaType: draft.file.type || "application/octet-stream",
          sizeBytes: draft.file.size,
          provenance: "imported",
        }
      : review.replacement;
    return {
      itemId: item.id,
      status: review.status,
      notes: review.notes || "",
      classification: review.classification,
      replacement: replacement ?? null,
    };
  });
  return {
    schemaVersion: "item-review-v1",
    kind: "deterministic-item-review",
    reviewId: `review-${state.manifest.runId ?? "run"}-${Date.now()}`,
    runId: state.manifest.runId,
    sourceManifest: {
      filename: state.manifestFile?.name ?? "manifest.json",
      sha256: state.manifestSha256,
    },
    createdAt: new Date().toISOString(),
    items,
    summary: items.reduce(
      (summary, item) => {
        summary[item.status] = (summary[item.status] ?? 0) + 1;
        return summary;
      },
      {},
    ),
  };
}

function updateReviewProgress() {
  const total = state.manifest?.items?.length ?? 0;
  let decided = 0;
  for (const review of state.reviews.values()) {
    if (review.status !== "pending") decided += 1;
  }
  elements.reviewProgress.textContent = `${decided} / ${total} decided`;
}

elements.exportReview.addEventListener("click", () => {
  saveSelectedDecision();
  const review = reviewDocument();
  if (!review) return;
  downloadBlob("item-review.json", `${JSON.stringify(review, null, 2)}\n`);
});

elements.copyReview.addEventListener("click", () => {
  saveSelectedDecision();
  const review = reviewDocument();
  if (review) copyText(JSON.stringify(review, null, 2), elements.outputFeedback);
});

elements.clearAtlas.addEventListener("click", () => {
  revokeObjectUrls();
  state.manifest = null;
  state.manifestFile = null;
  state.manifestSha256 = null;
  state.runFiles.clear();
  state.reviews.clear();
  state.selectedItemId = null;
  elements.manifestInput.value = "";
  elements.runFolderInput.value = "";
  elements.manifestFileName.textContent = "No file selected";
  elements.runFolderName.textContent = "Needed to resolve local images";
  renderRunSummary();
  renderItems();
  renderInspector();
  updateReviewProgress();
});

function queueSummary(job) {
  if (job.workflowId === "regenerate-single-item") {
    return `One isolated replacement for ${job.inputs?.itemId ?? "one item"}. No collage or multi-category output.`;
  }
  return job.prompt?.slice(0, 190) || "Prepared portable handoff.";
}

function renderQueue() {
  const fragments = state.queue.map((job, index) => {
    const fragment = elements.queueItemTemplate.content.cloneNode(true);
    fragment.querySelector(".queue-kind").textContent = job.mode ?? "handoff";
    fragment.querySelector(".queue-title").textContent =
      state.registry?.workflows?.find((workflow) => workflow.id === job.workflowId)?.title ?? job.workflowId;
    fragment.querySelector(".queue-id").textContent = job.jobId;
    fragment.querySelector(".queue-summary").textContent = queueSummary(job);
    fragment.querySelector(".queue-remove").addEventListener("click", () => {
      state.queue.splice(index, 1);
      persistQueue();
      renderQueue();
    });
    return fragment;
  });
  elements.queueList.replaceChildren(...fragments);
  elements.queueEmpty.hidden = state.queue.length > 0;
  elements.queueCount.textContent = `${state.queue.length} ${state.queue.length === 1 ? "job" : "jobs"}`;
  elements.downloadQueue.disabled = state.queue.length === 0;
  elements.copyQueue.disabled = state.queue.length === 0;
  elements.clearQueue.disabled = state.queue.length === 0;
}

function queueJsonl() {
  return state.queue.map((job) => JSON.stringify(job)).join("\n") + (state.queue.length ? "\n" : "");
}

elements.downloadQueue.addEventListener("click", () => {
  if (state.queue.length) downloadBlob("studio-handoffs.jsonl", queueJsonl(), "application/x-ndjson");
});

elements.copyQueue.addEventListener("click", () => {
  if (state.queue.length) copyText(queueJsonl(), elements.outputFeedback);
});

elements.clearQueue.addEventListener("click", () => {
  state.queue = [];
  persistQueue();
  renderQueue();
});

window.addEventListener("beforeunload", revokeObjectUrls);

const initialView = location.hash.replace(/^#/, "");
if (["launcher", "atlas", "queue", "about"].includes(initialView)) setView(initialView);

renderRunSummary();
renderItems();
renderInspector();
renderQueue();
updateReviewProgress();
loadWorkflowRegistry();
