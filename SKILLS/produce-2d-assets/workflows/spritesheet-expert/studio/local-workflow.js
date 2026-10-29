import {request as api, session} from './studio-client.js';
import {paintMatte} from './matte.js';

const $ = (id) => document.getElementById(`local-${id}`);
let runId = "", snapshot = null, sourceImage = null, pendingImage = null;
let selected = new Set(), strokes = [], currentStroke = null, lastHash = "", loading = false;
const itemImages = new Map();

function action(fn) {
  return async (...args) => {
    try { await fn(...args); }
    catch (error) { $("status").textContent = error.message; }
  };
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image(); image.onload = () => resolve(image); image.onerror = () => reject(new Error("Cannot load run image")); image.src = url;
  });
}

async function refreshRuns() {
  const runs = await api("/api/runs");
  $("runs").replaceChildren(new Option("Select a run", ""), ...runs.filter(run => run.lane === 'static-items').map(run => new Option(`${run.id.slice(0,8)} · ${run.name} · ${run.status}`, run.id)));
  $("runs").value = runId;
}

function primary() { return snapshot?.document?.items.find(item => selected.has(item.id)); }

function renderItems() {
  if (!snapshot?.document) return;
  const items = [...snapshot.document.items].sort((a,b) => (a.geometry.pageId || '').localeCompare(b.geometry.pageId || '') || a.geometry.cellRect[1]-b.geometry.cellRect[1] || a.geometry.cellRect[0]-b.geometry.cellRect[0]);
  const list = [];
  for (const item of items) {
    const needsReview = item.review.status !== "approved";
    if ($("doubts").checked && !needsReview) continue;
    const card = document.createElement("label"); card.className = "local-card"; card.dataset.itemId = item.id;
    card.classList.toggle("selected", selected.has(item.id));
    const check = document.createElement("input"); check.type = "checkbox"; check.checked = selected.has(item.id); check.setAttribute("aria-label", `Select ${item.id}`);
    check.addEventListener("change", () => {
      if (check.checked) selected.add(item.id); else selected.delete(item.id);
      renderItems(); action(inspectSelection)();
    });
    const image = document.createElement("img"); image.src = snapshot.artifactBase + item.artifacts.rgba;
    image.alt = item.classification.canonicalType;
    const copy = document.createElement("span");
    const title = document.createElement("strong"); title.textContent = item.classification.canonicalType === "unknown" ? item.source.lineage?.label || "Unclassified sprite" : item.classification.canonicalType;
    const size = document.createElement("small"); size.textContent = `${item.geometry.originalSize.join(" × ")} · ${item.classification.family}`;
    const status = document.createElement("small"); status.textContent = needsReview ? item.qaFlags.join(", ").replaceAll("_", " ") || "Awaiting review" : "Reviewed";
    copy.append(title, size, status); card.append(check, image, copy); list.push(card);
  }
  if (!list.length) { const empty = document.createElement("p"); empty.textContent = "No items in this filter. Disable it to inspect all sprites."; list.push(empty); }
  $("items").replaceChildren(...list);
}

async function inspectSelection() {
  const item = primary();
  $("family").value = item?.classification.family || "";
  $("type").value = item?.classification.canonicalType || "";
  $("tags").value = item?.classification.tags?.join(", ") || "";
  if (item && !itemImages.has(item.id)) itemImages.set(item.id, await loadImage(snapshot.artifactBase + item.artifacts.rgba));
  $("crop-pair").hidden = !item;
  if (item) for (const background of ["light", "dark"]) {
    const image = $("crop-" + background);
    image.src = snapshot.artifactBase + item.artifacts.rgba;
    image.alt = `${item.id} · ${item.classification.canonicalType} · native pixels`;
  }
  draw();
}

function draw() {
  if (!sourceImage) return;
  const canvas = $("canvas"), context = canvas.getContext("2d");
  canvas.width = sourceImage.width; canvas.height = sourceImage.height;
  const zoom = $("zoom").value;
  canvas.style.width = zoom === "fit" ? "100%" : `${sourceImage.width * Number(zoom)}px`;
  paintMatte(context, canvas.width, canvas.height, $("bg").value);
  context.drawImage(sourceImage,0,0);
  if ($("overlay").checked) {
    const item = primary(), image = item ? itemImages.get(item.id) : pendingImage;
    if (image) {
      const mask = document.createElement("canvas"); mask.width = image.width; mask.height = image.height;
      const ctx = mask.getContext("2d"); ctx.drawImage(image,0,0);
      if (!item) {
        const pixels = ctx.getImageData(0,0,mask.width,mask.height);
        for (let i=0;i<pixels.data.length;i+=4) pixels.data[i+3] = pixels.data[i];
        ctx.putImageData(pixels,0,0);
      }
      ctx.globalCompositeOperation = "source-in"; ctx.fillStyle = item ? "#a4e87b" : "#ef54bd"; ctx.fillRect(0,0,mask.width,mask.height);
      context.globalAlpha = .65; context.drawImage(mask,item?.source.bbox[0] || 0,item?.source.bbox[1] || 0); context.globalAlpha = 1;
    }
  }
  context.globalAlpha = .7;
  for (const stroke of [...strokes, ...(currentStroke ? [currentStroke] : [])]) {
    context.fillStyle = stroke.target === "discard" ? "#e26459" : stroke.target === "pending" ? "#ef54bd" : "#87beff";
    for (const [x,y] of stroke.points) { context.beginPath(); context.arc(x,y,stroke.radius,0,Math.PI*2); context.fill(); }
  }
  context.globalAlpha = 1;
  $("apply").disabled = !strokes.length; $("undo").disabled = !strokes.length;
}

