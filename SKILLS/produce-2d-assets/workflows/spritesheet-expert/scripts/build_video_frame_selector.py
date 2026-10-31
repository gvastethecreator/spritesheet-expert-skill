#!/usr/bin/env python3
"""Build the required visual selector for every decoded source-video frame."""

from __future__ import annotations

import argparse
import base64
from html import escape
from hashlib import sha256
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import shlex
import stat
import sys
from urllib.parse import quote

from PIL import Image, ImageDraw

from runio import RunLockError, acquire_run_lock, atomic_write_bytes, atomic_write_text
from spritecore.paths import resolve_run_path
from spritecore.tool_theme import THEME_SCRIPT, TOOL_CSS
from spritecore.video_animation import (
    MAX_DECODED_FRAMES,
    read_video_metadata,
    reviewed_sample_indices,
)


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def thumbnail_data(image: Image.Image, index: int, timestamp: float) -> str:
    rgba = image.convert("RGBA")
    preview = Image.new("RGBA", rgba.size, (17, 17, 17, 255))
    preview.alpha_composite(rgba)
    preview = preview.convert("RGB")
    preview.thumbnail((144, 144), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (156, 180), (13, 13, 15))
    canvas.paste(preview, ((156 - preview.width) // 2, 6))
    draw = ImageDraw.Draw(canvas)
    draw.text((8, 157), f"#{index}  {timestamp:.3f}s", fill=(235, 235, 238))
    buffer = BytesIO()
    canvas.save(buffer, format="JPEG", quality=72, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def write_timeline_pages(
    output_dir: Path,
    thumbnails: list[str],
    fps: float,
    *,
    columns: int = 5,
    rows: int = 5,
) -> dict[str, object]:
    """Persist an exhaustive, paginated visual audit beside the HTML selector."""
    if any(type(value) is not int or value <= 0 for value in (columns, rows)):
        raise ValueError("timeline page grid must have positive dimensions")
    if not thumbnails or not math.isfinite(fps) or fps <= 0:
        raise ValueError("timeline requires frames and a finite positive fps")
    output_dir.mkdir(parents=True, exist_ok=True)
    page_capacity = columns * rows
    pages: list[dict[str, object]] = []
    for page_index, first in enumerate(range(0, len(thumbnails), page_capacity), 1):
        batch = thumbnails[first : first + page_capacity]
        page = Image.new("RGB", (columns * 156, rows * 180), (9, 9, 11))
        for offset, data_url in enumerate(batch):
            _header, encoded = data_url.split(",", 1)
            thumb = Image.open(BytesIO(base64.b64decode(encoded))).convert("RGB")
            page.paste(thumb, ((offset % columns) * 156, (offset // columns) * 180))
        page_path = output_dir / f"timeline-page-{page_index:02d}.png"
        buffer = BytesIO()
        page.save(buffer, format="PNG", optimize=True)
        atomic_write_bytes(page_path, buffer.getvalue())
        pages.append(
            {
                "path": page_path.name,
                "first": first,
                "last": first + len(batch) - 1,
                "sha256": digest(page_path),
            }
        )
    manifest = {
        "version": 1,
        "kind": "full-video-frame-review-pages",
        "frame_count": len(thumbnails),
        "fps": fps,
        "columns": columns,
        "rows": rows,
        "pages": pages,
    }
    manifest_path = output_dir / "timeline-pages.json"
    atomic_write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return {
        "manifest": manifest_path.name,
        "manifest_sha256": digest(manifest_path),
        "pages": pages,
    }


def decode_thumbnails(video_path: Path) -> tuple[list[str], float, tuple[int, int]]:
    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise ValueError("imageio-ffmpeg is required; install requirements-video.txt") from exc
    reader = imageio_ffmpeg.read_frames(str(video_path), pix_fmt="rgb24")
    try:
        try:
            metadata = next(reader)
        except StopIteration as exc:
            raise ValueError("video decoder returned no metadata") from exc
        size, fps, _duration = read_video_metadata(metadata)
        expected = size[0] * size[1] * 3
        thumbnails = []
        for index, payload in enumerate(reader):
            if index >= MAX_DECODED_FRAMES:
                raise ValueError(f"video exceeds the {MAX_DECODED_FRAMES}-frame safety limit")
            if not isinstance(payload, (bytes, bytearray)) or len(payload) != expected:
                raise ValueError(f"malformed decoded video frame {index}")
            image = Image.frombytes("RGB", size, bytes(payload))
            thumbnails.append(thumbnail_data(image, index, index / fps))
    finally:
        close = getattr(reader, "close", None)
        if callable(close):
            close()
    if not thumbnails:
        raise ValueError("video decoder returned zero frames")
    return thumbnails, fps, size


def _directory_link(path: Path) -> bool:
    return path.is_symlink() or (
        os.name == "nt"
        and bool(path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    )


def resolve_source_report(run_dir: Path, state: str, supplied: Path | None) -> Path:
    if supplied is not None:
        path = supplied.expanduser().resolve()
        try:
            path.relative_to(run_dir)
        except ValueError as exc:
            raise ValueError("source report must stay inside the run directory") from exc
        if not path.is_file():
            raise ValueError(f"source report does not exist: {path}")
        return path
    provider_dir = run_dir / "provider"
    if _directory_link(provider_dir):
        raise ValueError("provider report discovery does not follow directory links")
    candidates = []
    for root, dirs, files in os.walk(provider_dir, followlinks=False):
        dirs[:] = [name for name in dirs if not _directory_link(Path(root) / name)]
        if Path(root).name == state and "video-source.json" in files:
            path = Path(root) / "video-source.json"
            candidates.append(resolve_run_path(run_dir, path.relative_to(run_dir)))
    if len(candidates) != 1:
        raise ValueError(
            f"expected one video-source.json for {state!r}, found {len(candidates)}; "
            "pass --source-report"
        )
    return candidates[0].resolve()


def report_file_path(run_dir: Path, record: dict[str, object]) -> Path:
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise ValueError("source report file record must contain a path")
    path = Path(record["path"]).expanduser()
    return path.resolve() if path.is_absolute() else resolve_run_path(run_dir, path)


def _shell_command(args: list[str]) -> str:
    """Quote an argv for this host's documented shell: PowerShell or POSIX sh."""
    if os.name == "nt":
        return "& " + " ".join("'" + value.replace("'", "''") + "'" for value in args)
    return shlex.join(args)


def selector_review_contract(
    run_dir: Path,
    state: str,
    slot_count: int,
    exact_idle_slots: list[int],
) -> dict[str, object]:
    request_path = run_dir / "sprite-request.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(request, dict) or not isinstance(request.get("states"), dict):
        raise ValueError("sprite request must declare states")
    entry = request["states"].get(state)
    if not isinstance(entry, dict):
        raise ValueError("selector state is missing from sprite request")
    workflows = {
        str(value).strip().lower()
        for value in entry.get("animation_workflows", [])
        if isinstance(value, str)
    }
    motion = request.get("creature_motion")
    motion = motion if isinstance(motion, dict) else {}
    anatomy = str(motion.get("anatomy") or "unspecified")
    locomotion = str(motion.get("locomotion") or "unspecified")
    if "front-fps-creature-locomotion" in workflows and slot_count == 4:
        slot_labels = ["Exact idle", "Phase A", "Exact idle", "Phase B"]
        motion_source = str(motion.get("movement_source") or "declared movement")
    elif "front-fps-creature-attack" in workflows and slot_count == 4:
        slot_labels = ["Exact idle", "Anticipation", "Contact", "Exact idle"]
        motion_source = str(motion.get("attack_source") or "declared attack")
    else:
        slot_labels = [
            "Exact idle" if index in exact_idle_slots else f"Pose {index + 1}"
            for index in range(slot_count)
        ]
        motion_source = "declared movement"
    return {
        "creatureType": f"{anatomy} / {locomotion}",
        "motionSource": motion_source,
        "slotLabels": slot_labels,
        "checks": [
            "Subject type, anatomy and declared orientation are correct",
            "Each slot holds its pose and uses the declared movement",
            "Identity, face, volume and limb count stay stable",
            "Camera, scale, center, ground and background stay fixed",
            "No part touches the edge or is cropped",
        ],
    }


def build_selector(
    *,
    run_dir: Path,
    state: str,
    source_report: Path | None = None,
    force: bool = False,
) -> dict[str, object]:
    run_root = run_dir.expanduser().resolve()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", state):
        raise ValueError("state must be a lowercase kebab-case name")
    report_path = resolve_source_report(run_root, state, source_report)
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes.decode("utf-8"))
    if not isinstance(report, dict) or report.get("kind") not in (
        "sprite-grok-video-source", "sprite-video-source"
    ):
        raise ValueError("source report is not a supported video-source report")
    if report.get("status") != "pass" or report.get("state") != state:
        raise ValueError("source report must pass and match --state")
    video_record = report.get("video")
    video_path = report_file_path(run_root, video_record)
    if not video_path.is_file() or digest(video_path) != video_record.get("sha256"):
        raise ValueError("video is missing or no longer matches video-source.json")
    sources = {report_path: sha256(report_bytes).hexdigest(), video_path: video_record["sha256"]}
    request_path = resolve_run_path(run_root, "sprite-request.json")
    sources[request_path] = digest(request_path)
    request_record = report.get("sprite_request")
    if not isinstance(request_record, dict) or request_record.get("sha256") != sources[request_path]:
        raise ValueError("sprite request no longer matches video-source.json")
    first_record = report.get("first_frame")
    first_path = None
    if first_record is not None:
        first_path = report_file_path(run_root, first_record)
        sources[first_path] = digest(first_path)
        if sources[first_path] != first_record.get("sha256"):
            raise ValueError("first frame no longer matches video-source.json")
    exact_first = report.get("exact_first_frame_preserved")
    if type(exact_first) is not bool or (exact_first and first_path is None):
        raise ValueError("exact first-frame evidence is invalid")
    output_dir = resolve_run_path(run_root, f"qa/{state}-video-frame-selector")
    output_path = output_dir / "index.html"
    evidence_path = output_dir / "selector.evidence.json"
    timeline_manifest_path = output_dir / "timeline-pages.json"
    if (
        output_path.exists()
        or evidence_path.exists()
        or timeline_manifest_path.exists()
        or any(output_dir.glob("timeline-page-*.png"))
    ) and not force:
        raise ValueError(
            f"selector already exists; pass --force to replace it: {output_path}"
        )
    thumbnails, fps, size = decode_thumbnails(video_path)
    decoded = report.get("decoded")
    if not isinstance(decoded, dict) or (
        decoded.get("frame_count") != len(thumbnails)
        or decoded.get("fps") != fps
        or (decoded.get("width"), decoded.get("height")) != size
    ):
        raise ValueError("decoded video no longer matches source report metadata")
    selected = report.get("sampled_video_indices")
    if not isinstance(selected, list) or len(selected) < 2 or any(type(v) is not int for v in selected):
        raise ValueError("sampled video indices must be integers for at least two slots")
    reviewed_sample_indices(len(thumbnails), len(selected), selected)
    exact_idle_slots = report.get("exact_idle_slots", [0])
    if not isinstance(exact_idle_slots, list) or any(
        type(v) is not int or v < 0 or v >= len(selected) for v in exact_idle_slots
    ):
        raise ValueError("exact idle slots must refer to selection slots")
    metrics = report.get("selection_metrics")
    if metrics is None:
        metrics = {}
    if not isinstance(metrics, dict):
        raise ValueError("selection metrics must be an object")
    candidates = metrics.get("candidate_sets", [])
    if not isinstance(candidates, list):
        raise ValueError("candidate sets must be an array")
    for candidate in candidates:
        indices = candidate.get("indices") if isinstance(candidate, dict) else None
        if not isinstance(indices, list) or any(type(v) is not int for v in indices):
            raise ValueError("candidate indices must be integers")
        reviewed_sample_indices(len(thumbnails), len(selected), indices)
        score = candidate.get("score")
        if score is not None and (type(score) not in (int, float) or not math.isfinite(score)):
            raise ValueError("candidate score must be finite when supplied")
    for key in ("source_edge_contact_frames", "scale_unstable_frames"):
        flags = metrics.get(key, [])
        if not isinstance(flags, list) or any(type(v) is not int or not 0 <= v < len(thumbnails) for v in flags):
            raise ValueError(f"invalid selection metric: {key}")
    idle_thumbnail = thumbnails[0]
    if exact_first:
        with Image.open(first_path) as image:
            idle_thumbnail = thumbnail_data(image, 0, 0)
    review_contract = selector_review_contract(
        run_root, state, len(selected), exact_idle_slots
    )
    scripts_dir = Path(__file__).resolve().parent
    if report["kind"] == "sprite-grok-video-source":
        invocation_path = report_file_path(run_root, report.get("invocation"))
        sources[invocation_path] = digest(invocation_path)
        args = [sys.executable, str(scripts_dir / "ingest_grok_video_animation.py"),
                "--run-dir", str(run_root), "--state", state,
                "--invocation", str(invocation_path)]
        video_url = video_path.as_uri()
    else:
        if not video_path.is_relative_to(run_root):
            raise ValueError("imported video must be the run-owned copy")
        args = [sys.executable, str(scripts_dir / "ingest_video_animation.py"),
                "--run-dir", str(run_root), "--state", state, "--video", str(video_path)]
        if first_path is not None:
            args.extend(["--first-frame", str(first_path)])
        video_url = quote(os.path.relpath(video_path, output_dir).replace(os.sep, "/"))
    command_prefix = _shell_command([*args, "--sample-indices"]) + " "
    payload = {
        "state": state,
        "fps": fps,
        "frameCount": len(thumbnails),
        "videoUrl": video_url,
        "thumbnails": thumbnails,
        "idleThumbnail": idle_thumbnail,
        "selected": selected,
        "candidates": candidates,
        "unsafeFrames": (report.get("selection_metrics") or {}).get(
            "source_edge_contact_frames", []
        ),
        "scaleUnsafeFrames": (report.get("selection_metrics") or {}).get(
            "scale_unstable_frames", []
        ),
        "exactIdleSlots": exact_idle_slots,
        "exactFirstFramePreserved": exact_first,
        "commandPrefix": command_prefix,
        "reviewContract": review_contract,
    }
    encoded = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


    html = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark light">
<title>Frame selector · __STATE__</title>
<style>__THEME_CSS__
.sel-main{display:grid;grid-template-columns:minmax(300px,400px) minmax(0,1fr);min-height:0}
.sel-side{display:grid;gap:12px;align-content:start;padding:12px;border-right:1px solid var(--line);background:var(--surface)}
.sel-side video{display:block;width:100%;aspect-ratio:1;border-radius:var(--radius-lg);background:var(--matte-black)}
.sel-intro{padding:8px 16px;border-bottom:1px solid var(--line);color:var(--muted);font-size:12px}
.slots{display:grid;grid-template-columns:repeat(auto-fit,minmax(84px,1fr));gap:6px}
.slot{display:grid;gap:4px;padding:4px;border:1px solid var(--line);border-radius:var(--radius);background:var(--raised);color:var(--muted);font:11px/1.3 var(--font-mono);text-align:left;cursor:pointer}
.slot img{display:block;width:100%;border-radius:2px}
.slot.active{border-color:var(--accent);color:var(--ink);box-shadow:inset 0 0 0 1px var(--accent)}
.slot.locked{cursor:default}
.cycle{display:block;width:160px;max-width:100%;margin:0 auto;border:1px solid var(--line);border-radius:var(--radius)}
.review{padding:10px;border:1px solid var(--line);border-radius:var(--radius-lg);background:var(--raised)}
.review strong{display:block}.review small{display:block;margin:2px 0 8px;color:var(--muted)}
.review label{display:flex;gap:8px;align-items:flex-start;margin:6px 0;font-size:12px;line-height:1.35}
.review input{accent-color:var(--accent);margin-top:2px}
.candidates{display:grid;gap:6px}
.candidate{display:flex;flex-wrap:wrap;gap:3px;align-items:center;padding:6px;border:1px solid var(--line);border-radius:var(--radius);background:var(--raised);color:var(--ink);cursor:pointer;text-align:left}
.candidate img{width:44px;display:block;border-radius:2px}
.candidate strong{flex-basis:100%;font:600 11px var(--font-mono)}
.candidate.unsafe{border-color:var(--bad)}
.candidate.unsafe strong{color:var(--bad)}
.actions{display:flex;gap:6px;flex-wrap:wrap}
.sel-status{color:var(--muted);font:11px/1.5 var(--font-mono);word-break:break-all}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(112px,1fr));gap:6px;padding:12px;align-content:start}
.frame{position:relative;padding:0;border:2px solid transparent;border-radius:var(--radius);background:var(--surface);cursor:pointer;overflow:hidden}
.frame img{display:block;width:100%}
.frame.selected{border-color:var(--accent)}
.frame.active{outline:2px solid var(--ok);outline-offset:1px}
.frame.unsafe::after,.frame.scale-unsafe::before{position:absolute;right:4px;padding:1px 5px;border-radius:3px;color:#fff;font:700 10px var(--font-mono)}
.frame.unsafe::after{content:'EDGE';top:4px;background:var(--bad)}
.frame.scale-unsafe::before{content:'SCALE';top:22px;background:var(--warn)}
.badge{position:absolute;top:4px;left:4px;padding:1px 5px;border-radius:3px;background:var(--accent);color:var(--accent-ink);font:700 11px var(--font-mono)}
h2.rail-title{margin:0}
@media(max-width:850px){.sel-main{grid-template-columns:minmax(0,1fr)}.sel-side{border-right:0;border-bottom:1px solid var(--line)}}
</style></head><body>
<div class="tool">
<header class="tool-header"><div class="brand"><span class="brand-mark">Video frames</span><h1>Frame selector · __STATE__</h1></div><div class="status" id="headline" aria-live="polite"></div><button type="button" class="btn btn-icon" id="theme-toggle" aria-label="Switch theme"><span aria-hidden="true">&#9680;</span></button></header>
<div>
<p class="sel-intro">Full video at <b id="fps"></b> FPS. Frame 0 is locked. Change the other frames without regenerating.</p>
<main class="sel-main">
<section class="sel-side" aria-label="Selection">
<video id="video" controls muted loop></video>
<img id="cycle" class="cycle" alt="Cycle preview">
<button type="button" class="btn" id="play-cycle">Pause preview</button>
<div id="slots" class="slots"></div>
<div id="review" class="review"></div>
<h2 class="rail-title">Candidate cycles</h2>
<div id="candidates" class="candidates"></div>
<div class="actions"><button type="button" class="btn btn-primary" id="copy">Copy reviewed command</button><button type="button" class="btn" id="download">Download selection JSON</button><button type="button" class="btn" id="reset">Restore automatic</button></div>
<div id="status" class="sel-status" aria-live="polite"></div>
</section>
<section aria-label="All decoded frames"><div id="grid" class="grid"></div></section>
</main>
</div>
</div>
<script>__THEME_SCRIPT__</script>
<script>
const data=__DATA__;
let selected=[...data.selected],active=1,cycleFrame=0;
const video=document.querySelector('#video'),grid=document.querySelector('#grid'),slots=document.querySelector('#slots'),status=document.querySelector('#status'),headline=document.querySelector('#headline'),cycle=document.querySelector('#cycle'),review=document.querySelector('#review'),copy=document.querySelector('#copy'),download=document.querySelector('#download'),play=document.querySelector('#play-cycle');
const motionPreference=matchMedia('(prefers-reduced-motion: reduce)');
let playing=!motionPreference.matches;
video.src=data.videoUrl;
document.querySelector('#fps').textContent=data.fps.toFixed(3);
(()=>{
  const title=document.createElement('strong');title.textContent='Contract: '+data.reviewContract.creatureType;
  const source=document.createElement('small');source.textContent='Motion: '+data.reviewContract.motionSource;
  review.append(title,source);
  data.reviewContract.checks.forEach((label,index)=>{
    const row=document.createElement('label'),input=document.createElement('input');
    input.type='checkbox';input.dataset.review=String(index);row.append(input,document.createTextNode(label));review.append(row);
  });
})();
function seek(i){video.currentTime=i/data.fps;video.pause()}
function isEdgeUnsafe(frame,slot){return data.unsafeFrames.includes(frame)&&!(data.exactFirstFramePreserved&&data.exactIdleSlots.includes(slot))}
function isScaleUnsafe(frame,slot){return data.scaleUnsafeFrames.includes(frame)&&!(data.exactFirstFramePreserved&&data.exactIdleSlots.includes(slot))}
function isUnsafe(frame,slot){return isEdgeUnsafe(frame,slot)||isScaleUnsafe(frame,slot)}
function reviewInputs(){return [...review.querySelectorAll('input')]}
function resetReview(){reviewInputs().forEach(input=>input.checked=false)}
function thumb(src,alt){const img=document.createElement('img');img.src=src;img.alt=alt;return img}
function slotThumbnail(frame,slot){return data.exactIdleSlots.includes(slot)?data.idleThumbnail:data.thumbnails[frame]}
function command(){return data.commandPrefix+'"'+selected.join(',')+'" --force'}
function render(){
  slots.replaceChildren();
  selected.forEach((frame,i)=>{
    const b=document.createElement('button');b.type='button';b.className='slot '+(i===active?'active ':'')+(i===0?'locked':'');
    const label=document.createElement('span');label.textContent=`${i+1}: ${data.reviewContract.slotLabels[i]||'Pose'} · #${frame}${isEdgeUnsafe(frame,i)?' · TOUCHES EDGE':''}${isScaleUnsafe(frame,i)?' · UNSTABLE SCALE':''}`;
    b.append(thumb(slotThumbnail(frame,i),data.exactIdleSlots.includes(i)?'Exact idle':'Frame '+frame),label);
    if(i>0)b.onclick=()=>{active=i;seek(frame);render()};slots.append(b);
  });
  document.querySelectorAll('.frame').forEach((el,i)=>{
    el.classList.toggle('selected',selected.includes(i));el.classList.toggle('active',selected[active]===i);
    const badge=el.querySelector('.badge');if(badge)badge.remove();
    const slot=selected.indexOf(i);if(slot>=0){const x=document.createElement('span');x.className='badge';x.textContent=slot+1;el.append(x)}
  });
  const edgeUnsafe=selected.filter((frame,slot)=>isEdgeUnsafe(frame,slot)),scaleUnsafe=selected.filter((frame,slot)=>isScaleUnsafe(frame,slot)),reviewed=reviewInputs().every(input=>input.checked);
  copy.disabled=download.disabled=edgeUnsafe.length>0||scaleUnsafe.length>0||!reviewed;
  headline.textContent=reviewed&&!edgeUnsafe.length&&!scaleUnsafe.length?'ready to ingest':'review required';
  status.textContent='Indices: '+selected.join(', ')+(edgeUnsafe.length?' · WARNING edge: '+edgeUnsafe.join(', '):' · no source-edge flags')+(scaleUnsafe.length?' · WARNING scale: '+scaleUnsafe.join(', '):' · no scale flags')+(reviewed?' · review complete':' · confirm all review checks')+' · '+command();
  cycle.src=slotThumbnail(selected[cycleFrame%selected.length],cycleFrame%selected.length);
  play.textContent=playing?'Pause preview':'Play preview';play.setAttribute('aria-pressed',String(playing));
}
review.addEventListener('change',render);
data.candidates.forEach(c=>{
  const unsafe=c.indices.filter((frame,slot)=>isUnsafe(frame,slot)),b=document.createElement('button');
  b.type='button';b.className='candidate'+(unsafe.length?' unsafe':'');
  const head=document.createElement('strong');head.textContent=`#${c.rank} · ${Number.isFinite(c.score)?'heuristic score '+c.score:'unscored'}${unsafe.length?' · check '+unsafe.join(', '):' · no supplied alerts'}`;
  b.append(head,...c.indices.map((i,slot)=>thumb(slotThumbnail(i,slot),'Slot '+(slot+1))));
  b.onclick=()=>{selected=[...c.indices];active=1;cycleFrame=0;resetReview();seek(selected[1]);render()};document.querySelector('#candidates').append(b);
});
data.thumbnails.forEach((src,i)=>{
  const b=document.createElement('button');b.type='button';b.className='frame'+(data.unsafeFrames.includes(i)?' unsafe':'')+(data.scaleUnsafeFrames.includes(i)?' scale-unsafe':'');
  const img=thumb(src,'Frame '+i);img.loading='lazy';b.append(img);
  b.onclick=()=>{
    seek(i);
    if(i!==0){
      if(selected.includes(i)){active=selected.indexOf(i)}
      else{if(active===0)active=1;selected[active]=i;selected=[0,...selected.slice(1).sort((a,b)=>a-b)];active=selected.indexOf(i);resetReview()}
    }
    render();
  };grid.append(b);
});
setInterval(()=>{if(playing){cycleFrame=(cycleFrame+1)%selected.length;cycle.src=slotThumbnail(selected[cycleFrame],cycleFrame)}},125);
play.onclick=()=>{playing=!playing;render()};
motionPreference.addEventListener('change',event=>{if(event.matches){playing=false;render()}});
copy.onclick=async()=>{await navigator.clipboard.writeText(command());status.textContent='Reviewed command copied.'};
download.onclick=()=>{
  const blob=new Blob([JSON.stringify({state:data.state,sample_indices:selected,fps:data.fps,review_contract:data.reviewContract,reviewed_checks:data.reviewContract.checks},null,2)],{type:'application/json'}),a=document.createElement('a');
  a.href=URL.createObjectURL(blob);a.download=`${data.state}-frame-selection.json`;a.click();URL.revokeObjectURL(a.href);
};
document.querySelector('#reset').onclick=()=>{selected=[...data.selected];active=1;cycleFrame=0;resetReview();render()};
render();
</script></body></html>"""
    html = (
        html.replace("__THEME_CSS__", TOOL_CSS)
        .replace("__THEME_SCRIPT__", THEME_SCRIPT)
        .replace("__STATE__", escape(state))
        .replace("__DATA__", encoded)
    )
    outputs = [output_path, evidence_path, timeline_manifest_path, *(
        output_dir / f"timeline-page-{index:02d}.png"
        for index in range(1, (len(thumbnails) + 24) // 25 + 1)
    )]
    for path in outputs:
        resolved = resolve_run_path(run_root, path.relative_to(run_root))
        if resolved in sources:
            raise ValueError("selector outputs cannot overwrite sources")
        if resolved.exists() and not resolved.is_file():
            raise ValueError(f"selector output is not a file: {resolved}")
    if any(digest(path) != expected for path, expected in sources.items()):
        raise ValueError("selector sources changed before commit")
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(output_path, html)
    timeline = write_timeline_pages(output_dir, thumbnails, fps)
    evidence = {
        "version": 1,
        "kind": "sprite-video-frame-selector-evidence",
        "status": "pass",
        "state": state,
        "source_report": {
            "path": report_path.relative_to(run_root).as_posix(),
            "sha256": sha256(report_bytes).hexdigest(),
        },
        "video": {
            "path": report["video"]["path"],
            "sha256": report["video"]["sha256"],
        },
        "decoded_frame_count": len(thumbnails),
        "fps": fps,
        "selected_indices": selected,
        "candidate_count": len(payload["candidates"]),
        "html": {
            "path": output_path.relative_to(run_root).as_posix(),
            "sha256": digest(output_path),
        },
        "timeline": timeline,
    }
    atomic_write_text(evidence_path, json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    return {
        "status": "pass",
        "output": str(output_path),
        "evidence": str(evidence_path),
        "frames": len(thumbnails),
        "fps": fps,
        "timeline_pages": len(timeline["pages"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--source-report", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        with acquire_run_lock(args.run_dir, Path(__file__).name):
            result = build_selector(
                run_dir=args.run_dir,
                state=args.state,
                source_report=args.source_report,
                force=args.force,
            )
    except (OSError, ValueError, RunLockError) as exc:
        print(json.dumps({"status": "operational-error", "errors": [str(exc)]}, ensure_ascii=False))
        return 3
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
