"""Build a portable, manifest-driven animation review workbench."""

from __future__ import annotations

from base64 import b64encode
from hashlib import sha256
import html
from io import BytesIO, StringIO
import json
from pathlib import Path, PurePosixPath
import posixpath
from typing import Any, Mapping

from PIL import Image

from spritecore.contracts import load_manifest
from spritecore.paths import PathSafetyError, resolve_run_path
from spritecore.runtime_preview import RuntimePreviewError, manifest_durations_ms
from spritecore.tool_theme import THEME_SCRIPT, TOOL_CSS


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
    try:
        return list(manifest_durations_ms(manifest, state, count))
    except RuntimePreviewError as exc:
        raise PreviewWorkbenchError(str(exc)) from exc


def _gate_status(path: Path, content: bytes) -> str:
    """Read pass/fail/warn from a QA JSON report; other files are plain evidence."""
    if path.suffix.lower() != ".json":
        return "file"
    try:
        report = json.loads(content)
    except (OSError, ValueError):
        return "fail"
    if not isinstance(report, Mapping):
        return "fail"
    errors, warnings = report.get("errors", []), report.get("warnings", [])
    if not isinstance(errors, list) or not isinstance(warnings, list) or errors:
        return "fail"
    for name in ("ok", "complete", "applicable"):
        if name in report and type(report[name]) is not bool:
            return "fail"
    if report.get("ok") is False:
        return "fail"
    if report.get("complete") is False or report.get("applicable") is False:
        return "warn"
    status = report.get("status")
    if status in ("pass", "fail", "warn"):
        return "warn" if status == "pass" and warnings else status
    if "status" in report:
        return "warn" if status == "skipped" else "fail"
    ok = report.get("ok")
    if isinstance(ok, bool):
        if not ok:
            return "fail"
        return "warn" if report.get("warnings") else "pass"
    return "file"


def _relative_href(output_path: Path, target: Path) -> str:
    relative = posixpath.relpath(
        target.as_posix(),
        start=output_path.parent.as_posix(),
    )
    return str(PurePosixPath(relative))


def _source_record(run_dir: Path, path: Path, role: str, *, content: bytes | None = None) -> dict[str, Any]:
    if content is None:
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
        manifest_bytes = manifest_path.read_bytes()
        manifest = load_manifest(StringIO(manifest_bytes.decode("utf-8-sig"))).data
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
        atlas_bytes = atlas_path.read_bytes()
        with Image.open(BytesIO(atlas_bytes)) as opened:
            opened.verify()
        with Image.open(BytesIO(atlas_bytes)) as opened:
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
    if output_path == report_path or {output_path, report_path} & {atlas_path, manifest_path}:
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
    evidence_records: dict[str, dict[str, Any]] = {}
    for label, relative in KNOWN_EVIDENCE:
        try:
            target = resolve_run_path(run_root, relative)
        except PathSafetyError:
            continue
        if target.is_file():
            content = target.read_bytes()
            evidence_records[relative] = _source_record(run_root, target, "evidence", content=content)
            evidence.append(
                {
                    "label": label,
                    "path": relative,
                    "href": _relative_href(output_path, target),
                    "status": _gate_status(target, content),
                }
            )
        else:
            evidence.append({"label": label, "path": relative, "status": "missing"})
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
                evidence_records[relative] = _source_record(run_root, target, "evidence")
                evidence.append(
                    {
                        "label": label,
                        "path": relative,
                        "href": _relative_href(output_path, target),
                        "status": "file",
                    }
                )
    runtime_dir = run_root / "qa" / "runtime-preview"
    if runtime_dir.is_dir():
        for target in sorted(runtime_dir.glob("*.evidence.json")):
            relative = target.relative_to(run_root).as_posix()
            target = resolve_run_path(run_root, relative)
            evidence_records[relative] = _source_record(run_root, target, "evidence")
            evidence.append(
                {
                    "label": f"Runtime: {target.stem.removesuffix('.evidence')}",
                    "path": target.relative_to(run_root).as_posix(),
                    "href": _relative_href(output_path, target),
                    "status": "file",
                }
            )

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
        _source_record(run_root, atlas_path, "atlas", content=atlas_bytes),
        _source_record(run_root, manifest_path, "manifest", content=manifest_bytes),
    ]
    evidence_sources = []
    for entry in evidence:
        if entry["status"] == "missing":
            continue
        record = dict(evidence_records[entry["path"]])
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


