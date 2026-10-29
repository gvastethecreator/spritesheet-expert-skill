// SPDX-License-Identifier: Apache-2.0
// sprite-gen curation webview — vanilla JS, no build step.
//
// Edits never touch the source frame PNGs. They mutate an in-memory model that
// mirrors curation.json and is auto-saved (debounced) via POST /api/curation.
// rotate is degrees, counter-clockwise positive (matches PIL bake). The preview
// (CSS + canvas) negates it because screen/CSS/canvas positive rotation is
// clockwise, so what you see is what compose_sprite_atlas.py will bake.

const IDENTITY = () => ({ rotate: 0, scale: 1, dx: 0, dy: 0, shx: 0, shy: 0, flipX: 0 });
const SCALE_MIN = 0.2;
const SCALE_MAX = 3;
const DRAG_THRESHOLD = 4;

// forward 2x2 matrix (Rotate · Shear · Scale · FlipX); mirrors curation.py transform_matrix
function matrixOf(t) {
  const rr = (t.rotate * Math.PI) / 180;
  const c = Math.cos(rr);
  const sn = Math.sin(rr);
  const s = t.scale;
  const shx = t.shx || 0;
  const shy = t.shy || 0;
  let m00 = s * (c + sn * shy);
  const m01 = s * (c * shx + sn);
  let m10 = s * (-sn + c * shy);
  const m11 = s * (c - sn * shx);
  // (Alex 2026-05-28) flipX = horizontal mirror (image-gen 결과가 좌우 반대로
  // 나올 때). diag(-1, 1) 을 matrix 마지막에 곱 → column-0 부호 반전.
  if (t.flipX) {
    m00 = -m00;
    m10 = -m10;
  }
  return { m00, m01, m10, m11 };
}

// --- UI copy (English) -------------------------------------------------------
const STR = {
  frames: "frames", loop: "loop", nonLoop: "one-shot", preview: "Preview",
  excluded: "Excluded", selected: "Selected", extractFail: "Extraction incomplete",
  editing: "Editing…", saved: "Saved", saveFail: "Save failed: ",
  baking: "Baking atlas…", composeDone: "Atlas baked", composeFail: "Bake failed: ",
  exporting: "Exporting…", exportFail: "Export failed: ",
  ready: "Ready", loaded: "Loaded existing curation", runLoadFail: "Could not load the run:",
  tRotate: "Drag to rotate", tShear: "Drag to shear (horizontal = shx, vertical = shy)", tReset: "Reset transform", tFlipX: "Flip horizontally",
  exportDone: (n) => `Exported ${n} PNGs to curated/`,
};
const t = (key) => STR[key];

let run = null; // /api/run snapshot
let entries = {}; // { stateName: { selected: [idx], transforms: { idx: {..} } } }
const imageCache = new Map();

const statusEl = document.getElementById("status");
let saveTimer = null;

function setStatus(text, kind = "") {
  statusEl.textContent = text;
  statusEl.className = "status" + (kind ? " " + kind : "");
}

function img(url) {
  if (!imageCache.has(url)) {
    const i = new Image();
    i.src = url;
    imageCache.set(url, i);
  }
  return imageCache.get(url);
}

function getTransform(stateName, idx) {
  const t = entries[stateName].transforms;
  if (!t[idx]) t[idx] = IDENTITY();
  return t[idx];
}

function isSelected(stateName, idx) {
  return entries[stateName].selected.includes(idx);
}

function toggleSelect(stateName, idx) {
  const sel = entries[stateName].selected;
  const at = sel.indexOf(idx);
  if (at >= 0) sel.splice(at, 1);
  else {
    sel.push(idx);
    sel.sort((a, b) => a - b);
  }
}

// --- persistence -----------------------------------------------------------

function buildPayload() {
  const states = {};
  for (const [name, entry] of Object.entries(entries)) {
    const transforms = {};
    for (const [idx, t] of Object.entries(entry.transforms)) {
      if (t.rotate || t.scale !== 1 || t.dx || t.dy || t.shx || t.shy || t.flipX) transforms[idx] = t;
    }
    states[name] = { selected: entry.selected, transforms };
  }
  return { version: run.schemaVersion || 1, kind: "sprite-gen-curation", states };
}

