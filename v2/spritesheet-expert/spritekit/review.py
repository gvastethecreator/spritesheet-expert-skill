"""review.html: one self-contained review page per run. No network, no server."""

from __future__ import annotations

import base64
import html
import io
import json
from pathlib import Path

from PIL import Image

SOURCE_PREVIEW_WIDTH = 960


def data_uri(img: Image.Image, fmt: str = "PNG") -> str:
    buf = io.BytesIO()
    img.save(buf, fmt, **({"quality": 85} if fmt == "WEBP" else {}))
    return f"data:image/{fmt.lower()};base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def payload(run_dir: Path, run: dict) -> dict:
    build = run["build"]
    states = []
    for st in run["states"]:
        if st["name"] not in build["states"]:
            continue
        src = Image.open(run_dir / run["sources"][st["name"]]["file"]).convert("RGBA")
        if src.width > SOURCE_PREVIEW_WIDTH:
            src = src.resize((SOURCE_PREVIEW_WIDTH, round(src.height * SOURCE_PREVIEW_WIDTH / src.width)), Image.Resampling.LANCZOS)
        states.append({
            "name": st["name"], "motion": st["motion"], "fps": st["fps"], "loop": st["loop"],
            "slots": st["motion"] in ("slots", "atlas"), "fit": "packed" if st["motion"] == "atlas" else st["ground"],
            "phases": [p["label"] for p in st["phases"]],
            "frames": build["atlas"]["states"][st["name"]]["frames"],
            "checks": build["states"][st["name"]]["checks"],
            "cutout": build["states"][st["name"]]["cutout"]["method"],
            "scale": build["states"][st["name"]]["scale"],
            "source": data_uri(src, "WEBP"),
            "provenance": run["sources"][st["name"]],
        })
    return {
        "subject": run["subject"], "lane": run["lane"], "cell": run["cell"],
        "pivot": build["atlas"]["pivot"], "built": build["time"], "states": states,
        "atlas": data_uri(Image.open(run_dir / "atlas.png")),
    }


def write(run_dir: Path, run: dict) -> Path:
    data = json.dumps(payload(run_dir, run)).replace("</", "<\\/")
    page = PAGE.replace("__TITLE__", html.escape(run_dir.resolve().name)).replace("__DATA__", data)
    out = run_dir / "review.html"
    out.write_text(page, encoding="utf-8")
    return out


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark light">
<title>Review · __TITLE__</title>
<style>
:root { color-scheme: dark;
  --bg:#111211; --panel:#181918; --raised:#212220; --line:#30322f; --line2:#474a45;
  --ink:#ebebe6; --muted:#9a9c94; --accent:#7aa2ff; --accent-ink:#0b1430; --soft:#7aa2ff26;
  --ok:#5fbf83; --warn:#e2b443; --bad:#ef6a5f; --ck1:#2a2b29; --ck2:#363834;
  --mono:ui-monospace,"Cascadia Mono",Consolas,monospace; --sans:ui-sans-serif,system-ui,"Segoe UI",sans-serif; }