WORKBENCH_CSS = """
.tool { height:100vh; }
.wb-main { display:grid; grid-template-columns:minmax(0,1fr) 280px; min-height:0; }
.wb-work { display:grid; grid-template-columns:minmax(0,1fr); grid-template-rows:minmax(0,1fr) auto auto; gap:10px; min-width:0; min-height:0; padding:12px; }
.wb-work .stage { min-height:0; }
.canvas-wrap { padding:32px; display:grid; place-items:center; }
.controls { display:grid; gap:10px; padding:10px 12px; }
.controls .toolbar { justify-content:space-between; }
.atlas-source { display:none; }
@media (max-width:860px) {
  .tool { height:auto; }
  .wb-main { grid-template-columns:minmax(0,1fr); }
  .wb-work .stage { min-height:56vh; }
  .rail { border-left:0; border-top:1px solid var(--line); }
  .brand-mark { display:none; }
}
@media (max-width:480px) {
  .wb-work { padding:8px; }
  .transport { grid-template-columns:auto 1fr; }
  .transport .readout { grid-column:2; grid-row:1; }
  .transport .scrub { grid-column:1 / -1; }
  .controls .toolbar { justify-content:flex-start; }
  .canvas-wrap { padding:16px; }
}
"""


def _render_html(data: Mapping[str, Any], atlas_data_uri: str) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    safe_atlas = html.escape(atlas_data_uri, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark light">
<title>Sprite review workbench</title>
<style>{TOOL_CSS}{WORKBENCH_CSS}</style>
</head>
<body>
<div class="tool">
  <header class="tool-header">
    <div class="brand"><span class="brand-mark">Sprite review</span><h1>Preview workbench</h1></div>
    <div class="status" id="status" aria-live="polite">Loading atlas…</div>
    <button type="button" class="btn btn-icon" id="theme-toggle" aria-label="Switch theme"><span aria-hidden="true">◐</span></button>
  </header>
  <main class="wb-main">
    <section class="wb-work" aria-label="Animation review">
      <div class="stage" data-testid="preview-stage" data-background="checker" id="stage" tabindex="0" aria-label="Animation stage. Use Space to play or pause and arrow keys to step frames.">
        <div class="canvas-wrap"><canvas id="frame-canvas" role="img" aria-label="Current animation frame"></canvas></div>
      </div>
      <div class="controls card">
        <div class="transport" aria-label="Playback controls">
          <div class="group">
            <button type="button" class="btn btn-icon" id="previous" aria-label="Previous frame">◀</button>
            <button type="button" class="btn btn-primary" id="play" aria-label="Play animation" aria-pressed="false">Play</button>
            <button type="button" class="btn btn-icon" id="next" aria-label="Next frame">▶</button>
          </div>
          <input class="scrub" id="scrub" aria-label="Animation frame" type="range" min="0" value="0" step="1">
          <output class="readout" id="readout" for="scrub">1 / 1</output>
        </div>
        <div class="toolbar">
          <div class="group">
            <label class="field" for="speed">Speed <select id="speed"><option value="0.25">0.25×</option><option value="0.5">0.5×</option><option value="1" selected>1×</option><option value="2">2×</option></select></label>
            <label class="field" for="zoom">Zoom <select id="zoom"><option value="1">1×</option><option value="2">2×</option><option value="4">4×</option><option value="8">8×</option><option value="12">12×</option></select></label>
          </div>
          <div class="seg backgrounds" role="group" aria-label="Review background">
            <button type="button" class="btn" data-background="checker" aria-pressed="true"><span class="swatch" data-swatch="checker" aria-hidden="true"></span>Checker</button>
            <button type="button" class="btn" data-background="black" aria-pressed="false"><span class="swatch" data-swatch="black" aria-hidden="true"></span>Black</button>
            <button type="button" class="btn" data-background="gray" aria-pressed="false"><span class="swatch" data-swatch="gray" aria-hidden="true"></span>Gray</button>
            <button type="button" class="btn" data-background="white" aria-pressed="false"><span class="swatch" data-swatch="white" aria-hidden="true"></span>White</button>
          </div>
        </div>
      </div>
      <div class="filmstrip" id="filmstrip" aria-label="All frames"></div>
    </section>
    <aside class="rail" aria-label="Inspector">
      <section class="rail-section"><h2 class="rail-title">States</h2><ul class="list" id="states"></ul></section>
      <section class="rail-section"><h2 class="rail-title">Frame</h2><dl class="facts" id="facts"></dl></section>
      <section class="rail-section"><h2 class="rail-title">Evidence</h2><ul class="list" id="evidence"></ul></section>
      <section class="rail-section"><h2 class="rail-title">Keys</h2>
        <dl class="keys"><dt><kbd>Space</kbd></dt><dd>Play or pause</dd><dt><kbd>←</kbd> <kbd>→</kbd></dt><dd>Step one frame</dd><dt><kbd>Home</kbd> <kbd>End</kbd></dt><dd>First or last frame</dd><dt><kbd>↑</kbd> <kbd>↓</kbd></dt><dd>Previous or next state</dd></dl>
      </section>
    </aside>
  </main>
</div>
<img class="atlas-source" id="atlas-source" src="{safe_atlas}" alt="">
<script type="application/json" id="preview-data">{payload}</script>
<script>{THEME_SCRIPT}</script>
<script>
(() => {{
  'use strict';
  const data = JSON.parse(document.getElementById('preview-data').textContent);
  const atlas = document.getElementById('atlas-source');
  const canvas = document.getElementById('frame-canvas');
  const stage = document.getElementById('stage');
  const statesList = document.getElementById('states');
  const facts = document.getElementById('facts');
  const speedSelect = document.getElementById('speed');
  const zoomSelect = document.getElementById('zoom');
  const scrub = document.getElementById('scrub');
  const readout = document.getElementById('readout');
  const status = document.getElementById('status');
  const play = document.getElementById('play');
  const filmstrip = document.getElementById('filmstrip');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const stateNames = Object.keys(data.states);
  canvas.dataset.sampling = data.sampling;
  zoomSelect.value = String(data.initialZoom);
  let state = stateNames[0];
  let frame = 0;
  let playing = false;
  let timer = null;

  function current() {{ return data.states[state]; }}
  function fitInitialZoom() {{
    const rect = current().frames[0];
    const available = Math.max(1, Math.min(stage.clientWidth, stage.clientHeight || stage.clientWidth) - 64);
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
  function paint(target, rect) {{
    target.width = rect.w; target.height = rect.h;
    const context = target.getContext('2d', {{ alpha: true }});
    context.imageSmoothingEnabled = data.sampling !== 'nearest';
    context.clearRect(0, 0, rect.w, rect.h);
    context.drawImage(atlas, rect.x, rect.y, rect.w, rect.h, 0, 0, rect.w, rect.h);
  }}
  function draw() {{
    const rect = current().frames[frame];
    const zoom = Number(zoomSelect.value);
    paint(canvas, rect);
    canvas.style.width = `${{rect.w * zoom}}px`;
    canvas.style.height = `${{rect.h * zoom}}px`;
  }}
  function renderStates() {{
    if (statesList.children.length === 0) {{
      stateNames.forEach(name => {{
        const entry = data.states[name];
        const total = entry.durationsMs.reduce((sum, value) => sum + value, 0);
        const item = document.createElement('li');
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'list-row'; button.dataset.state = name;
        const label = document.createElement('span'); label.textContent = name;
        const meta = document.createElement('span'); meta.className = 'meta'; meta.textContent = `${{entry.frames.length}} fr · ${{total}} ms`;
        button.append(label, meta);
        button.addEventListener('click', () => selectState(name));
        item.append(button); statesList.append(item);
      }});
    }}
    statesList.querySelectorAll('button').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.state === state)));
  }}
  function renderFilmstrip() {{
    if (filmstrip.dataset.state !== state || filmstrip.children.length !== current().frames.length) {{
      filmstrip.replaceChildren();
      const longest = Math.max(...current().durationsMs);
      current().frames.forEach((rect, index) => {{
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'film-frame'; button.dataset.frame = String(index);
        button.setAttribute('aria-label', `Show frame ${{index + 1}}, ${{current().durationsMs[index]}} milliseconds`);
        const thumb = document.createElement('canvas');
        thumb.dataset.sampling = data.sampling; thumb.setAttribute('aria-hidden', 'true');
        paint(thumb, rect);
        const number = document.createElement('span'); number.textContent = String(index + 1).padStart(2, '0');
        const bar = document.createElement('span'); bar.className = 'bar';
        bar.style.width = `${{Math.max(12, Math.round(current().durationsMs[index] / longest * 100))}}%`;
        button.append(thumb, number, bar);
        button.addEventListener('click', () => {{ frame = index; render(); schedule(); }});
        filmstrip.append(button);
      }});
      filmstrip.dataset.state = state;
    }}
    Array.from(filmstrip.children).forEach((button, index) => {{
      button.setAttribute('aria-current', String(index === frame));
    }});
  }}
  function renderFacts() {{
    const rect = current().frames[frame];
    const rows = [
      ['State', state], ['Frame', `${{frame + 1}} of ${{current().frames.length}}`],
      ['Size', `${{rect.w}} × ${{rect.h}} px`], ['Atlas x, y', `${{rect.x}}, ${{rect.y}}`],
      ['Duration', `${{current().durationsMs[frame]}} ms`], ['Sampling', data.sampling], ['Zoom', `${{zoomSelect.value}}×`],
    ];
    facts.replaceChildren(...rows.flatMap(([term, value]) => {{
      const dt = document.createElement('dt'); dt.textContent = term;
      const dd = document.createElement('dd'); dd.textContent = value;
      return [dt, dd];
    }}));
  }}
  function render() {{
    frame = Math.max(0, Math.min(frame, current().frames.length - 1));
    scrub.max = String(current().frames.length - 1); scrub.value = String(frame);
    readout.value = `${{frame + 1}} / ${{current().frames.length}}`;
    status.textContent = `${{state}} · frame ${{frame + 1}} · ${{data.sampling}}`;
    play.textContent = playing ? 'Pause' : 'Play';
    play.setAttribute('aria-label', playing ? 'Pause animation' : 'Play animation');
    play.setAttribute('aria-pressed', String(playing));
    draw(); renderStates(); renderFilmstrip(); renderFacts();
  }}
  function selectState(name) {{ state = name; frame = 0; render(); schedule(); }}
  function step(delta) {{ frame = (frame + delta + current().frames.length) % current().frames.length; render(); schedule(); }}

  speedSelect.addEventListener('change', schedule);
  zoomSelect.addEventListener('change', () => {{ draw(); renderFacts(); }});
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
    const index = stateNames.indexOf(state);
    if (event.code === 'Space') {{ event.preventDefault(); playing = !playing; render(); schedule(); }}
    else if (event.code === 'ArrowLeft') {{ event.preventDefault(); step(-1); }}
    else if (event.code === 'ArrowRight') {{ event.preventDefault(); step(1); }}
    else if (event.code === 'ArrowUp') {{ event.preventDefault(); selectState(stateNames[(index - 1 + stateNames.length) % stateNames.length]); }}
    else if (event.code === 'ArrowDown') {{ event.preventDefault(); selectState(stateNames[(index + 1) % stateNames.length]); }}
    else if (event.code === 'Home') {{ event.preventDefault(); frame = 0; render(); schedule(); }}
    else if (event.code === 'End') {{ event.preventDefault(); frame = current().frames.length - 1; render(); schedule(); }}
  }});
  const evidence = document.getElementById('evidence');
  const chipText = {{ pass: 'pass', fail: 'fail', warn: 'warn', missing: 'missing', file: 'file' }};
  if (data.evidence.every(entry => entry.status === 'missing')) {{ const item = document.createElement('li'); item.className = 'empty'; item.textContent = 'No QA files yet. Run the checks, then rebuild this workbench.'; evidence.append(item); }}
  data.evidence.forEach(entry => {{
    const item = document.createElement('li');
    const chip = document.createElement('span'); chip.className = 'chip'; chip.dataset.status = entry.status; chip.textContent = chipText[entry.status] || entry.status;
    const label = document.createElement('span'); label.textContent = entry.label;
    if (entry.href) {{ const link = document.createElement('a'); link.className = 'list-row'; link.href = entry.href; link.target = '_blank'; link.rel = 'noopener'; link.append(label, chip); item.append(link); }}
    else {{ const row = document.createElement('div'); row.className = 'list-row'; row.setAttribute('aria-disabled', 'true'); row.append(label, chip); item.append(row); }}
    evidence.append(item);
  }});
  fitInitialZoom();
  atlas.addEventListener('load', () => {{ render(); if (!reducedMotion) {{ playing = true; render(); schedule(); }} }}, {{ once: true }});
  if (atlas.complete) atlas.dispatchEvent(new Event('load'));
}})();
</script>
</body>
</html>
"""


__all__ = ["PreviewWorkbenchError", "prepare_workbench"]
