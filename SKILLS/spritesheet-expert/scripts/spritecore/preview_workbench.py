"""Build a portable, manifest-driven animation review workbench."""

from __future__ import annotations

from base64 import b64encode
from hashlib import sha256
import html
import json
from pathlib import Path, PurePosixPath
import posixpath
from typing import Any, Mapping

from PIL import Image

from spritecore.contracts import load_manifest
from spritecore.paths import PathSafetyError, resolve_run_path


class PreviewWorkbenchError(ValueError):
    """Raised before mutation when the workbench cannot be built honestly."""


DEFAULT_OUTPUT = "qa/preview-workbench/index.html"
DEFAULT_REPORT = "qa/preview-workbench/workbench.evidence.json"
KNOWN_EVIDENCE = (
    ("Generation provenance", "qa/generation-provenance-report.json"),
    ("Background matte", "qa/background-matte-review.png"),
    ("All-frame contact sheet", "qa/all-contact.png"),
    ("Alignment report", "qa/frame-alignment-report.json"),
    ("Identity report", "qa/identity-consistency-report.json"),
    ("Animation contract", "qa/animation-contract-report.json"),
    ("Run validation", "qa/run-validation-report.json"),
)


def _digest(content: bytes) -> str:
    return sha256(content).hexdigest()


def _portable_output(run_dir: Path, value: str, suffix: str) -> Path:
    if "\\" in value or not value.startswith("qa/preview-workbench/"):
        raise PreviewWorkbenchError(
            "preview workbench outputs must use portable paths under qa/preview-workbench/"
        )
    try:
        output = resolve_run_path(run_dir, value)
    except PathSafetyError as exc:
        raise PreviewWorkbenchError(str(exc)) from exc
    if output.suffix.lower() != suffix:
        raise PreviewWorkbenchError(f"preview workbench output must use {suffix}")
    return output


def _durations(manifest: Mapping[str, Any], state: str, count: int) -> list[int]:
    animation = manifest.get("animation")
    row: Mapping[str, Any] = {}
    if isinstance(animation, Mapping):
        rows = animation.get("rows")
        if isinstance(rows, Mapping) and isinstance(rows.get(state), Mapping):
            row = rows[state]
    explicit = row.get("durations_ms")
    if (
        isinstance(explicit, list)
        and len(explicit) == count
        and all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in explicit)
    ):
        return list(explicit)
    fps = row.get("fps", 8)
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or fps <= 0:
        raise PreviewWorkbenchError(f"animation row {state!r} has invalid fps")
    return [max(1, round(1000 / fps))] * count


def _relative_href(output_path: Path, target: Path) -> str:
    relative = posixpath.relpath(
        target.as_posix(),
        start=output_path.parent.as_posix(),
    )
    return str(PurePosixPath(relative))


def _source_record(run_dir: Path, path: Path, role: str) -> dict[str, Any]:
    content = path.read_bytes()
    return {
        "role": role,
        "path": path.relative_to(run_dir).as_posix(),
        "sha256": _digest(content),
        "size_bytes": len(content),
    }


def _initial_zoom(states: Mapping[str, Any]) -> int:
    largest = max(
        max(int(rect["w"]), int(rect["h"]))
        for state in states.values()
        for rect in state["frames"]
    )
    if largest <= 32:
        return 8
    if largest <= 96:
        return 4
    if largest <= 256:
        return 2
    return 1