@media (prefers-color-scheme: light) { :root:not([data-theme=dark]) { color-scheme: light;
  --bg:#f4f4f1; --panel:#fbfbf9; --raised:#fff; --line:#d9d9d2; --line2:#b9b9b0; --ink:#1b1c1a; --muted:#5e605a;
  --accent:#2f5bd3; --accent-ink:#fff; --soft:#2f5bd31f; --ok:#23824a; --warn:#9a6a00; --bad:#c2392f; --ck1:#dcdcd6; --ck2:#f2f2ee; } }
:root[data-theme=light] { color-scheme: light;
  --bg:#f4f4f1; --panel:#fbfbf9; --raised:#fff; --line:#d9d9d2; --line2:#b9b9b0; --ink:#1b1c1a; --muted:#5e605a;
  --accent:#2f5bd3; --accent-ink:#fff; --soft:#2f5bd31f; --ok:#23824a; --warn:#9a6a00; --bad:#c2392f; --ck1:#dcdcd6; --ck2:#f2f2ee; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:13px/1.45 var(--sans); }
button, select, input { font:inherit; color:inherit; }
:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
header { display:flex; align-items:center; gap:14px; min-height:48px; padding:0 16px; border-bottom:1px solid var(--line); background:var(--panel); }
header .kind { color:var(--muted); font:600 11px var(--mono); letter-spacing:.08em; text-transform:uppercase; }
header h1 { margin:0; font-size:15px; font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
#status { margin-left:auto; color:var(--muted); font:12px var(--mono); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.layout { display:grid; grid-template-columns:200px minmax(0,1fr) 320px; min-height:calc(100vh - 48px); }
aside, .rail { background:var(--panel); min-width:0; }
aside { border-right:1px solid var(--line); padding:12px 8px; }
.rail { border-left:1px solid var(--line); overflow:auto; }
.title { margin:0 0 8px; color:var(--muted); font:600 11px var(--mono); letter-spacing:.08em; text-transform:uppercase; }
.row { display:flex; justify-content:space-between; align-items:center; gap:8px; width:100%; min-height:34px; padding:6px 8px; border:0; border-radius:4px; background:none; text-align:left; cursor:pointer; }
.row:hover { background:var(--raised); }
.row[aria-pressed=true] { background:var(--soft); box-shadow:inset 2px 0 0 var(--accent); }
.meta { color:var(--muted); font:12px var(--mono); }
main { display:grid; align-content:start; gap:10px; padding:12px; min-width:0; }
.stage { display:grid; place-items:center; height:clamp(300px, calc(100vh - 290px), 760px); overflow:auto; border:1px solid var(--line); border-radius:6px; }
.stage[data-bg=checker] { background:conic-gradient(var(--ck1) 25%,var(--ck2) 0 50%,var(--ck1) 0 75%,var(--ck2) 0) 0 0/16px 16px; }
.stage[data-bg=black] { background:#000; } .stage[data-bg=gray] { background:#808080; } .stage[data-bg=white] { background:#fff; }
.stage canvas, .stage img { max-width:100%; }
.bar { display:flex; flex-wrap:wrap; align-items:center; gap:8px 14px; }
.transport { display:grid; grid-template-columns:auto minmax(80px,1fr) auto; gap:10px; align-items:center; }
.btn, select { min-height:32px; padding:0 10px; border:1px solid var(--line); border-radius:4px; background:var(--raised); cursor:pointer; }
.btn:hover { border-color:var(--line2); }
.btn[aria-pressed=true] { background:var(--accent); border-color:var(--accent); color:var(--accent-ink); }
.seg { display:inline-flex; border:1px solid var(--line); border-radius:4px; overflow:hidden; }
.seg .btn { border:0; border-radius:0; }
.seg .btn + .btn { border-left:1px solid var(--line); }
input[type=range] { width:100%; accent-color:var(--accent); }
output { color:var(--muted); font:12px var(--mono); white-space:nowrap; }
.film { display:flex; gap:6px; overflow-x:auto; padding-bottom:4px; }
.film button { flex:0 0 auto; display:grid; gap:3px; padding:4px; border:1px solid var(--line); border-radius:4px; background:var(--panel); color:var(--muted); font:11px var(--mono); cursor:pointer; }
.film button[aria-current=true] { border-color:var(--accent); color:var(--ink); box-shadow:inset 0 0 0 1px var(--accent); }
.film button.flag { border-color:var(--warn); }
.film canvas { width:64px; height:64px; background:conic-gradient(var(--ck1) 25%,var(--ck2) 0 50%,var(--ck1) 0 75%,var(--ck2) 0) 0 0/8px 8px; }
section { padding:14px 16px; border-bottom:1px solid var(--line); }
.check { display:grid; grid-template-columns:auto 1fr; gap:4px 10px; padding:8px 0; border-top:1px solid var(--line); }
.check:first-of-type { border-top:0; }
.check p { margin:0; color:var(--muted); grid-column:2; }
.check button { grid-column:2; justify-self:start; padding:0; border:0; background:none; color:var(--accent); cursor:pointer; text-decoration:underline; }
.chip { display:inline-flex; align-items:center; gap:5px; height:20px; padding:0 7px; border:1px solid currentColor; border-radius:999px; font:600 11px var(--mono); }
.chip::before { content:""; width:6px; height:6px; border-radius:50%; background:currentColor; }
.chip[data-s=pass] { color:var(--ok); } .chip[data-s=warn] { color:var(--warn); } .chip[data-s=fail] { color:var(--bad); }
dl { display:grid; grid-template-columns:auto 1fr; gap:4px 12px; margin:0; font-size:12px; }
dt { color:var(--muted); } dd { margin:0; font-family:var(--mono); text-align:right; overflow-wrap:anywhere; }
kbd { padding:1px 5px; border:1px solid var(--line2); border-bottom-width:2px; border-radius:3px; font:11px var(--mono); }
@media (max-width:980px) { .layout { grid-template-columns:minmax(0,1fr); } aside { border-right:0; border-bottom:1px solid var(--line); }
  aside .list { display:flex; gap:4px; overflow-x:auto; } .rail { border-left:0; border-top:1px solid var(--line); } }
@media (prefers-reduced-motion:reduce) { * { transition:none !important; } }
</style>
</head>
<body>
<header>
  <span class="kind">Sprite review</span>
  <h1>__TITLE__</h1>
  <span id="status" aria-live="polite"></span>
  <button class="btn" id="theme" type="button" aria-label="Switch theme">◐</button>
</header>
<div class="layout">
  <aside aria-label="States and sets"><p class="title">Rows</p><div class="list" id="states"></div></aside>
  <main>
    <div class="stage" id="stage" data-bg="checker" tabindex="0" aria-label="Frame preview. Space plays, arrows step, O toggles onion skin, B changes background.">
      <canvas id="canvas" aria-label="Animation frame"></canvas>
      <img id="source" alt="Source sheet" hidden>
    </div>
    <div class="transport">
      <div class="bar">
        <button class="btn" id="prev" type="button" aria-label="Previous frame">◀</button>
        <button class="btn" id="play" type="button" aria-label="Play animation">Play</button>
        <button class="btn" id="next" type="button" aria-label="Next frame">▶</button>
      </div>
      <input id="scrub" type="range" min="0" value="0" aria-label="Frame">
      <output id="readout">1 / 1</output>
    </div>
    <div class="bar">
      <div class="seg" role="group" aria-label="View">
        <button class="btn" type="button" data-view="frames" aria-pressed="true">Frames</button>
        <button class="btn" type="button" data-view="source" aria-pressed="false">Source</button>
      </div>
      <button class="btn" id="onion" type="button" aria-pressed="false">Onion skin</button>
      <button class="btn" id="guides" type="button" aria-pressed="true">Pivot</button>
      <button class="btn" id="stretch" type="button" aria-pressed="false" hidden>Stretch</button>
      <div class="seg" role="group" aria-label="Background">
        <button class="btn" type="button" data-bg="checker" aria-pressed="true">Checker</button>
        <button class="btn" type="button" data-bg="black" aria-pressed="false">Black</button>
        <button class="btn" type="button" data-bg="gray" aria-pressed="false">Gray</button>
        <button class="btn" type="button" data-bg="white" aria-pressed="false">White</button>
      </div>
      <label class="meta">Zoom <select id="zoom"><option value="fit">Fit</option><option>1</option><option>2</option><option>3</option></select></label>
    </div>
    <div class="film" id="film" aria-label="Frames"></div>
  </main>
  <div class="rail">
    <section><p class="title">Checks</p><div id="checks"></div></section>
    <section><p class="title">State</p><dl id="facts"></dl></section>
    <section><p class="title">Source</p><dl id="prov"></dl></section>
    <section><p class="title">Keys</p><dl>
      <dt><kbd>Space</kbd></dt><dd>play or pause</dd><dt><kbd>←</kbd> <kbd>→</kbd></dt><dd>step frame</dd>
      <dt><kbd>↑</kbd> <kbd>↓</kbd></dt><dd>change state</dd><dt><kbd>O</kbd></dt><dd>onion skin</dd><dt><kbd>B</kbd></dt><dd>background</dd>
    </dl></section>
  </div>
</div>
<script type="application/json" id="data">__DATA__</script>
<script>
(() => {
  const D = JSON.parse(document.getElementById('data').textContent);
  const $ = (id) => document.getElementById(id);
  const [CW, CH] = D.cell;
  const atlas = new Image();
  const S = { st: 0, f: 0, playing: false, timer: 0, onion: false, guides: true, stretch: false, view: 'frames', bg: 'checker' };
  const canvas = $('canvas'), ctx = canvas.getContext('2d');
  const el = (tag, props = {}, text) => { const e = document.createElement(tag); Object.assign(e, props); if (text !== undefined) e.textContent = text; return e; };
  const cur = () => D.states[S.st];
  const pressed = (sel, attr, val) => document.querySelectorAll(sel).forEach((b) => b.setAttribute('aria-pressed', String(b.dataset[attr] === val)));

  function zoom() {
    const z = $('zoom').value;
    if (z !== 'fit') return Number(z);
    const box = $('stage');
    return Math.max(0.25, Math.min((box.clientWidth - 24) / CW, (box.clientHeight - 24) / CH, 3));
  }
  // Nine-slice proof: corners stay, edges and middle stretch to 2x width and 1.5x height.
  function drawNine(fr) {
    const [x0, y0, x1, y1] = fr.nine_slice.box, [l, t, r, b] = fr.nine_slice.slice;
    const sw = x1 - x0, sh = y1 - y0, W = Math.round(sw * 2), H = Math.round(sh * 1.5);
    canvas.width = W; canvas.height = H;
    canvas.style.width = `${Math.min(W * zoom(), $('stage').clientWidth - 24)}px`;
    const sx = [0, l, sw - r, sw], dx = [0, l, W - r, W], sy = [0, t, sh - b, sh], dy = [0, t, H - b, H];
    for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) {
      if (sx[i + 1] > sx[i] && sy[j + 1] > sy[j]) ctx.drawImage(atlas, fr.x + x0 + sx[i], fr.y + y0 + sy[j], sx[i + 1] - sx[i],
        sy[j + 1] - sy[j], dx[i], dy[j], dx[i + 1] - dx[i], dy[j + 1] - dy[j]);
    }
  }
  function draw() {
    const st = cur(), n = st.frames.length, fr = st.frames[S.f];
    const z = zoom();
    canvas.width = CW; canvas.height = CH;
    canvas.style.width = `${CW * z}px`;
    ctx.clearRect(0, 0, CW, CH);
    $('stretch').hidden = !fr.nine_slice;
    $('scrub').max = String(n - 1); $('scrub').value = String(S.f);
    $('readout').textContent = `${S.f + 1} / ${n}`;
    $('status').textContent = st.slots ? `${st.name} · ${fr.name}` : `${st.name} · ${S.f + 1} ${st.phases[S.f] || ''} · ${fr.duration_ms} ms`;
    document.querySelectorAll('#film button').forEach((b, i) => b.setAttribute('aria-current', String(i === S.f)));
    if (S.stretch && fr.nine_slice) { drawNine(fr); return; }
    if (S.onion && n > 1) {
      const p = st.frames[(S.f - 1 + n) % n];
      ctx.globalAlpha = 0.35; ctx.drawImage(atlas, p.x, p.y, p.w, p.h, (CW - p.w) / 2, (CH - p.h) / 2, p.w, p.h); ctx.globalAlpha = 1;
    }
    ctx.drawImage(atlas, fr.x, fr.y, fr.w, fr.h, (CW - fr.w) / 2, (CH - fr.h) / 2, fr.w, fr.h);
    if (S.guides) {
      ctx.strokeStyle = 'rgba(239,106,95,.85)'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(0, D.pivot[1] + .5); ctx.lineTo(CW, D.pivot[1] + .5);
      ctx.moveTo(D.pivot[0] + .5, D.pivot[1] - 8); ctx.lineTo(D.pivot[0] + .5, D.pivot[1] + 8); ctx.stroke();
    }
  }
  function setView(v) {
    S.view = v; pressed('[data-view]', 'view', v);
    canvas.hidden = v !== 'frames'; $('source').hidden = v !== 'source';
    if (v === 'source') { stop(); $('source').src = cur().source; }
    else draw();
  }
  function stop() { S.playing = false; clearTimeout(S.timer); $('play').textContent = 'Play'; $('play').setAttribute('aria-label', 'Play animation'); }
  function play() {
    stop(); if (cur().frames.length < 2 || cur().slots) return;
    S.playing = true; $('play').textContent = 'Pause'; $('play').setAttribute('aria-label', 'Pause animation');
    const tick = () => { S.timer = setTimeout(() => { S.f = (S.f + 1) % cur().frames.length; draw(); tick(); }, cur().frames[S.f].duration_ms); };
    tick();
  }
  function go(i) { stop(); const n = cur().frames.length; S.f = (i + n) % n; if (S.view !== 'frames') setView('frames'); else draw(); }

  function renderState() {
    const st = cur();
    document.querySelectorAll('#states .row').forEach((b, i) => b.setAttribute('aria-pressed', String(i === S.st)));
    const flagged = new Set(st.checks.filter((c) => c.status !== 'pass').flatMap((c) => c.frames));
    $('film').replaceChildren(...st.frames.map((fr, i) => {
      const b = el('button', { type: 'button', title: st.phases[i] || '' });
      if (flagged.has(i + 1)) b.className = 'flag';
      const c = el('canvas'); c.width = CW; c.height = CH;
      c.getContext('2d').drawImage(atlas, fr.x, fr.y, fr.w, fr.h, (CW - fr.w) / 2, (CH - fr.h) / 2, fr.w, fr.h);
      b.append(c, el('span', {}, st.slots ? fr.name : `${String(i + 1).padStart(2, '0')}`));
      b.addEventListener('click', () => go(i));
      return b;
    }));
    $('checks').replaceChildren(...st.checks.map((c) => {
      const d = el('div', { className: 'check' });
      const chip = el('span', { className: 'chip' }, c.status); chip.dataset.s = c.status;
      d.append(chip, el('strong', {}, c.id), el('p', {}, c.detail));
      if (c.frames.length) { const b = el('button', { type: 'button' }, `Show frame ${c.frames[0]}`); b.addEventListener('click', () => go(c.frames[0] - 1)); d.append(b); }
      return d;
    }));
    const facts = [...(st.slots ? [['Fit', st.fit], ['Slots', st.frames.length]]
      : [['Motion', st.motion], ['Frames', st.frames.length], ['FPS', st.fps], ['Loop', st.loop ? 'yes' : 'no']]),
      ['Cell', `${CW} × ${CH}`], ['Pivot', D.pivot.join(', ')], ['Cutout', st.cutout], ['Scale', st.scale || 'per slot']];
    $('play').disabled = st.slots;
    $('facts').replaceChildren(...facts.flatMap(([k, v]) => [el('dt', {}, k), el('dd', {}, String(v))]));
    const p = st.provenance;
    $('prov').replaceChildren(...[['File', p.file], ['SHA-256', p.sha256.slice(0, 16) + '…'], ['Provider', p.provider || 'not stated'], ['Ingested', p.ingested]]
      .flatMap(([k, v]) => [el('dt', {}, k), el('dd', {}, v)]));
    S.f = 0; setView(S.view);
    if (!matchMedia('(prefers-reduced-motion: reduce)').matches && S.view === 'frames') play();
  }

  $('states').replaceChildren(...D.states.map((st, i) => {
    const fails = st.checks.filter((c) => c.status !== 'pass').length;
    const b = el('button', { type: 'button', className: 'row' });
    b.append(el('span', {}, st.name), el('span', { className: 'meta' }, fails ? `${fails} to review` : `${st.frames.length} ${st.slots ? 'slots' : 'fr'}`));
    b.addEventListener('click', () => { stop(); S.st = i; renderState(); });
    return b;
  }));
  $('play').addEventListener('click', () => (S.playing ? stop() : play()));
  $('prev').addEventListener('click', () => go(S.f - 1));
  $('next').addEventListener('click', () => go(S.f + 1));
  $('scrub').addEventListener('input', (e) => go(Number(e.target.value)));
  $('zoom').addEventListener('change', draw);
  $('onion').addEventListener('click', () => { S.onion = !S.onion; $('onion').setAttribute('aria-pressed', String(S.onion)); draw(); });
  $('guides').addEventListener('click', () => { S.guides = !S.guides; $('guides').setAttribute('aria-pressed', String(S.guides)); draw(); });
  $('stretch').addEventListener('click', () => { S.stretch = !S.stretch; $('stretch').setAttribute('aria-pressed', String(S.stretch)); draw(); });
  document.querySelectorAll('[data-view]').forEach((b) => b.addEventListener('click', () => setView(b.dataset.view)));
  const setBg = (bg) => { S.bg = bg; $('stage').dataset.bg = bg; pressed('[data-bg]', 'bg', bg); };
  document.querySelectorAll('[data-bg]').forEach((b) => b.addEventListener('click', () => setBg(b.dataset.bg)));
  $('theme').addEventListener('click', () => {
    const dark = (document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark')) === 'dark';
    document.documentElement.dataset.theme = dark ? 'light' : 'dark';
  });
  document.addEventListener('keydown', (e) => {
    if (e.target.matches('input, select')) return;
    if (e.key === ' ') { e.preventDefault(); S.playing ? stop() : play(); }
    else if (e.key === 'ArrowRight') go(S.f + 1);
    else if (e.key === 'ArrowLeft') go(S.f - 1);
    else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); stop(); S.st = (S.st + (e.key === 'ArrowDown' ? 1 : -1) + D.states.length) % D.states.length; renderState(); }
    else if (e.key.toLowerCase() === 'o') $('onion').click();
    else if (e.key.toLowerCase() === 'b') { const o = ['checker', 'black', 'gray', 'white']; setBg(o[(o.indexOf(S.bg) + 1) % 4]); }
  });
  addEventListener('resize', draw);
  atlas.onload = renderState;
  atlas.src = D.atlas;
})();
</script>
</body>
</html>
"""