async function refresh() {
  if (!runId || loading) return;
  loading = true;
  try {
    const id = runId, next = await api(`/api/runs/${id}`);
    if (id !== runId) return;
    const changed = snapshot?.status !== next.status || snapshot?.manifestSha256 !== next.manifestSha256;
    snapshot = next;
    let option = [...$('runs').options].find(option => option.value === id);
    if (!option) { option = new Option('', id); $('runs').append(option); }
    option.textContent = `${id.slice(0, 8)} · ${next.name} · ${next.status}`;
    $('runs').value = id;
    if (changed) window.dispatchEvent(new Event('studio:workspace-changed'));
    $("status").textContent = `${next.name} · ${next.status}${next.active ? ` · ${next.stage || "starting"}` : ""}${next.document ? ` · ${next.document.items.length} sprites · ${next.reviewCount} to review · ${next.pendingPixels} pending pixels` : ""}${next.error ? ` · ${next.error}` : ""}`;
    $("log").textContent = next.log || "";
    $("cancel").disabled = !next.active;
    $("resume").disabled = next.active || !["failed","cancelled","interrupted","imported"].includes(next.status);
    $("export").disabled = !next.document || next.active || next.reviewCount>0 || next.pendingPixels>0;
    $("draft").disabled = !next.document || next.active;
    $("review").hidden = !next.document;
    if (next.document && next.manifestSha256 !== lastHash) {
      selected = new Set([...selected].filter(id => next.document.items.some(item => item.id === id)));
      itemImages.clear(); strokes = [];
      const [source, pending] = await Promise.all([loadImage(next.artifactBase+next.document.evidence.sourceRgba),loadImage(next.artifactBase+next.document.evidence.pendingMask)]);
      if (id !== runId) return;
      sourceImage = source; pendingImage = pending; lastHash = next.manifestSha256;
      $("atlas").src = next.artifactBase+next.document.atlas.path;
      const pages = next.document.pages || [{id: 'page-0001', ...next.document.atlas}];
      $('atlas-page').replaceChildren(...pages.map(page => new Option(`${page.id} · ${page.width} × ${page.height}`, page.path)));
      renderItems(); await inspectSelection();
    }
  } finally { loading = false; }
}

async function review(operations) {
  if (!snapshot?.document) throw new Error("Select a completed run first");
  await api(`/api/runs/${runId}/review`, {parentManifestSha256: snapshot.manifestSha256, operations});
  await refresh();
  window.dispatchEvent(new Event('studio:workspace-changed'));
}