function scheduleSave() {
  setStatus(t("editing"));
  clearTimeout(saveTimer);
  saveTimer = setTimeout(save, 250);
}

async function save() {
  try {
    const res = await fetch("/api/curation", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildPayload()),
    });
    if (!res.ok) throw new Error((await res.json()).error || res.statusText);
    setStatus(t("saved"), "ok");
  } catch (e) {
    setStatus(t("saveFail") + e.message, "err");
  }
}

// --- transform application -------------------------------------------------

function applyCardTransform(stage, stateName, idx) {
  const t = getTransform(stateName, idx);
  const el = stage.querySelector("img");
  if (!el) return;
  // dx/dy are stored in cell pixels; CSS needs rendered pixels.
  const ds = stage.clientWidth / run.cell.width;
  const m = matrixOf(t);
  // CSS matrix(a,b,c,d,e,f): a=m00 b=m10 c=m01 d=m11; translate applied after, about center.
  el.style.transform =
    `translate(${t.dx * ds}px, ${t.dy * ds}px) matrix(${m.m00}, ${m.m10}, ${m.m01}, ${m.m11}, 0, 0)`;
  const sh = t.shx || t.shy ? ` sh${(t.shx || 0).toFixed(2)},${(t.shy || 0).toFixed(2)}` : "";
  const flip = t.flipX ? " ↔" : "";
  const card = stage.closest(".frame-card");
  const tvals = card.querySelector(".tvals");
  tvals.textContent =
    `r${t.rotate.toFixed(0)}° ×${t.scale.toFixed(2)} ${t.dx >= 0 ? "+" : ""}${t.dx.toFixed(0)},${t.dy >= 0 ? "+" : ""}${t.dy.toFixed(0)}${sh}${flip}`;
  tvals.title = tvals.textContent;
  const flipBtn = card.querySelector(".flip-btn");
  if (flipBtn) flipBtn.setAttribute("aria-pressed", String(!!t.flipX));
}

// --- interactions ----------------------------------------------------------

