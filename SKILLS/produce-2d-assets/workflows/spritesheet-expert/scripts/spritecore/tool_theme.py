"""Shared visual system for the skill's self-contained review tools.

Emitters inline ``TOOL_CSS`` (and ``THEME_SCRIPT`` when the page offers a theme
toggle) at build time. Pages stay single-file and never link remote assets.
"""

from __future__ import annotations

TOOL_CSS = """
:root {
  color-scheme: dark;
  --bg:#111; --surface:#181818; --raised:#202020; --sunken:#0b0b0b;
  --line:#303030; --line-strong:#474747; --ink:#ebebeb; --muted:#9a9a9a; --faint:#6c6c6c;
  --accent:#d4d4d4; --accent-ink:#111; --accent-soft:#ffffff14;
  --ok:#5fbf83; --warn:#e2b443; --bad:#ef6a5f;
  --checker-a:#2a2a2a; --checker-b:#363636; --checker-size:16px;
  --matte-black:#000; --matte-gray:#808080; --matte-white:#fff;
  --scroll-track:var(--sunken);
  --radius:4px; --radius-lg:6px;
  --font-ui:ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-mono:ui-monospace, "SF Mono", "Cascadia Mono", Consolas, monospace;
}
:root[data-theme="light"] {
  color-scheme: light;
  --bg:#f4f4f4; --surface:#fbfbfb; --raised:#ffffff; --sunken:#e8e8e8;
  --line:#d9d9d9; --line-strong:#b9b9b9; --ink:#1b1b1b; --muted:#5e5e5e; --faint:#8b8b8b;
  --accent:#444; --accent-ink:#ffffff; --accent-soft:#00000014;
  --ok:#23824a; --warn:#9a6a00; --bad:#c2392f;
  --checker-a:#dcdcdc; --checker-b:#f2f2f2;
}
@media (prefers-color-scheme: light) {
  :root:not([data-theme="dark"]) {
    color-scheme: light;
    --bg:#f4f4f4; --surface:#fbfbfb; --raised:#ffffff; --sunken:#e8e8e8;
    --line:#d9d9d9; --line-strong:#b9b9b9; --ink:#1b1b1b; --muted:#5e5e5e; --faint:#8b8b8b;
    --accent:#444; --accent-ink:#ffffff; --accent-soft:#00000014;
    --ok:#23824a; --warn:#9a6a00; --bad:#c2392f;
    --checker-a:#dcdcdc; --checker-b:#f2f2f2;
  }
}
* { box-sizing:border-box; scrollbar-width:thin; scrollbar-color:var(--line) var(--scroll-track); }
*::-webkit-scrollbar { width:10px; height:10px; }
*::-webkit-scrollbar-track { background:var(--scroll-track); }
*::-webkit-scrollbar-thumb { background:var(--line); border:2px solid var(--scroll-track); border-radius:999px; }
html, body { margin:0; background:var(--bg); color:var(--ink); }
body { min-width:320px; font:13px/1.45 var(--font-ui); -webkit-font-smoothing:antialiased; }
h1, h2, h3, p { margin:0; }
button, select, input { font:inherit; color:inherit; }
:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
.num, output, kbd { font-family:var(--font-mono); font-variant-numeric:tabular-nums; }
.sr-only { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); white-space:nowrap; }

/* Shell */
.tool { min-height:100vh; display:grid; grid-template-columns:minmax(0,1fr); grid-template-rows:auto 1fr; }
.tool-header { display:flex; align-items:center; gap:16px; min-height:48px; padding:0 16px; border-bottom:1px solid var(--line); background:var(--surface); }
.brand { display:flex; align-items:baseline; gap:10px; min-width:0; }
.brand-mark { color:var(--muted); font:600 11px/1 var(--font-mono); letter-spacing:.08em; text-transform:uppercase; white-space:nowrap; }
.brand h1 { font-size:15px; font-weight:600; letter-spacing:-.01em; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.status { min-width:0; margin-left:auto; color:var(--muted); font-family:var(--font-mono); font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }

/* Controls */
.btn, select { min-height:32px; padding:0 10px; border:1px solid var(--line); border-radius:var(--radius); background:var(--raised); color:var(--ink); cursor:pointer; }
.btn:hover, select:hover { border-color:var(--line-strong); }
.btn[aria-pressed="true"] { background:var(--accent); border-color:var(--accent); color:var(--accent-ink); }
.btn-icon { min-width:32px; padding:0; display:inline-grid; place-items:center; }
.btn-primary { min-width:72px; font-weight:600; }
.btn:disabled { opacity:.45; cursor:not-allowed; }
select { padding-right:24px; }
.field { display:inline-flex; align-items:center; gap:6px; color:var(--muted); font-size:12px; }
.toolbar { display:flex; flex-wrap:wrap; align-items:center; gap:8px 14px; }
.group { display:inline-flex; align-items:center; gap:4px; }
.seg { display:inline-flex; border:1px solid var(--line); border-radius:var(--radius); overflow:hidden; }
.seg .btn { border:0; border-radius:0; min-height:30px; }
.seg .btn + .btn { border-left:1px solid var(--line); }
.swatch { display:inline-block; width:10px; height:10px; margin-right:6px; border:1px solid var(--line-strong); border-radius:2px; vertical-align:-1px; }
.swatch[data-swatch="checker"] { background:conic-gradient(var(--checker-a) 25%, var(--checker-b) 0 50%, var(--checker-a) 0 75%, var(--checker-b) 0) 0 0/6px 6px; }
.swatch[data-swatch="black"] { background:var(--matte-black); }
.swatch[data-swatch="gray"] { background:var(--matte-gray); }
.swatch[data-swatch="white"] { background:var(--matte-white); }

/* Stage: the artifact owns the space */
.stage { position:relative; min-height:320px; overflow:auto; display:grid; place-items:center; border:1px solid var(--line); border-radius:var(--radius-lg); background-color:var(--checker-a); }
.stage[data-background="checker"] { background-image:conic-gradient(var(--checker-a) 25%, var(--checker-b) 0 50%, var(--checker-a) 0 75%, var(--checker-b) 0); background-size:var(--checker-size) var(--checker-size); }
.stage[data-background="black"] { background:var(--matte-black); }
.stage[data-background="gray"] { background:var(--matte-gray); }
.stage[data-background="white"] { background:var(--matte-white); }
.stage:focus-visible { outline:2px solid var(--accent); outline-offset:-2px; }
canvas[data-sampling="nearest"] { image-rendering:pixelated; image-rendering:crisp-edges; }
canvas[data-sampling="linear"] { image-rendering:auto; }

/* Transport and timeline */
.transport { display:grid; grid-template-columns:auto minmax(120px,1fr) auto; align-items:center; gap:10px; }
.scrub { width:100%; accent-color:var(--accent); }
.readout { min-width:64px; color:var(--muted); text-align:right; font-size:12px; }
.filmstrip { display:flex; gap:6px; overflow-x:auto; padding:2px 2px 6px; scroll-snap-type:x proximity; }
.film-frame { flex:0 0 auto; display:grid; gap:4px; padding:4px; min-width:56px; border:1px solid var(--line); border-radius:var(--radius); background:var(--surface); color:var(--muted); cursor:pointer; scroll-snap-align:start; font:11px/1 var(--font-mono); }
.film-frame canvas { display:block; width:48px; height:48px; margin:0 auto; object-fit:contain; background:conic-gradient(var(--checker-a) 25%, var(--checker-b) 0 50%, var(--checker-a) 0 75%, var(--checker-b) 0) 0 0/8px 8px; }
.film-frame .bar { display:block; height:3px; border-radius:2px; background:var(--line-strong); }
.film-frame:hover { border-color:var(--line-strong); color:var(--ink); }
.film-frame[aria-current="true"] { border-color:var(--accent); color:var(--ink); box-shadow:inset 0 0 0 1px var(--accent); }
.film-frame[aria-current="true"] .bar { background:var(--accent); }

/* Rails and lists */
.rail { min-width:0; border-left:1px solid var(--line); background:var(--surface); overflow:auto; }
.rail-section { padding:14px 16px; border-bottom:1px solid var(--line); }
.rail-title { margin:0 0 8px; color:var(--muted); font:600 11px/1.2 var(--font-mono); letter-spacing:.08em; text-transform:uppercase; }
.list { list-style:none; margin:0; padding:0; }
.list-row { display:flex; align-items:center; justify-content:space-between; gap:8px; width:100%; min-height:32px; padding:6px 8px; border:0; border-radius:var(--radius); background:none; color:var(--ink); text-align:left; text-decoration:none; cursor:pointer; }
.list-row:hover { background:var(--raised); }
.list-row[aria-pressed="true"] { background:var(--accent-soft); box-shadow:inset 2px 0 0 var(--accent); }
.list-row .meta { color:var(--muted); font:12px var(--font-mono); font-variant-numeric:tabular-nums; white-space:nowrap; }
.facts { display:grid; grid-template-columns:auto 1fr; gap:4px 12px; margin:0; font-size:12px; }
.facts dt { color:var(--muted); }
.facts dd { margin:0; font-family:var(--font-mono); font-variant-numeric:tabular-nums; text-align:right; }
.empty { color:var(--muted); font-style:italic; padding:6px 8px; }

/* Review decisions */
.chip { display:inline-flex; align-items:center; gap:5px; height:20px; padding:0 7px; border:1px solid var(--line); border-radius:999px; font:600 11px/1 var(--font-mono); color:var(--muted); }
.chip::before { content:""; width:6px; height:6px; border-radius:50%; background:currentColor; }
.chip[data-status="approved"], .chip[data-status="pass"] { color:var(--ok); border-color:currentColor; }
.chip[data-status="rejected"], .chip[data-status="fail"] { color:var(--bad); border-color:currentColor; }
.chip[data-status="pending"], .chip[data-status="warn"] { color:var(--warn); border-color:currentColor; }
.chip[data-status="missing"] { color:var(--faint); border-style:dashed; }
.chip[data-status="missing"]::before { background:none; border:1px solid currentColor; }
.list-row[aria-disabled="true"] { cursor:default; color:var(--muted); }
.list-row[aria-disabled="true"]:hover { background:none; }
.card { border:1px solid var(--line); border-radius:var(--radius-lg); background:var(--surface); }
kbd { display:inline-block; min-width:20px; padding:1px 5px; border:1px solid var(--line-strong); border-bottom-width:2px; border-radius:3px; color:var(--ink); font-size:11px; text-align:center; }
.keys { display:grid; grid-template-columns:auto 1fr; gap:6px 10px; align-items:center; margin:0; color:var(--muted); font-size:12px; }
.keys dd { margin:0; }

@media (prefers-reduced-motion:reduce) { * { scroll-behavior:auto !important; transition:none !important; animation:none !important; } }
"""

THEME_SCRIPT = """
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
"""

__all__ = ["THEME_SCRIPT", "TOOL_CSS"]