$("start").addEventListener("click", action(async () => {
  ensureSavedStrokes();
  const file = $("source").files[0]; if (!file) throw new Error("Choose a transparent source image");
  $("start").disabled = true;
  try {
    const response = await api('/api/import', file, {raw: true, headers: {
      'X-Filename': encodeURIComponent(file.name), 'X-Collection': encodeURIComponent($("collection").value), 'X-Job-Id': $("job").value,
    }});
    runId = response.id; lastHash = ""; selected.clear();
    await api(`/api/runs/${runId}/start`,{models:$("models").value,quantum:Number($("quantum").value),padding:Number($("padding").value),
      ...Object.fromEntries(['max-width','max-height','max-pages','max-page-pixels','max-total-pixels'].map(key => [key.replaceAll('-', '_'), Number($(key).value)]))});
    await refreshRuns(); await refresh();
    window.dispatchEvent(new Event('studio:workspace-changed'));
  } finally { $("start").disabled = false; }
}));
function ensureSavedStrokes() {
  if (strokes.length || currentStroke) throw new Error('Apply or undo mask strokes before opening another run.');
}
$('atlas-page').addEventListener('change', () => { if (snapshot) $('atlas').src = snapshot.artifactBase + $('atlas-page').value; });
async function openRun(id) {
  ensureSavedStrokes(); runId = id; lastHash = ''; selected.clear(); snapshot = null;
  sourceImage = null; pendingImage = null; $('review').hidden = true;
  await refreshRuns(); await refresh();
}
async function refreshJobs() {
  const records = await api('/api/handoffs'), selectedJob = $('job').value;
  $('job').replaceChildren(new Option('No linked job', ''), ...records.filter(record => !record.archived)
    .map(({job}) => new Option(`${job.workflowId} · ${job.jobId}`, job.jobId)));
  if ([...$('job').options].some(option => option.value === selectedJob)) $('job').value = selectedJob;
}
$('runs').addEventListener('change', action(async () => {
  const id = $('runs').value; $('runs').value = runId; await openRun(id);
}));
window.addEventListener('studio:open-run', action(async event => {
  ensureSavedStrokes(); document.querySelector('[data-view="process"]').click(); await openRun(event.detail);
}));
window.addEventListener('studio:before-workspace-change', event => { if (strokes.length || currentStroke) event.preventDefault(); });
window.addEventListener('studio:runs-changed', action(refreshRuns));
window.addEventListener('studio:handoffs-changed', action(refreshJobs));
$("resume").addEventListener("click",action(async()=>{await api(`/api/runs/${runId}/start`,{});await refresh();}));
$("cancel").addEventListener("click",action(async()=>{await api(`/api/runs/${runId}/cancel`,{});await refresh();}));
for (const id of ["bg","zoom","overlay"]) $(id).addEventListener("change", draw);
$("doubts").addEventListener("change",renderItems);
for (const [id,kind] of [["merge","merge"],["approve","approve"],["discard","discard"]]) {
  $(id).addEventListener("click",action(async()=>{
    if (!selected.size || (kind === "merge" && selected.size<2)) throw new Error(kind === "merge" ? "Select at least two sprites" : "Select a sprite first");
    if (strokes.length) throw new Error("Apply or undo the current strokes first");
    await review([{kind,itemIds:[...selected]}]);
  }));
}
$("save-tags").addEventListener("click",action(async()=>{
  if (!selected.size) throw new Error("Select a sprite first");
  await review([{kind:"tags",itemIds:[...selected],classification:{family:$("family").value,canonicalType:$("type").value,tags:$("tags").value.split(",").map(s=>s.trim()).filter(Boolean)}}]);
}));
const canvas = $("canvas");
function point(event) {const box=canvas.getBoundingClientRect();return [Math.max(0,Math.min(canvas.width-1,Math.floor((event.clientX-box.left)*canvas.width/box.width))),Math.max(0,Math.min(canvas.height-1,Math.floor((event.clientY-box.top)*canvas.height/box.height)))];}
canvas.addEventListener("pointerdown",event=>{
  let target=$("paint").value;
  if (target === "off" || !sourceImage) return;
  if (target === "selected") {target=primary()?.id;if (!target) {$("status").textContent="Select a sprite first";return;}}
  currentStroke={kind:"paint",target,radius:Number($("radius").value),points:[point(event)]};
  canvas.setPointerCapture(event.pointerId);draw();
});
canvas.addEventListener("pointermove",event=>{if(currentStroke){currentStroke.points.push(point(event));draw();}});
canvas.addEventListener("pointerup",()=>{if(currentStroke){strokes.push(currentStroke);currentStroke=null;draw();}});
canvas.addEventListener("pointercancel",()=>{currentStroke=null;draw();});
$("undo").addEventListener("click",()=>{strokes.pop();draw();});
$("apply").addEventListener("click",action(async()=>{
  await review(strokes);
}));
for (const [id,draft] of [["export",false],["draft",true]]) $(id).addEventListener("click",action(async()=>{
  const record = await api(`/api/runs/${runId}/delivery`, {draft});
  const link = document.createElement('a'); link.href = `/api/exports/${record.id}`;
  link.download = `sprites-${runId}${draft ? '-draft' : ''}.zip`; link.click();
  $('status').textContent = `Saved ${record.path}`;
  window.dispatchEvent(new Event('studio:workspace-changed'));
}));
await action(async()=>{
  const current = await session();
  $("runtime").textContent=current.modelProfiles.length ? `Offline checkpoints ready: ${current.modelProfiles.join(", ")}` : "Saved results and alpha processing are available. Prepare checkpoints to use models.";
  for(const option of $("models").options) option.disabled=option.value!=="none"&&!current.modelProfiles.includes(option.value);
  if(!current.modelProfiles.includes("standard")) $("models").value=current.modelProfiles[0]||"none";
  $("status").textContent="Ready. Import a sheet or resume saved work.";await refreshRuns(); await refreshJobs();
})();
setInterval(()=>action(refresh)(),2000);