function wireStage(stage, stateName, idx) {
  const ds = () => stage.clientWidth / run.cell.width;

  // translate by dragging, toggle select on a click that did not drag
  stage.addEventListener("pointerdown", (ev) => {
    if (ev.target.classList.contains("rotate-handle")) return;
    ev.preventDefault();
    stage.setPointerCapture(ev.pointerId);
    const t = getTransform(stateName, idx);
    const start = { x: ev.clientX, y: ev.clientY, dx: t.dx, dy: t.dy };
    let moved = false;

    const onMove = (e) => {
      const ddx = e.clientX - start.x;
      const ddy = e.clientY - start.y;
      if (Math.abs(ddx) > DRAG_THRESHOLD || Math.abs(ddy) > DRAG_THRESHOLD) moved = true;
      t.dx = start.dx + ddx / ds();
      t.dy = start.dy + ddy / ds();
      applyCardTransform(stage, stateName, idx);
    };
    const onUp = (e) => {
      stage.releasePointerCapture(ev.pointerId);
      stage.removeEventListener("pointermove", onMove);
      stage.removeEventListener("pointerup", onUp);
      if (!moved) {
        toggleSelect(stateName, idx);
        renderSelectionState(stateName);
      }
      scheduleSave();
    };
    stage.addEventListener("pointermove", onMove);
    stage.addEventListener("pointerup", onUp);
  });

  // scale with the wheel
  stage.addEventListener(
    "wheel",
    (ev) => {
      ev.preventDefault();
      const t = getTransform(stateName, idx);
      const factor = ev.deltaY < 0 ? 1.05 : 1 / 1.05;
      t.scale = Math.min(SCALE_MAX, Math.max(SCALE_MIN, t.scale * factor));
      applyCardTransform(stage, stateName, idx);
      scheduleSave();
    },
    { passive: false }
  );

  // rotate via the top handle
  const handle = stage.querySelector(".rotate-handle");
  handle.addEventListener("pointerdown", (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    handle.setPointerCapture(ev.pointerId);
    const rect = stage.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const t = getTransform(stateName, idx);
    const startScreen = Math.atan2(ev.clientY - cy, ev.clientX - cx);
    const origRotate = t.rotate;

    const onMove = (e) => {
      const now = Math.atan2(e.clientY - cy, e.clientX - cx);
      // screen angle grows clockwise; schema is CCW positive -> subtract.
      const deltaDeg = ((now - startScreen) * 180) / Math.PI;
      t.rotate = origRotate - deltaDeg;
      applyCardTransform(stage, stateName, idx);
    };
    const onUp = () => {
      handle.releasePointerCapture(ev.pointerId);
      handle.removeEventListener("pointermove", onMove);
      handle.removeEventListener("pointerup", onUp);
      scheduleSave();
    };
    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", onUp);
  });

  // shear via the bottom-left handle: horizontal drag = shx, vertical = shy
  const shear = stage.querySelector(".shear-handle");
  shear.addEventListener("pointerdown", (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    shear.setPointerCapture(ev.pointerId);
    const t = getTransform(stateName, idx);
    const start = { x: ev.clientX, y: ev.clientY, shx: t.shx || 0, shy: t.shy || 0 };
    const onMove = (e) => {
      // full-width drag ≈ 1.0 slope; small moves give fine control
      t.shx = start.shx + (e.clientX - start.x) / stage.clientWidth;
      t.shy = start.shy + (e.clientY - start.y) / stage.clientHeight;
      applyCardTransform(stage, stateName, idx);
    };
    const onUp = () => {
      shear.releasePointerCapture(ev.pointerId);
      shear.removeEventListener("pointermove", onMove);
      shear.removeEventListener("pointerup", onUp);
      scheduleSave();
    };
    shear.addEventListener("pointermove", onMove);
    shear.addEventListener("pointerup", onUp);
  });
}

function resetTransform(stateName, idx, stage) {
  entries[stateName].transforms[idx] = IDENTITY();
  applyCardTransform(stage, stateName, idx);
  scheduleSave();
}

// --- rendering -------------------------------------------------------------

function renderSelectionState(stateName) {
  document.querySelectorAll(`.frame-card[data-state="${cssEscape(stateName)}"]`).forEach((card) => {
    const idx = Number(card.dataset.idx);
    const sel = isSelected(stateName, idx);
    card.classList.toggle("selected", sel);
    card.classList.toggle("rejected", !sel);
    const btn = card.querySelector(".sel-btn");
    if (btn) {
      btn.textContent = sel ? t("selected") : t("excluded");
      btn.setAttribute("aria-pressed", String(sel));
    }
  });
  const state = run.states.find((s) => s.name === stateName);
  const count = `${entries[stateName].selected.length}/${state.requestFrames} ${t("frames")}`;
  const countEl = document.querySelector(`.preview[data-state="${cssEscape(stateName)}"] .count`);
  if (countEl) countEl.textContent = count;
  const chip = document.querySelector(`.state[data-state="${cssEscape(stateName)}"] .chip`);
  if (chip) {
    chip.textContent = count;
    chip.dataset.status = entries[stateName].selected.length === state.requestFrames ? "approved" : "pending";
  }
}

