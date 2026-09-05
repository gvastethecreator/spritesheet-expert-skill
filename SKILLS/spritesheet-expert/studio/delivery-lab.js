/* Local-only artifact viewer. Hashes are of original file bytes, not Canvas pixels. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  let files = new Map(), manifests = new Map(), current = null, selected = 0, view = "atlas";
  let version = 0, receiptVersion = 0, urls = [], externalReceipt = null;
  const state = {errors: [], hashes: {}, manifestSha256: null, receipt: "not supplied"};
  const MAX_FILE_BYTES = 256 * 1024 * 1024;
  const pathOf = file => file.webkitRelativePath || file.name;
  const hash = async file => [...new Uint8Array(await crypto.subtle.digest("SHA-256", await file.arrayBuffer()))].map(v => v.toString(16).padStart(2, "0")).join("");
  function safeRelative(relative) {
    return typeof relative === "string" && relative.length > 0 && !relative.startsWith("/") &&
      !/[\\:]/.test(relative) && !relative.split("/").some(p => !p || p === "." || p === "..");
  }
  function dispose() { for (const url of urls) URL.revokeObjectURL(url); urls = []; }
  function exact(relative, root) {
    if (!safeRelative(relative)) throw new Error(`Unsafe artifact path: ${relative}`);
    const file = files.get(root + relative);
    if (!file) throw new Error(`Missing exact artifact: ${root + relative}`);
    if (file.size > MAX_FILE_BYTES) throw new Error(`Artifact exceeds byte budget: ${relative}`);
    return file;
  }
  async function image(file) {
    const url = URL.createObjectURL(file); urls.push(url);
    const img = new Image();
    await new Promise((resolve, reject) => { img.onload = resolve; img.onerror = () => reject(new Error(`Cannot decode ${file.name}`)); img.src = url; });
    if (img.width * img.height > 50_000_000) throw new Error(`Image exceeds pixel budget: ${file.name}`);
    return img;
  }
  function reportText() {
    if (!current) return "No verified run loaded.";
    const unreviewed = current.manifest.items.filter(i => i.review?.status !== "approved").length;
    return JSON.stringify({schemaVersion: "item-browser-inspection-v1", authority: "inspection-only",
      manifestSha256: state.manifestSha256, fileIdentity: state.errors.length ? "failed" : "verified",
      integrityErrors: state.errors, unresolvedItemReviews: unreviewed,
      pendingPixelsDeclared: current.manifest.completion?.pendingPixels ?? null,
      pythonReceipt: state.receipt, engineSmokeTested: false, verifiedFileHashes: state.hashes}, null, 2);
  }
  async function checkReceipt(epoch) {
    if (!current) return;
    const receiptEpoch = ++receiptVersion;
    const {root, manifest} = current, manifestHash = state.manifestSha256;
    const required = [...Object.keys(state.hashes), manifest.evidence.pendingMask, manifest.evidence.discardedMask];
    const local = files.get(root + "qa/delivery-check.json") || files.get(root + "delivery-check.json");
    const file = externalReceipt || local;
    let result = "not supplied; Python pixel ownership check has not been demonstrated";
    if (file) {
      try {
        if (file.size > 16 * 1024 * 1024) throw new Error("Receipt exceeds size budget");
        const receipt = JSON.parse(await file.text());
        if (receipt.schemaVersion !== "item-delivery-check-v1" || receipt.manifestSha256 !== manifestHash)
          throw new Error("Receipt is for another manifest or contract");
        if (!["pass", "review-required", "invalid"].includes(receipt.status) || typeof receipt.draft !== "boolean" ||
            !Array.isArray(receipt.integrityErrors) || !Array.isArray(receipt.reviewBlockers)) throw new Error("Malformed receipt status");
        if (!receipt.verifiedArtifacts || typeof receipt.verifiedArtifacts !== "object" || Array.isArray(receipt.verifiedArtifacts) ||
            required.some(path => !Object.hasOwn(receipt.verifiedArtifacts, path))) throw new Error("Receipt is missing required artifact hashes");
        if (receipt.status === "pass" && (receipt.integrityErrors.length || (!receipt.draft && receipt.reviewBlockers.length)))
          throw new Error("Contradictory pass receipt");
        for (const [relative, expected] of Object.entries(receipt.verifiedArtifacts)) {
          const actual = await hash(exact(relative, root));
          if (epoch !== version || receiptEpoch !== receiptVersion) return;
          if (actual !== expected) throw new Error(`Stale receipt artifact: ${relative}`);
        }
        result = {status: receipt.status, draft: receipt.draft, reviewBlockers: receipt.reviewBlockers,
          manifestAndRecordedArtifactsMatch: true, authenticatedSignature: false};
      } catch (error) { result = `REJECTED: ${error.message}`; }
    }
    if (epoch !== version || receiptEpoch !== receiptVersion) return;
    state.receipt = result;
    $("check-output").textContent = reportText();
  }
  async function loadManifest() {
    const epoch = ++version;
    dispose(); current = null; selected = 0; state.errors = []; state.hashes = {}; state.manifestSha256 = null;
    $("canvas").hidden = true; $("empty").hidden = false; $("items").replaceChildren();
    $("download").disabled = true; $("previous").disabled = true; $("next").disabled = true;
    try {
      const entry = manifests.get($("manifest").value);
      if (!entry) return;
      const root = entry.path.slice(0, entry.path.lastIndexOf("/") + 1);
      const manifest = entry.manifest;
      if (!Array.isArray(manifest.items) || !manifest.items.length || manifest.items.length > 10000) throw new Error("Invalid item inventory");
      const manifestHash = await hash(entry.file);
      if (epoch !== version) return;
      state.manifestSha256 = manifestHash;
      const needed = [[manifest.atlas.path, manifest.atlas.sha256],
        [manifest.evidence.sourceRgba, manifest.evidence.sourceRgbaSha256],
        ...manifest.items.map(i => [i.artifacts.rgba, i.artifacts.sha256])];
      for (const [relative, expected] of needed) {
        const actual = await hash(exact(relative, root));
        if (epoch !== version) return;
        if (!/^[0-9a-f]{64}$/.test(expected) || actual !== expected) throw new Error(`SHA-256 mismatch: ${relative}`);
        state.hashes[relative] = actual;
      }
      const atlas = await image(exact(manifest.atlas.path, root));
      const source = await image(exact(manifest.evidence.sourceRgba, root));
      if (epoch !== version) return;
      if (atlas.width !== manifest.atlas.width || atlas.height !== manifest.atlas.height ||
          source.width !== manifest.source.width || source.height !== manifest.source.height) throw new Error("Declared image dimensions do not match files");
      const ids = new Set();
      for (const item of manifest.items) {
        if (typeof item.id !== "string" || ids.has(item.id)) throw new Error("Duplicate or missing stable ID");
        ids.add(item.id);
        const g = item.geometry;
        if (!Array.isArray(g.frame) || g.frame.length !== 4 || !g.frame.every(Number.isInteger) ||
            g.frame[0] < 0 || g.frame[1] < 0 || g.frame[2] <= 0 || g.frame[3] <= 0 ||
            g.frame[0] + g.frame[2] > atlas.width || g.frame[1] + g.frame[3] > atlas.height) throw new Error(`Invalid frame: ${item.id}`);
        if (!Array.isArray(g.pivot) || g.pivot.length !== 2 || !g.pivot.every(v => Number.isFinite(v) && v >= 0 && v <= 1)) throw new Error(`Invalid pivot: ${item.id}`);
        if (!Array.isArray(g.cellRect) || g.cellRect.length !== 4 || !g.cellRect.every(Number.isInteger) ||
            !Array.isArray(item.source.bbox) || item.source.bbox.length !== 4 || !item.source.bbox.every(Number.isInteger)) throw new Error(`Invalid bounds: ${item.id}`);
      }
      current = {manifest, root, atlas, source};
      $("status").textContent = `${manifest.items.length} sprites · ${needed.length} file references verified · ${manifest.items.filter(i => i.review?.status !== "approved").length} awaiting approval. Browser identity checks do not replace the Python delivery gate.`;
      $("empty").hidden = true; $("canvas").hidden = false; $("download").disabled = false;
      $("previous").disabled = false; $("next").disabled = false; $("count").textContent = String(manifest.items.length);
      renderItems(); draw(); await checkReceipt(epoch);
    } catch (error) {
      if (epoch !== version) return;
      state.errors.push(error.message); current = null;
      $("status").textContent = `BLOCKED · ${error.message}. No unverified image will be shown.`;
      $("empty").textContent = "Correct the artifact identity error and reload the run folder.";
      $("check-output").textContent = JSON.stringify({status: "blocked", integrityErrors: state.errors}, null, 2);
    }
  }
  function renderItems() {
    if (!current) return;
    $("items").replaceChildren(...current.manifest.items.map((item, index) => {
      const button = document.createElement("button"); button.className = "item"; button.setAttribute("aria-pressed", String(index === selected));
      const img = document.createElement("img"), url = URL.createObjectURL(exact(item.artifacts.rgba, current.root));
      urls.push(url); img.src = url; img.alt = "";
      const text = document.createElement("span"), title = document.createElement("span"), detail = document.createElement("small");
      title.textContent = item.classification?.canonicalType || item.id;
      detail.textContent = `${item.id} · ${item.review?.status || "pending"}`; text.append(title, detail); button.append(img, text);
      button.addEventListener("click", () => { selected = index; syncSelection(); }); return button;
    }));
  }
  function syncSelection() {
    [...$("items").children].forEach((button, index) => button.setAttribute("aria-pressed", String(index === selected)));
    draw();
  }
  function backdrop(ctx, width, height) {
    const backgrounds = {black: "#000", white: "#fff", gray: "#777", checker: "#292929"};
    ctx.fillStyle = backgrounds[$("background").value]; ctx.fillRect(0, 0, width, height);
    if ($("background").value === "checker") {
      ctx.fillStyle = "#363636";
      for (let y = 0; y < height; y += 16) for (let x = 0; x < width; x += 16)
        if ((x / 16 + y / 16) % 2) ctx.fillRect(x, y, 16, 16);
    }
  }
  function draw() {
    if (!current || view === "delivery") return;
    const item = current.manifest.items[selected], canvas = $("canvas"), zoom = Number($("zoom").value);
    const g = item.geometry, [x, y, w, h] = g.frame;
    const base = view === "source" ? current.source : current.atlas;
    canvas.width = view === "placement" ? Math.max(320, w + 96) : base.width;
    canvas.height = view === "placement" ? Math.max(240, h + 96) : base.height;
    canvas.style.width = `${canvas.width * zoom}px`; canvas.style.height = `${canvas.height * zoom}px`;
    const ctx = canvas.getContext("2d"); ctx.imageSmoothingEnabled = false; backdrop(ctx, canvas.width, canvas.height);
    const overlays = $("overlay").value === "on";
    if (view === "placement") {
      // Center the actual crop so extreme pivots do not clip the diagnostic.
      const left = Math.floor((canvas.width - w) / 2), top = Math.floor((canvas.height - h) / 2);
      const px = left + w * g.pivot[0], py = top + h * g.pivot[1];
      ctx.drawImage(current.atlas, x, y, w, h, left, top, w, h);
      if (overlays) {
        ctx.strokeStyle = "#a59d90"; ctx.beginPath(); ctx.moveTo(0, py + .5); ctx.lineTo(canvas.width, py + .5); ctx.stroke();
        ctx.strokeStyle = "#e4bf7b"; ctx.beginPath(); ctx.moveTo(px - 8, py); ctx.lineTo(px + 8, py); ctx.moveTo(px, py - 8); ctx.lineTo(px, py + 8); ctx.stroke();
      }
    } else {
      ctx.drawImage(base, 0, 0);
      if (overlays) {
        ctx.lineWidth = 1; ctx.strokeStyle = "#777";
        for (const other of current.manifest.items) {
          const r = view === "source" ? other.source.bbox : other.geometry.cellRect;
          ctx.strokeRect(r[0] + .5, r[1] + .5, view === "source" ? r[2] - r[0] : r[2], view === "source" ? r[3] - r[1] : r[3]);
        }
        ctx.strokeStyle = "#e4bf7b"; ctx.lineWidth = 2;
        if (view === "source") { const b = item.source.bbox; ctx.strokeRect(b[0], b[1], b[2] - b[0], b[3] - b[1]); }
        else ctx.strokeRect(x, y, w, h);
      }
    }
    $("item-info").textContent = `${item.id} / ${item.review?.status || "pending"}`;
    $("geometry-info").textContent = `XYXY [${item.source.bbox.join(", ")}] / XYWH [${g.frame.join(", ")}]`;
    $("pivot-info").textContent = `${w} × ${h} / [${g.pivot.join(", ")}]`;
  }
  $("folder").addEventListener("change", async () => {
    const epoch = ++version; dispose(); files = new Map(); manifests = new Map(); current = null;
    $("manifest").disabled = true; $("status").textContent = "Reading local manifests…";
    $("canvas").hidden = true; $("empty").hidden = false; $("items").replaceChildren();
    $("download").disabled = true; $("previous").disabled = true; $("next").disabled = true; $("count").textContent = "0";
    try {
      for (const file of $("folder").files) {
        const path = pathOf(file); if (files.has(path)) throw new Error(`Duplicate path: ${path}`); files.set(path, file);
      }
      for (const [path, file] of files) {
        if (!/manifest[^/]*\.json$/i.test(path) || file.size > 16 * 1024 * 1024) continue;
        try {
          const manifest = JSON.parse(await file.text());
          if (epoch !== version) return;
          if (manifest.kind === "deterministic-item-atlas" && manifest.schemaVersion === "deterministic-item-sheet-v1") manifests.set(path, {path, file, manifest});
        } catch { /* Not every JSON in a run is a manifest. */ }
      }
      if (!manifests.size) throw new Error("No supported deterministic item-atlas manifest found");
      $("manifest").replaceChildren(...[...manifests.keys()].map(path => new Option(path, path)));
      $("manifest").disabled = false; await loadManifest();
    } catch (error) { if (epoch === version) $("status").textContent = `BLOCKED · ${error.message}`; }
  });
  $("manifest").addEventListener("change", loadManifest);
  $("receipt").addEventListener("change", async () => { externalReceipt = $("receipt").files[0] || null; await checkReceipt(version); });
  for (const element of document.querySelectorAll("[data-view]")) element.addEventListener("click", () => {
    view = element.dataset.view; document.querySelectorAll("[data-view]").forEach(button => button.setAttribute("aria-selected", String(button === element)));
    $("visual").hidden = view === "delivery"; $("delivery").hidden = view !== "delivery"; draw();
  });
  for (const id of ["zoom", "background", "overlay"]) $(id).addEventListener("change", draw);
  function step(delta) { if (current) { selected = (selected + delta + current.manifest.items.length) % current.manifest.items.length; syncSelection(); } }
  $("previous").addEventListener("click", () => step(-1)); $("next").addEventListener("click", () => step(1));
  document.addEventListener("keydown", event => {
    if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName)) return;
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.preventDefault(); step(event.key === "ArrowRight" ? 1 : -1); }
  });
  $("download").addEventListener("click", () => {
    if (!current) return;
    const url = URL.createObjectURL(new Blob([reportText()], {type: "application/json"}));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = "browser-inspection.json"; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  window.addEventListener("beforeunload", dispose);
})();
