#!/usr/bin/env python3
"""Build the required visual selector for every decoded source-video frame."""

from __future__ import annotations

import argparse
import base64
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

from PIL import Image, ImageDraw

from runio import atomic_write_text


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def thumbnail_data(image: Image.Image, index: int, timestamp: float) -> str:
    preview = image.convert("RGB")
    preview.thumbnail((144, 144), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (156, 180), (13, 13, 15))
    canvas.paste(preview, ((156 - preview.width) // 2, 6))
    draw = ImageDraw.Draw(canvas)
    draw.text((8, 157), f"#{index}  {timestamp:.3f}s", fill=(235, 235, 238))
    buffer = BytesIO()
    canvas.save(buffer, format="JPEG", quality=72, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def decode_thumbnails(video_path: Path) -> tuple[list[str], float, tuple[int, int]]:
    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise SystemExit("imageio-ffmpeg is required; install requirements-video.txt") from exc
    reader = imageio_ffmpeg.read_frames(str(video_path), pix_fmt="rgb24")
    try:
        metadata = next(reader)
        size = tuple(int(value) for value in metadata["size"])
        fps = float(metadata["fps"])
        expected = size[0] * size[1] * 3
        thumbnails = []
        for index, payload in enumerate(reader):
            if len(payload) != expected:
                raise SystemExit(f"malformed decoded video frame {index}")
            image = Image.frombytes("RGB", size, bytes(payload))
            thumbnails.append(thumbnail_data(image, index, index / fps))
    finally:
        close = getattr(reader, "close", None)
        if callable(close):
            close()
    return thumbnails, fps, size


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
    candidates = sorted((run_dir / "provider").glob(f"**/{state}/video-source.json"))
    if len(candidates) != 1:
        raise ValueError(
            f"expected one video-source.json for {state!r}, found {len(candidates)}; "
            "pass --source-report"
        )
    return candidates[0].resolve()


def report_file_path(run_dir: Path, record: dict[str, object]) -> Path:
    path = Path(str(record["path"])).expanduser()
    return path.resolve() if path.is_absolute() else (run_dir / path).resolve()


def build_selector(
    *,
    run_dir: Path,
    state: str,
    source_report: Path | None = None,
    force: bool = False,
) -> dict[str, object]:
    run_root = run_dir.expanduser().resolve()
    report_path = resolve_source_report(run_root, state, source_report)
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes.decode("utf-8"))
    if report.get("kind") not in {"sprite-grok-video-source", "sprite-video-source"}:
        raise ValueError("source report is not a supported video-source report")
    if report.get("state") != state:
        raise ValueError("source report state does not match --state")
    video_path = report_file_path(run_root, report["video"])
    if not video_path.is_file() or digest(video_path) != report["video"]["sha256"]:
        raise ValueError("video is missing or no longer matches video-source.json")
    output_dir = run_root / "qa" / f"{state}-video-frame-selector"
    output_path = output_dir / "index.html"
    evidence_path = output_dir / "selector.evidence.json"
    if (output_path.exists() or evidence_path.exists()) and not force:
        raise ValueError(
            f"selector already exists; pass --force to replace it: {output_path}"
        )
    thumbnails, fps, _size = decode_thumbnails(video_path)
    selected = [int(value) for value in report["sampled_video_indices"]]
    scripts_dir = Path(__file__).resolve().parent
    if report["kind"] == "sprite-grok-video-source":
        invocation_path = Path(report["invocation"]["path"]).expanduser().resolve()
        command_prefix = (
            f'python "{scripts_dir / "ingest_grok_video_animation.py"}" '
            f'--run-dir "{run_root}" --state "{state}" '
            f'--invocation "{invocation_path}" --sample-indices '
        )
    else:
        command_prefix = (
            f'python "{scripts_dir / "ingest_video_animation.py"}" '
            f'--run-dir "{run_root}" --state "{state}" --video "{video_path}" '
        )
        first_record = report.get("first_frame")
        if isinstance(first_record, dict):
            command_prefix += f'--first-frame "{report_file_path(run_root, first_record)}" '
        command_prefix += "--sample-indices "
    payload = {
        "state": state,
        "fps": fps,
        "frameCount": len(thumbnails),
        "videoUrl": video_path.as_uri(),
        "thumbnails": thumbnails,
        "selected": selected,
        "candidates": (report.get("selection_metrics") or {}).get("candidate_sets", []),
        "unsafeFrames": (report.get("selection_metrics") or {}).get(
            "source_edge_contact_frames", []
        ),
        "exactIdleSlots": report.get("exact_idle_slots", [0]),
        "exactFirstFramePreserved": bool(report.get("exact_first_frame_preserved")),
        "commandPrefix": command_prefix,
    }
    encoded = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


    html = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Selector de frames · __STATE__</title>
<style>
:root{color-scheme:dark;font-family:Inter,system-ui,sans-serif;background:#09090b;color:#f4f4f5}*{box-sizing:border-box}
body{margin:0}header{position:sticky;top:0;z-index:5;background:#09090bf2;border-bottom:1px solid #27272a;padding:14px 18px}
h1{font-size:18px;margin:0 0 10px}.layout{display:grid;grid-template-columns:minmax(300px,420px) 1fr;gap:18px;padding:18px}
.panel{background:#111113;border:1px solid #27272a;border-radius:12px;padding:14px}video{display:block;width:100%;aspect-ratio:1;background:#000}
.slots{display:grid;grid-template-columns:repeat(auto-fit,minmax(92px,1fr));gap:8px;margin:12px 0}.slot{padding:5px;border:1px solid #3f3f46;background:#18181b;color:#fafafa;border-radius:8px;cursor:pointer}.slot img{display:block;width:100%;border-radius:5px}.slot.active{border-color:#f59e0b;color:#fbbf24}.slot.locked{cursor:default}.cycle{display:block;width:190px;max-width:100%;margin:10px auto;border:1px solid #3f3f46;border-radius:8px}
.candidate{display:flex;flex-wrap:wrap;max-width:340px;gap:3px;align-items:center}.candidate img{width:54px;display:block}.candidate strong{flex-basis:100%;text-align:left}.candidate.unsafe{border-color:#ef4444;color:#fecaca}
.actions{display:flex;gap:8px;flex-wrap:wrap}button{border:1px solid #3f3f46;background:#27272a;color:#fafafa;padding:8px 10px;border-radius:8px;cursor:pointer}.status{font-size:13px;color:#a1a1aa;margin-top:10px;word-break:break-all}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(116px,1fr));gap:8px}.frame{border:2px solid transparent;background:#111113;padding:0;position:relative}.frame img{width:100%;display:block}.frame.selected{border-color:#f59e0b}.frame.active{outline:2px solid #38bdf8}.frame.unsafe::after{content:'BORDE';position:absolute;top:5px;right:5px;background:#b91c1c;color:#fff;padding:2px 5px;border-radius:4px;font-weight:700;font-size:10px}.badge{position:absolute;top:5px;left:5px;background:#f59e0b;color:#111;padding:2px 5px;border-radius:4px;font-weight:700;font-size:11px}
@media(max-width:850px){.layout{grid-template-columns:1fr}header{position:static}}
</style></head><body>
<header><h1>Selector de frames · __STATE__</h1><div>Video completo a <b id="fps"></b> FPS. Frame 0 queda bloqueado; cambia los otros frames sin regenerar.</div></header>
<main class="layout"><section class="panel"><video id="video" controls muted loop></video><img id="cycle" class="cycle" alt="Preview del ciclo"><div id="slots" class="slots"></div><h2 style="font-size:14px">Ciclos candidatos</h2><div id="candidates" class="actions"></div><div class="actions" style="margin-top:12px"><button id="copy">Copiar comando</button><button id="download">Descargar selección JSON</button><button id="reset">Restaurar automática</button></div><div id="status" class="status"></div></section><section><div id="grid" class="grid"></div></section></main>
<script>const data=__DATA__;let selected=[...data.selected];let active=1,cycleFrame=0;const video=document.querySelector('#video'),grid=document.querySelector('#grid'),slots=document.querySelector('#slots'),status=document.querySelector('#status'),cycle=document.querySelector('#cycle');video.src=data.videoUrl;document.querySelector('#fps').textContent=data.fps.toFixed(3);
function seek(i){video.currentTime=i/data.fps;video.pause()}
function isUnsafe(frame,slot){return data.unsafeFrames.includes(frame)&&!(data.exactFirstFramePreserved&&data.exactIdleSlots.includes(slot))}function render(){slots.innerHTML='';selected.forEach((frame,i)=>{const b=document.createElement('button');b.className='slot '+(i===active?'active ':'')+(i===0?'locked':'');const shown=data.exactIdleSlots.includes(i)?0:frame;b.innerHTML=`<img src="${data.thumbnails[shown]}"><span>${i+1}: #${frame}${data.exactIdleSlots.includes(i)?' · idle exacto':''}${isUnsafe(frame,i)?' · TOCA BORDE':''}</span>`;if(i>0)b.onclick=()=>{active=i;seek(frame);render()};slots.append(b)});document.querySelectorAll('.frame').forEach((el,i)=>{el.classList.toggle('selected',selected.includes(i));el.classList.toggle('active',selected[active]===i);const badge=el.querySelector('.badge');if(badge)badge.remove();const slot=selected.indexOf(i);if(slot>=0){const x=document.createElement('span');x.className='badge';x.textContent=slot+1;el.append(x)}});const unsafe=selected.filter((frame,slot)=>isUnsafe(frame,slot));status.textContent='Índices: '+selected.join(', ')+(unsafe.length?' · ADVERTENCIA borde: '+unsafe.join(', '):' · márgenes fuente seguros')+' · '+data.commandPrefix+'"'+selected.join(',')+'" --force'}
data.candidates.forEach(c=>{const unsafe=c.indices.filter((frame,slot)=>isUnsafe(frame,slot));const b=document.createElement('button');b.className='candidate'+(unsafe.length?' unsafe':'');b.innerHTML=`<strong>#${c.rank} · score ${c.score}${unsafe.length?' · borde '+unsafe.join(', '):' · seguro'}</strong>`+c.indices.map((i,slot)=>`<img src="${data.thumbnails[data.exactIdleSlots.includes(slot)?0:i]}" alt="Frame ${i}">`).join('');b.onclick=()=>{selected=[...c.indices];active=1;seek(selected[1]);render()};document.querySelector('#candidates').append(b)});data.thumbnails.forEach((src,i)=>{const b=document.createElement('button');b.className='frame'+(data.unsafeFrames.includes(i)?' unsafe':'');b.innerHTML=`<img loading="lazy" src="${src}" alt="Frame ${i}">`;b.onclick=()=>{seek(i);if(i===0){active=0}else if(selected.includes(i)){active=selected.indexOf(i)}else{selected[active]=i;selected=[selected[0],...selected.slice(1).sort((a,b)=>a-b)];active=selected.indexOf(i)}render()};grid.append(b)});setInterval(()=>{const slot=cycleFrame++%selected.length;const index=data.exactIdleSlots.includes(slot)?0:selected[slot];cycle.src=data.thumbnails[index]},125);
document.querySelector('#copy').onclick=async()=>{await navigator.clipboard.writeText(data.commandPrefix+'"'+selected.join(',')+'" --force');status.textContent='Comando copiado.'};document.querySelector('#download').onclick=()=>{const blob=new Blob([JSON.stringify({state:data.state,sample_indices:selected,fps:data.fps},null,2)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`${data.state}-frame-selection.json`;a.click();URL.revokeObjectURL(a.href)};document.querySelector('#reset').onclick=()=>{selected=[...data.selected];active=1;render()};render();</script></body></html>"""
    html = html.replace("__STATE__", state).replace("__STATE__", state).replace("__DATA__", encoded)
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(output_path, html)
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
    }
    atomic_write_text(evidence_path, json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    return {
        "status": "pass",
        "output": str(output_path),
        "evidence": str(evidence_path),
        "frames": len(thumbnails),
        "fps": fps,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--source-report", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        result = build_selector(
            run_dir=args.run_dir,
            state=args.state,
            source_report=args.source_report,
            force=args.force,
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "operational-error", "errors": [str(exc)]}, ensure_ascii=False))
        return 3
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