function cssEscape(s) {
  return s.replace(/"/g, '\\"');
}

// Run data (state names, actions, labels, paths) is untrusted text inside markup.
function esc(value) {
  return String(value).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

function renderState(state) {
  const wrap = document.createElement("section");
  wrap.className = "state card";
  wrap.dataset.state = state.name;

  const head = document.createElement("div");
  head.className = "state-head";
  head.innerHTML =
    `<h2 class="name">${esc(state.name)}</h2>` +
    `<span class="meta">${state.requestFrames} ${t("frames")} · ${state.fps} fps · ${state.loop ? t("loop") : t("nonLoop")}</span>` +
    (state.action ? `<span class="action">${esc(state.action)}</span>` : "") +
    (state.extractOk ? "" : `<span class="chip" data-status="rejected">${t("extractFail")}</span>`) +
    `<span class="chip" data-status="pending"></span>`;
  wrap.appendChild(head);

  const body = document.createElement("div");
  body.className = "state-body";

  const framesEl = document.createElement("div");
  framesEl.className = "frames";
  for (const frame of state.frames) {
    framesEl.appendChild(renderCard(state, frame));
  }
  body.appendChild(framesEl);
  body.appendChild(renderPreview(state));
  wrap.appendChild(body);

  document.getElementById("states").appendChild(wrap);

  // wire stages after they are in the DOM (need clientWidth)
  for (const frame of state.frames) {
    if (!frame.present) continue;
    const stage = wrap.querySelector(`.frame-card[data-idx="${frame.index}"] .cell`);
    wireStage(stage, state.name, frame.index);
    applyCardTransform(stage, state.name, frame.index);
    if (run.iso) drawGroundGrid(stage);
  }
  renderSelectionState(state.name);
  startPreview(state);
}

function renderCard(state, frame) {
  const card = document.createElement("div");
  card.className = "frame-card";
  card.dataset.state = state.name;
  card.dataset.idx = frame.index;
  if (!frame.present) card.classList.add("missing");
  card.style.setProperty("--cell-aspect", run.cell.width / run.cell.height);

  const stageInner = frame.present
    ? (run.iso ? `<canvas class="grid-overlay"></canvas>` : "") +
      `<img src="${esc(frame.url)}" alt="Frame ${frame.index}" draggable="false" />` +
      `<div class="rotate-handle" title="${t("tRotate")}"></div>` +
      `<div class="shear-handle" title="${t("tShear")}"></div>`
    : `<div class="missing-label">Missing</div>`;

  const label = esc(frame.label ? frame.label : `#${frame.index}`);
  card.innerHTML =
    `<div class="card-top">` +
    `<span class="idx" title="Frame ${frame.index}">${label}</span>` +
    `<button type="button" class="btn sel-btn" aria-pressed="false">${t("excluded")}</button>` +
    `</div>` +
    `<div class="cell">${stageInner}</div>` +
    `<div class="card-controls">` +
    `<span class="tvals"></span>` +
    `<span class="group">` +
    `<button type="button" class="btn btn-icon flip-btn" title="${t("tFlipX")}" aria-label="${t("tFlipX")}" aria-pressed="false">↔</button>` +
    `<button type="button" class="btn btn-icon reset-btn" title="${t("tReset")}" aria-label="${t("tReset")}">↺</button>` +
    `</span>` +
    `</div>`;

  card.querySelector(".sel-btn").addEventListener("click", () => {
    toggleSelect(state.name, frame.index);
    renderSelectionState(state.name);
    scheduleSave();
  });
  if (frame.present) {
    card.querySelector(".reset-btn").addEventListener("click", () =>
      resetTransform(state.name, frame.index, card.querySelector(".cell"))
    );
    card.querySelector(".flip-btn").addEventListener("click", () =>
      toggleFlipX(state.name, frame.index, card.querySelector(".cell"))
    );
  } else {
    card.querySelectorAll(".flip-btn, .reset-btn").forEach((btn) => (btn.disabled = true));
  }
  return card;
}

/** Toggle horizontal flip for a single frame (Alex 2026-05-28). */
function toggleFlipX(stateName, idx, stage) {
  const entry = entries[stateName];
  if (!entry) return;
  if (!entry.transforms[idx]) entry.transforms[idx] = IDENTITY();
  entry.transforms[idx].flipX = entry.transforms[idx].flipX ? 0 : 1;
  // applyCardTransform renders the mirror and highlights the flip button.
  applyCardTransform(stage, stateName, idx);
  scheduleSave();
}

function renderPreview(state) {
  const box = document.createElement("div");
  box.className = "preview";
  box.dataset.state = state.name;
  const aspect = run.cell.height / run.cell.width;
  box.innerHTML =
    `<h3 class="rail-title">${t("preview")}</h3>` +
    `<canvas width="${run.cell.width}" height="${run.cell.height}" style="height:${(160 * aspect).toFixed(0)}px" aria-label="${esc(state.name)} playback preview"></canvas>` +
    `<div class="count"></div>`;
  return box;
}

function startPreview(state) {
  const canvas = document.querySelector(`.preview[data-state="${cssEscape(state.name)}"] canvas`);
  const ctx = canvas.getContext("2d");
  const cw = run.cell.width;
  const ch = run.cell.height;
  let cursor = 0;
  let last = 0;

  function frame(ts) {
    const sel = entries[state.name].selected;
    const interval = 1000 / Math.max(1, state.fps);
    if (ts - last >= interval) {
      last = ts;
      cursor = sel.length ? (cursor + 1) % sel.length : 0;
    }
    ctx.clearRect(0, 0, cw, ch);
    if (sel.length) {
      const idx = sel[cursor % sel.length];
      const url = state.frames[idx] ? state.frames[idx].url : null;
      const image = url ? img(url) : null;
      if (image && image.complete && image.naturalWidth) {
        const t = getTransform(state.name, idx);
        const m = matrixOf(t);
        ctx.save();
        ctx.translate(cw / 2 + t.dx, ch / 2 + t.dy);
        ctx.transform(m.m00, m.m10, m.m01, m.m11, 0, 0); // same matrix as CSS + bake
        ctx.drawImage(image, -cw / 2, -ch / 2, cw, ch);
        ctx.restore();
      }
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

// --- iso ground grid overlay -----------------------------------------------

function drawGroundGrid(stage) {
  const canvas = stage.querySelector(".grid-overlay");
  if (!canvas || !run.iso) return;
  const rect = stage.getBoundingClientRect();
  const W = Math.round(rect.width);
  const H = Math.round(rect.height);
  if (!W || !H) return;
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, W, H);

  // cell pixels -> displayed pixels
  const ds = W / run.cell.width;
  const tw = run.iso.tile.width * ds;   // diamond full width (2:1 -> width = 2*height)
  const th = run.iso.tile.height * ds;  // diamond full height
  const [ax, ay] = run.iso.anchor_pixel;
  const ox = ax * ds; // anchor in displayed px
  const oy = ay * ds;

  // grid-(gx,gy) center on screen, 2:1 dimetric, anchored at the meta anchor
  const center = (gx, gy) => [ox + (gx - gy) * (tw / 2), oy + (gx + gy) * (th / 2)];
  const diamond = (cx, cy) => {
    ctx.beginPath();
    ctx.moveTo(cx, cy - th / 2);
    ctx.lineTo(cx + tw / 2, cy);
    ctx.lineTo(cx, cy + th / 2);
    ctx.lineTo(cx - tw / 2, cy);
    ctx.closePath();
  };

  const R = 4;
  const token = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  ctx.lineWidth = 1;
  ctx.strokeStyle = token("--accent");
  for (let gx = -R; gx <= R; gx++) {
    for (let gy = -R; gy <= R; gy++) {
      const [cx, cy] = center(gx, gy);
      diamond(cx, cy);
      ctx.globalAlpha = gx === 0 && gy === 0 ? 0.95 : 0.3;
      ctx.stroke();
    }
  }
  // axis guide lines through the anchor (the true 2:1 slopes)
  ctx.globalAlpha = 0.85;
  ctx.strokeStyle = token("--warn");
  ctx.lineWidth = 1.5;
  for (const [sx, sy] of [[1, 1], [1, -1]]) {
    ctx.beginPath();
    ctx.moveTo(ox - sx * tw * 3, oy - sy * th * 3);
    ctx.lineTo(ox + sx * tw * 3, oy + sy * th * 3);
    ctx.stroke();
  }
}

const gridToggle = document.getElementById("grid-toggle");
gridToggle.addEventListener("click", () => {
  const on = document.body.classList.toggle("show-grid");
  gridToggle.setAttribute("aria-pressed", String(on));
  if (on) document.querySelectorAll(".cell").forEach(drawGroundGrid);
});

document.querySelectorAll("[data-matte]").forEach((button) => {
  if (button.tagName !== "BUTTON") return;
  button.addEventListener("click", () => {
    document.getElementById("states").dataset.matte = button.dataset.matte;
    document.querySelectorAll("button[data-matte]").forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
  });
});

document.getElementById("theme-toggle").addEventListener("click", () => {
  if (document.body.classList.contains("show-grid")) requestAnimationFrame(() => document.querySelectorAll(".cell").forEach(drawGroundGrid));
});

// --- compose ---------------------------------------------------------------

document.getElementById("compose").addEventListener("click", async (ev) => {
  const btn = ev.currentTarget;
  btn.disabled = true;
  clearTimeout(saveTimer);
  await save();
  setStatus(t("baking"));
  try {
    const res = await fetch("/api/compose", { method: "POST" });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error((data.stderr || data.error || "compose failed").trim());
    setStatus(t("composeDone"), "ok");
  } catch (e) {
    setStatus(t("composeFail") + e.message, "err");
  } finally {
    btn.disabled = false;
  }
});

document.getElementById("export").addEventListener("click", async (ev) => {
  const btn = ev.currentTarget;
  btn.disabled = true;
  clearTimeout(saveTimer);
  await save();
  setStatus(t("exporting"));
  try {
    const res = await fetch("/api/export", { method: "POST" });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error((data.stderr || data.error || "export failed").trim());
    const out = data.export || {};
    setStatus(STR.exportDone(out.count || 0), "ok");
    console.log("exported to:", out.out_dir, out.files);
  } catch (e) {
    setStatus(t("exportFail") + e.message, "err");
  } finally {
    btn.disabled = false;
  }
});

// --- bootstrap -------------------------------------------------------------

function seedEntries() {
  entries = {};
  const curated = (run.curation && run.curation.states) || {};
  for (const state of run.states) {
    const present = state.frames.filter((f) => f.present).map((f) => f.index);
    const c = curated[state.name];
    let selected;
    if (c && Array.isArray(c.selected) && c.selected.length) {
      selected = c.selected.filter((i) => present.includes(i));
    } else {
      selected = present.slice();
    }
    const transforms = {};
    if (c && c.transforms) {
      for (const [idx, t] of Object.entries(c.transforms)) {
        transforms[idx] = { ...IDENTITY(), ...t };
      }
    }
    entries[state.name] = { selected, transforms };
  }
}

async function boot() {
  try {
    const res = await fetch("/api/run");
    run = await res.json();
    if (run.error) throw new Error(run.error);
  } catch (e) {
    document.getElementById("states").innerHTML =
      `<div class="fatal">${t("runLoadFail")}\n${esc(e.message)}</div>`;
    return;
  }
  document.getElementById("character").textContent = `${run.characterId} · ${run.cell.width}×${run.cell.height}`;
  document.title = `Frame curation · ${run.characterId}`;
  if (run.iso) gridToggle.hidden = false;
  seedEntries();
  for (const state of run.states) renderState(state);
  setStatus(run.curation && Object.keys(run.curation.states || {}).length ? t("loaded") : t("ready"));
}

// tool-theme:start (generated from spritecore/tool_theme.py by sync_tool_theme.py; do not edit)
(() => {
  const root = document.documentElement;
  const button = document.getElementById('theme-toggle');
  const key = 'sprite-tools-theme';
  const effective = () => root.dataset.theme || (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
  const label = () => { if (button) button.setAttribute('aria-label', `Switch to ${effective() === 'dark' ? 'light' : 'dark'} theme`); };
  try { const saved = localStorage.getItem(key); if (saved === 'light' || saved === 'dark') root.dataset.theme = saved; } catch (_error) {}
  label();
  if (button) button.addEventListener('click', () => {
    root.dataset.theme = effective() === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem(key, root.dataset.theme); } catch (_error) {}
    label();
  });
})();
// tool-theme:end

boot();