def prepare_workbench(
    *,
    run_dir: Path,
    manifest_name: str = "manifest.json",
    output_name: str = DEFAULT_OUTPUT,
    report_name: str = DEFAULT_REPORT,
    force: bool = False,
) -> tuple[Path, Path, bytes, dict[str, Any]]:
    """Validate sources and return output bytes/report without mutating the run."""

    run_root = Path(run_dir).expanduser().resolve()
    if not run_root.is_dir():
        raise PreviewWorkbenchError(f"run directory does not exist: {run_root}")
    try:
        manifest_path = resolve_run_path(run_root, manifest_name)
    except PathSafetyError as exc:
        raise PreviewWorkbenchError(str(exc)) from exc
    if not manifest_path.is_file():
        raise PreviewWorkbenchError(f"manifest does not exist: {manifest_name}")
    try:
        manifest = load_manifest(manifest_path).data
    except ValueError as exc:
        raise PreviewWorkbenchError(str(exc)) from exc

    atlas_name = manifest["atlas"]["path"]
    try:
        atlas_path = resolve_run_path(run_root, atlas_name)
    except PathSafetyError as exc:
        raise PreviewWorkbenchError(str(exc)) from exc
    if not atlas_path.is_file() or atlas_path == manifest_path:
        raise PreviewWorkbenchError(f"atlas does not exist: {atlas_name}")
    try:
        with Image.open(atlas_path) as opened:
            opened.verify()
        with Image.open(atlas_path) as opened:
            actual_dimensions = opened.size
            image_format = (opened.format or "PNG").lower()
    except (OSError, ValueError) as exc:
        raise PreviewWorkbenchError(f"atlas is not a decodable image: {atlas_name}") from exc
    expected_dimensions = (manifest["atlas"]["width"], manifest["atlas"]["height"])
    if actual_dimensions != expected_dimensions:
        raise PreviewWorkbenchError(
            f"atlas dimensions {actual_dimensions} do not match manifest {expected_dimensions}"
        )

    output_path = _portable_output(run_root, output_name, ".html")
    report_path = _portable_output(run_root, report_name, ".json")
    if output_path == report_path or output_path in {atlas_path, manifest_path}:
        raise PreviewWorkbenchError("preview workbench outputs cannot overwrite sources")
    if not force:
        collisions = [path for path in (output_path, report_path) if path.exists()]
        if collisions:
            raise PreviewWorkbenchError(
                "preview workbench output already exists; pass --force to replace known outputs"
            )

    rows = manifest["frame_layout"]["rows"]
    state_names = list(rows)
    if not state_names:
        raise PreviewWorkbenchError("manifest contains no animation states")
    states: dict[str, Any] = {}
    for state in state_names:
        rects = rows[state]
        if not rects:
            raise PreviewWorkbenchError(f"manifest state {state!r} contains no frames")
        states[state] = {
            "frames": [dict(rect) for rect in rects],
            "durationsMs": _durations(manifest, state, len(rects)),
        }

    evidence: list[dict[str, str]] = []
    for label, relative in KNOWN_EVIDENCE:
        try:
            target = resolve_run_path(run_root, relative)
        except PathSafetyError:
            continue
        if target.is_file():
            evidence.append(
                {
                    "label": label,
                    "path": relative,
                    "href": _relative_href(output_path, target),
                }
            )
    for state in state_names:
        for label, relative in (
            (f"{state}: contact", f"qa/{state}-contact.png"),
            (f"{state}: onion", f"qa/{state}-onion.png"),
        ):
            try:
                target = resolve_run_path(run_root, relative)
            except PathSafetyError:
                continue
            if target.is_file():
                evidence.append(
                    {
                        "label": label,
                        "path": relative,
                        "href": _relative_href(output_path, target),
                    }
                )
    runtime_dir = run_root / "qa" / "runtime-preview"
    if runtime_dir.is_dir():
        for target in sorted(runtime_dir.glob("*.evidence.json")):
            evidence.append(
                {
                    "label": f"Runtime: {target.stem.removesuffix('.evidence')}",
                    "path": target.relative_to(run_root).as_posix(),
                    "href": _relative_href(output_path, target),
                }
            )

    atlas_bytes = atlas_path.read_bytes()
    mime = "image/png" if image_format == "png" else f"image/{image_format}"
    atlas_data_uri = f"data:{mime};base64,{b64encode(atlas_bytes).decode('ascii')}"
    preview_data = {
        "cell": dict(manifest["cell"]),
        "states": states,
        "evidence": evidence,
        "sampling": manifest["sampling_policy"]["filter"],
        "initialZoom": _initial_zoom(states),
    }
    html_bytes = _render_html(preview_data, atlas_data_uri).encode("utf-8")
    sources = [
        _source_record(run_root, atlas_path, "atlas"),
        _source_record(run_root, manifest_path, "manifest"),
    ]
    evidence_sources = []
    for entry in evidence:
        target = resolve_run_path(run_root, entry["path"])
        record = _source_record(run_root, target, "evidence")
        record["label"] = entry["label"]
        evidence_sources.append(record)
    fingerprint_payload = json.dumps(
        {"sources": sources, "evidence": evidence_sources},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    report = {
        "version": 1,
        "kind": "sprite-preview-workbench",
        "artifact": {
            "path": output_path.relative_to(run_root).as_posix(),
            "sha256": _digest(html_bytes),
            "size_bytes": len(html_bytes),
        },
        "states": state_names,
        "sources": sources,
        "evidence": evidence_sources,
        "evidence_links": evidence,
        "input_fingerprint": _digest(fingerprint_payload),
        "self_contained": True,
        "initial_zoom": preview_data["initialZoom"],
    }
    return output_path, report_path, html_bytes, report


def _render_html(data: Mapping[str, Any], atlas_data_uri: str) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    safe_atlas = html.escape(atlas_data_uri, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Sprite review workbench</title>
<style>
:root {{ color-scheme: dark; --ink:#f4f0e8; --muted:#a9a49b; --line:#393832; --panel:#171715; --accent:#ffbd59; --stage:#252522; }}
* {{ box-sizing:border-box; scrollbar-width:thin; scrollbar-color:var(--line) #0d0d0c; }}
*::-webkit-scrollbar {{ width:10px; height:10px; }}
*::-webkit-scrollbar-track {{ background:#0d0d0c; }}
*::-webkit-scrollbar-thumb {{ background:var(--line); border:2px solid #0d0d0c; border-radius:999px; }}
*::-webkit-scrollbar-thumb:hover {{ background:#57554c; }}
body {{ margin:0; min-width:320px; background:#0d0d0c; color:var(--ink); font:14px/1.45 ui-monospace, SFMono-Regular, Consolas, monospace; }}
button, select, input {{ font:inherit; }}
button, select {{ color:var(--ink); background:#22221f; border:1px solid var(--line); border-radius:5px; }}
button {{ min-height:36px; padding:7px 11px; cursor:pointer; }}
button:hover, button:focus-visible, select:focus-visible, input:focus-visible {{ border-color:var(--accent); outline:2px solid transparent; }}
button[aria-pressed="true"], .film-frame[aria-current="true"] {{ color:#15120d; background:var(--accent); border-color:var(--accent); }}
.shell {{ min-height:100vh; display:grid; grid-template-rows:auto 1fr; }}
header {{ display:flex; align-items:flex-end; justify-content:space-between; gap:24px; padding:22px 26px 18px; border-bottom:1px solid var(--line); }}
h1 {{ margin:0; font:600 clamp(20px, 3vw, 34px)/1.05 ui-sans-serif, system-ui, sans-serif; letter-spacing:-.035em; }}
.eyebrow {{ margin:0 0 6px; color:var(--accent); font-size:11px; letter-spacing:.14em; text-transform:uppercase; }}
.status {{ color:var(--muted); text-align:right; }}
main {{ display:grid; grid-template-columns:minmax(0, 1fr) 270px; min-height:0; }}
.artifact-column {{ min-width:0; padding:22px 26px 28px; }}
.stage {{ min-height:460px; display:grid; place-items:center; overflow:auto; border:1px solid var(--line); background-color:var(--stage); box-shadow:inset 0 0 0 1px #090908; }}
.stage:focus-visible {{ border-color:var(--accent); outline:2px solid var(--accent); outline-offset:2px; }}
.stage[data-background="checker"] {{ background-image:linear-gradient(45deg,#333 25%,transparent 25%),linear-gradient(-45deg,#333 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#333 75%),linear-gradient(-45deg,transparent 75%,#333 75%); background-position:0 0,0 8px,8px -8px,-8px 0; background-size:16px 16px; }}
.stage[data-background="black"] {{ background:#000; }}
.stage[data-background="gray"] {{ background:#808080; }}
.stage[data-background="white"] {{ background:#fff; }}
.canvas-wrap {{ padding:44px; display:grid; place-items:center; }}
canvas {{ box-shadow:0 8px 32px #0008; }}
canvas[data-sampling="nearest"] {{ image-rendering:pixelated; image-rendering:crisp-edges; }}
canvas[data-sampling="linear"] {{ image-rendering:auto; }}
.transport {{ display:grid; grid-template-columns:auto auto minmax(150px,1fr) auto; align-items:center; gap:10px; padding:12px 0; border-bottom:1px solid var(--line); }}
.transport-group, .backgrounds {{ display:flex; align-items:center; gap:6px; }}
.scrub {{ width:100%; accent-color:var(--accent); }}
.readout {{ min-width:76px; color:var(--muted); text-align:right; }}
.secondary-controls {{ display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:12px; padding:10px 0 16px; }}
.field {{ display:flex; align-items:center; gap:7px; color:var(--muted); }}
select {{ min-height:36px; padding:6px 30px 6px 9px; }}
.filmstrip {{ display:flex; gap:8px; padding:3px 0 10px; overflow-x:auto; scroll-snap-type:x proximity; }}
.film-frame {{ flex:0 0 auto; min-width:50px; scroll-snap-align:start; }}
.film-frame span {{ display:block; font-size:10px; opacity:.78; }}
aside {{ border-left:1px solid var(--line); padding:22px 20px; background:var(--panel); }}
aside h2 {{ margin:0 0 8px; font:600 15px/1.2 ui-sans-serif, system-ui, sans-serif; }}
.rail-copy {{ margin:0 0 18px; color:var(--muted); }}
.evidence-list {{ list-style:none; margin:0; padding:0; border-top:1px solid var(--line); }}
.evidence-list li {{ border-bottom:1px solid var(--line); }}
.evidence-list a {{ display:block; padding:12px 2px; color:var(--ink); text-decoration:none; }}
.evidence-list a:hover, .evidence-list a:focus-visible {{ color:var(--accent); }}
.empty {{ color:var(--muted); font-style:italic; }}
.atlas-source {{ display:none; }}
.shortcut {{ margin-top:24px; color:var(--muted); font-size:11px; }}
kbd {{ color:var(--ink); border:1px solid var(--line); border-bottom-width:2px; border-radius:3px; padding:1px 4px; }}
@media (max-width:800px) {{
  header {{ align-items:flex-start; padding:18px; }}
  .status {{ display:none; }}
  main {{ grid-template-columns:1fr; }}
  .artifact-column {{ padding:16px 14px 20px; }}
  .stage {{ min-height:390px; }}
  .canvas-wrap {{ padding:28px; }}
  .transport {{ grid-template-columns:auto minmax(120px,1fr) auto; }}
  .transport-group {{ grid-column:1; }}
  .scrub {{ grid-column:2; }}
  .readout {{ grid-column:3; }}
  aside {{ border-left:0; border-top:1px solid var(--line); padding:18px 16px 28px; }}
}}
@media (max-width:480px) {{
  .transport {{ grid-template-columns:auto 1fr; }}
  .transport > .transport-group {{ grid-column:1; grid-row:1; }}
  .readout {{ grid-column:2; grid-row:1; justify-self:end; }}
  .scrub {{ grid-column:1 / -1; grid-row:2; min-width:0; }}
  .secondary-controls > .transport-group {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); width:100%; gap:8px; }}
  .secondary-controls .field {{ min-width:0; flex-direction:column; align-items:stretch; gap:3px; }}
  .secondary-controls select {{ width:100%; min-width:0; padding-right:20px; }}
  .backgrounds {{ flex-wrap:wrap; }}
}}
@media (prefers-reduced-motion:reduce) {{ * {{ scroll-behavior:auto !important; }} }}
</style>
</head>
<body>
<div class="shell">
  <header>
    <div><p class="eyebrow">Runtime artifact review</p><h1>Sprite workbench</h1></div>
    <div class="status" id="status" aria-live="polite">Loading atlas…</div>
  </header>
  <main>
    <section class="artifact-column" aria-label="Animation review">
      <div class="stage" data-testid="preview-stage" data-background="checker" id="stage" tabindex="0" aria-label="Animation stage. Use Space to play or pause and arrow keys to step frames.">
        <div class="canvas-wrap"><canvas id="frame-canvas" role="img" aria-label="Current animation frame"></canvas></div>
      </div>
      <div class="transport" aria-label="Playback controls">
        <div class="transport-group">
          <button type="button" id="previous" aria-label="Previous frame">←</button>
          <button type="button" id="play" aria-label="Play animation" aria-pressed="false">Play</button>
          <button type="button" id="next" aria-label="Next frame">→</button>
        </div>
        <input class="scrub" id="scrub" aria-label="Animation frame" type="range" min="0" value="0" step="1">
        <output class="readout" id="readout" for="scrub">1 / 1</output>
      </div>
      <div class="secondary-controls">
        <div class="transport-group">
          <label class="field" for="state">State <select id="state"></select></label>
          <label class="field" for="speed">Speed <select id="speed"><option value="0.5">0.5×</option><option value="1" selected>1×</option><option value="2">2×</option></select></label>
          <label class="field" for="zoom">Zoom <select id="zoom"><option value="1">1×</option><option value="2">2×</option><option value="4">4×</option><option value="8">8×</option><option value="12">12×</option></select></label>
        </div>
        <div class="backgrounds" aria-label="Review background">
          <button type="button" data-background="checker" aria-pressed="true">Checker</button>
          <button type="button" data-background="black" aria-pressed="false">Black</button>
          <button type="button" data-background="gray" aria-pressed="false">Gray</button>
          <button type="button" data-background="white" aria-pressed="false">White</button>
        </div>
      </div>
      <div class="filmstrip" id="filmstrip" aria-label="All frames"></div>
    </section>
    <aside aria-label="Evidence">
      <h2>Evidence</h2>
      <p class="rail-copy">Open the current QA files without losing the frame under review.</p>
      <ul class="evidence-list" id="evidence"></ul>
      <p class="shortcut"><kbd>Space</kbd> play/pause · <kbd>←</kbd> <kbd>→</kbd> step · <kbd>Home</kbd> <kbd>End</kbd> jump</p>
    </aside>
  </main>
</div>
<img class="atlas-source" id="atlas-source" src="{safe_atlas}" alt="">
<script type="application/json" id="preview-data">{payload}</script>
<script>
(() => {{
  'use strict';
  const data = JSON.parse(document.getElementById('preview-data').textContent);
  const atlas = document.getElementById('atlas-source');
  const canvas = document.getElementById('frame-canvas');
  const context = canvas.getContext('2d', {{ alpha: true }});
  const stage = document.getElementById('stage');
  const stateSelect = document.getElementById('state');
  const speedSelect = document.getElementById('speed');
  const zoomSelect = document.getElementById('zoom');
  const scrub = document.getElementById('scrub');
  const readout = document.getElementById('readout');
  const status = document.getElementById('status');
  const play = document.getElementById('play');
  const filmstrip = document.getElementById('filmstrip');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  canvas.dataset.sampling = data.sampling;
  zoomSelect.value = String(data.initialZoom);
  let state = Object.keys(data.states)[0];
  let frame = 0;
  let playing = false;
  let timer = null;

  function current() {{ return data.states[state]; }}
  function fitInitialZoom() {{
    const rect = current().frames[0];
    const available = Math.max(1, stage.clientWidth - 88);
    const ceiling = Math.max(1, Math.floor(available / Math.max(rect.w, rect.h)));
    const target = Math.min(Number(data.initialZoom), ceiling);
    const supported = [1, 2, 4, 8, 12];
    zoomSelect.value = String(supported.slice().reverse().find(value => value <= target) || 1);
    stage.dataset.initialZoom = zoomSelect.value;
  }}
  function stopTimer() {{ if (timer !== null) window.clearTimeout(timer); timer = null; }}
  function schedule() {{
    stopTimer();
    if (!playing || current().frames.length < 2) return;
    const duration = current().durationsMs[frame] / Number(speedSelect.value);
    timer = window.setTimeout(() => {{ frame = (frame + 1) % current().frames.length; render(); schedule(); }}, duration);
  }}
  function draw() {{
    const rect = current().frames[frame];
    canvas.width = rect.w; canvas.height = rect.h;
    const zoom = Number(zoomSelect.value);
    canvas.style.width = `${{rect.w * zoom}}px`;
    canvas.style.height = `${{rect.h * zoom}}px`;
    context.imageSmoothingEnabled = data.sampling !== 'nearest';
    context.clearRect(0, 0, rect.w, rect.h);
    context.drawImage(atlas, rect.x, rect.y, rect.w, rect.h, 0, 0, rect.w, rect.h);
  }}
  function renderFilmstrip() {{
    if (filmstrip.dataset.state !== state || filmstrip.children.length !== current().frames.length) {{
      filmstrip.replaceChildren();
      current().frames.forEach((_rect, index) => {{
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'film-frame'; button.dataset.frame = String(index);
        button.setAttribute('aria-label', `Show frame ${{index + 1}}`);
        button.innerHTML = `<span>FRAME</span>${{String(index + 1).padStart(2, '0')}}`;
        button.addEventListener('click', () => {{ frame = index; render(); schedule(); }});
        filmstrip.append(button);
      }});
      filmstrip.dataset.state = state;
    }}
    Array.from(filmstrip.children).forEach((button, index) => {{
      button.setAttribute('aria-current', String(index === frame));
    }});
  }}
  function render() {{
    frame = Math.max(0, Math.min(frame, current().frames.length - 1));
    scrub.max = String(current().frames.length - 1); scrub.value = String(frame);
    readout.value = `${{frame + 1}} / ${{current().frames.length}}`;
    status.textContent = `${{state}} · frame ${{frame + 1}} · ${{data.sampling}}`;
    play.textContent = playing ? 'Pause' : 'Play';
    play.setAttribute('aria-label', playing ? 'Pause animation' : 'Play animation');
    play.setAttribute('aria-pressed', String(playing));
    draw(); renderFilmstrip();
  }}
  function step(delta) {{ frame = (frame + delta + current().frames.length) % current().frames.length; render(); schedule(); }}

  Object.keys(data.states).forEach(name => {{ const option = document.createElement('option'); option.value = name; option.textContent = name; stateSelect.append(option); }});
  stateSelect.value = state;
  stateSelect.addEventListener('change', () => {{ state = stateSelect.value; frame = 0; render(); schedule(); }});
  speedSelect.addEventListener('change', schedule);
  zoomSelect.addEventListener('change', draw);
  scrub.addEventListener('input', () => {{ frame = Number(scrub.value); render(); schedule(); }});
  play.addEventListener('click', () => {{ playing = !playing; render(); schedule(); }});
  document.getElementById('previous').addEventListener('click', () => step(-1));
  document.getElementById('next').addEventListener('click', () => step(1));
  const backgroundButtons = document.querySelectorAll('.backgrounds button[data-background]');
  backgroundButtons.forEach(button => button.addEventListener('click', () => {{
    stage.dataset.background = button.dataset.background;
    backgroundButtons.forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  }}));
  document.addEventListener('keydown', event => {{
    if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement || event.target instanceof HTMLButtonElement) return;
    if (event.code === 'Space') {{ event.preventDefault(); playing = !playing; render(); schedule(); }}
    else if (event.code === 'ArrowLeft') {{ event.preventDefault(); step(-1); }}
    else if (event.code === 'ArrowRight') {{ event.preventDefault(); step(1); }}
    else if (event.code === 'Home') {{ event.preventDefault(); frame = 0; render(); schedule(); }}
    else if (event.code === 'End') {{ event.preventDefault(); frame = current().frames.length - 1; render(); schedule(); }}
  }});
  const evidence = document.getElementById('evidence');
  if (data.evidence.length === 0) {{ const item = document.createElement('li'); item.className = 'empty'; item.textContent = 'No optional QA files are present yet.'; evidence.append(item); }}
  data.evidence.forEach(entry => {{ const item = document.createElement('li'); const link = document.createElement('a'); link.href = entry.href; link.target = '_blank'; link.rel = 'noopener'; link.textContent = entry.label; item.append(link); evidence.append(item); }});
  fitInitialZoom();
  atlas.addEventListener('load', () => {{ render(); if (!reducedMotion) {{ playing = true; render(); schedule(); }} }}, {{ once: true }});
  if (atlas.complete) atlas.dispatchEvent(new Event('load'));
}})();
</script>
</body>
</html>
"""


__all__ = ["PreviewWorkbenchError", "prepare_workbench"]
