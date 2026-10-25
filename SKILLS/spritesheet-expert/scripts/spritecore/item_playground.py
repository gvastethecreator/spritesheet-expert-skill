"""Build a portable, manifest-driven item-atlas curation playground.

The playground is one self-contained HTML file: every atlas page and QA preview
is embedded as a data URI, so the artifact renders from any location without a
server. Review decisions made in the browser export an ``item-review-v1``
document that ``apply_item_review.py`` accepts; the playground never mutates
the run itself.
"""

from __future__ import annotations

from base64 import b64encode
from io import BytesIO
import json
import posixpath
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from PIL import Image

from spritecore.paths import PathSafetyError, resolve_run_path


class ItemPlaygroundError(ValueError):
    """Raised before mutation when the playground cannot be built honestly."""


DEFAULT_OUTPUT = "qa/item-playground/index.html"
DEFAULT_REPORT = "qa/item-playground/playground.evidence.json"
PREVIEW_KEYS = (
    ("sourceComponents", "Source components"),
    ("atlasGrid", "Atlas grid"),
    ("pendingMask", "Pending mask"),
    ("discardedMask", "Discarded mask"),
)
FLAG_LABELS = {
    "touching_source_edge": "touches source edge",
    "small_instance_review": "small instance",
    "high_weak_alpha_ratio": "high weak alpha",
    "sparse_shape_review": "sparse shape",
    "neighbor_alpha_conflict": "neighbor conflict",
    "low_classification_confidence": "low confidence",
    "replacement_imported": "replacement imported",
}


def _digest(content: bytes) -> str:
    from hashlib import sha256

    return sha256(content).hexdigest()


def _portable_output(run_dir: Path, value: str, suffix: str) -> Path:
    if "\\" in value or not value.startswith("qa/item-playground/"):
        raise ItemPlaygroundError(
            "item playground outputs must use portable paths under qa/item-playground/"
        )
    try:
        output = resolve_run_path(run_dir, value)
    except PathSafetyError as exc:
        raise ItemPlaygroundError(str(exc)) from exc
    if output.suffix.lower() != suffix:
        raise ItemPlaygroundError(f"item playground output must use {suffix}")
    return output


def _relative_href(output_path: Path, target: Path) -> str:
    relative = posixpath.relpath(target.as_posix(), start=output_path.parent.as_posix())
    return str(PurePosixPath(relative))


def _source_record(run_dir: Path, path: Path, role: str) -> dict[str, Any]:
    content = path.read_bytes()
    return {
        "role": role,
        "path": path.relative_to(run_dir).as_posix(),
        "sha256": _digest(content),
        "size_bytes": len(content),
    }


def _data_uri(payload: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{b64encode(payload).decode('ascii')}"


def _preview_image(path: Path, max_width: int) -> bytes:
    """Downscale a QA preview so the HTML stays movable; never upscale."""
    with Image.open(path) as opened:
        image = opened.copy()
    if image.width > max_width:
        scale = max_width / image.width
        image = image.resize((max_width, max(1, round(image.height * scale))), Image.NEAREST)
    encoded = BytesIO()
    image.save(encoded, format="PNG")
    return encoded.getvalue()


def _manifest_pages(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    pages = manifest.get("pages") or [manifest["atlas"]]
    if not isinstance(pages, list) or not pages:
        raise ItemPlaygroundError("manifest declares no atlas pages")
    primary = manifest["atlas"]
    resolved = []
    for index, page in enumerate(pages):
        if not isinstance(page, Mapping) or not isinstance(page.get("path"), str):
            raise ItemPlaygroundError("atlas page record is invalid")
        resolved.append(
            {
                "id": page.get("id") or primary.get("id") or ("atlas" if index == 0 else f"page-{index}"),
                "path": page["path"],
                "width": page.get("width"),
                "height": page.get("height"),
            }
        )
    return resolved


def prepare_playground(
    *,
    run_dir: Path,
    manifest_name: str = "manifest.json",
    output_name: str = DEFAULT_OUTPUT,
    report_name: str = DEFAULT_REPORT,
    force: bool = False,
    preview_max_width: int = 900,
) -> tuple[Path, Path, bytes, dict[str, Any]]:
    """Validate sources and return output bytes/report without mutating the run."""

    if preview_max_width < 64:
        raise ItemPlaygroundError("preview width budget is too small")
    run_root = Path(run_dir).expanduser().resolve()
    if not run_root.is_dir():
        raise ItemPlaygroundError(f"run directory does not exist: {run_root}")
    try:
        manifest_path = resolve_run_path(run_root, manifest_name)
    except PathSafetyError as exc:
        raise ItemPlaygroundError(str(exc)) from exc
    if not manifest_path.is_file():
        raise ItemPlaygroundError(f"manifest does not exist: {manifest_name}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("schemaVersion") != "deterministic-item-sheet-v1"
        or manifest.get("kind") != "deterministic-item-atlas"
    ):
        raise ItemPlaygroundError("manifest is not a deterministic item atlas")

    output_path = _portable_output(run_root, output_name, ".html")
    report_path = _portable_output(run_root, report_name, ".json")
    if output_path == report_path or output_path == manifest_path:
        raise ItemPlaygroundError("item playground outputs cannot overwrite sources")
    if not force:
        collisions = [path for path in (output_path, report_path) if path.exists()]
        if collisions:
            raise ItemPlaygroundError(
                "item playground output already exists; pass --force to replace known outputs"
            )

    manifest_root = manifest_path.parent
    pages: list[dict[str, Any]] = []
    page_images: dict[str, Image.Image] = {}
    for page in _manifest_pages(manifest):
        try:
            page_path = resolve_run_path(manifest_root, page["path"])
        except PathSafetyError as exc:
            raise ItemPlaygroundError(f"atlas page escapes the run: {page['path']}") from exc
        if not page_path.is_file():
            raise ItemPlaygroundError(f"atlas page does not exist: {page['path']}")
        try:
            with Image.open(page_path) as opened:
                opened.verify()
            with Image.open(page_path) as opened:
                actual = opened.size
        except (OSError, ValueError) as exc:
            raise ItemPlaygroundError(f"atlas page is not a decodable image: {page['path']}") from exc
        expected = (page["width"], page["height"])
        if actual != expected:
            raise ItemPlaygroundError(
                f"atlas page {page['path']} dimensions {actual} do not match manifest {expected}"
            )
        pages.append({**page, "dataUri": _data_uri(page_path.read_bytes())})
        with Image.open(page_path) as opened:
            page_images[page["id"]] = opened.copy()
    page_by_id = {page["id"]: page for page in pages}
    primary_id = pages[0]["id"]

    items: list[dict[str, Any]] = []
    flags: dict[str, int] = {}
    for item in manifest.get("items", []):
        geometry = item.get("geometry", {})
        frame = geometry.get("frame")
        if not isinstance(frame, list) or len(frame) != 4:
            raise ItemPlaygroundError(f"item {item.get('id')} has no frame rectangle")
        page_id = geometry.get("pageId") or primary_id
        page = page_by_id.get(page_id)
        if page is None:
            raise ItemPlaygroundError(f"item {item.get('id')} references unknown page {page_id}")
        image = page_images[page_id]
        x, y, w, h = frame
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > image.width or y + h > image.height:
            raise ItemPlaygroundError(f"item {item.get('id')} frame escapes its atlas page")
        item_flags = list(item.get("qaFlags") or [])
        for flag in item_flags:
            flags[flag] = flags.get(flag, 0) + 1
        classification = item.get("classification", {})
        items.append(
            {
                "id": item["id"],
                "flags": item_flags,
                "status": (item.get("review") or {}).get("status", "pending"),
                "notes": (item.get("review") or {}).get("notes", ""),
                "size": geometry.get("originalSize"),
                "frame": frame,
                "pageId": page_id,
                "cellRect": geometry.get("cellRect"),
                "bbox": (item.get("source") or {}).get("bbox"),
                "strong": (item.get("source") or {}).get("strongPixels"),
                "weak": (item.get("source") or {}).get("weakPixels"),
                "assigned": (item.get("source") or {}).get("assignedPixels"),
                "pivot": geometry.get("pivot"),
                "classificationSource": classification.get("source", "unclassified"),
                "family": classification.get("family"),
                "type": classification.get("canonicalType"),
                "tags": list(classification.get("tags") or []),
            }
        )
    if not items:
        raise ItemPlaygroundError("manifest contains no items")

    previews: list[dict[str, Any]] = []
    evidence: list[dict[str, str]] = []
    evidence_block = manifest.get("evidence") or {}
    for key, label in PREVIEW_KEYS:
        relative = evidence_block.get(key)
        if not isinstance(relative, str):
            continue
        try:
            target = resolve_run_path(manifest_root, relative)
        except PathSafetyError:
            continue
        if not target.is_file():
            continue
        previews.append({"key": key, "label": label, "dataUri": _data_uri(_preview_image(target, preview_max_width))})
        evidence.append(
            {"label": label, "path": _relative_href(manifest_path, target), "href": _relative_href(output_path, target)}
        )

    completion = manifest.get("completion") or {}
    payload = {
        "runId": manifest.get("runId"),
        "manifestFilename": manifest_path.relative_to(run_root).as_posix(),
        "manifestSha256": _digest(manifest_path.read_bytes()),
        "sourceProvenance": (manifest.get("source") or {}).get("provenance"),
        "sourceSha256": (manifest.get("source") or {}).get("sha256"),
        "pages": pages,
        "previews": previews,
        "items": items,
        "stats": {
            "items": len(items),
            "flags": flags,
            "flagged": sum(1 for item in items if item["flags"]),
            "pendingPixels": completion.get("pendingPixels"),
            "classificationComplete": completion.get("classificationComplete", False),
        },
        "evidence": evidence,
        "flagLabels": FLAG_LABELS,
    }
    html_bytes = _render_html(payload).encode("utf-8")

    sources = [_source_record(run_root, manifest_path, "manifest")]
    sources.extend(
        _source_record(run_root, resolve_run_path(manifest_root, page["path"]), "atlas-page") for page in _manifest_pages(manifest)
    )
    fingerprint_payload = json.dumps(
        {"sources": sources},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    report = {
        "version": 1,
        "kind": "item-playground",
        "artifact": {
            "path": output_path.relative_to(run_root).as_posix(),
            "sha256": _digest(html_bytes),
            "size_bytes": len(html_bytes),
        },
        "counts": {"items": len(items), "pages": len(pages), "flags": flags},
        "manifest": {
            "path": manifest_path.relative_to(run_root).as_posix(),
            "sha256": payload["manifestSha256"],
            "runId": manifest.get("runId"),
        },
        "sources": sources,
        "evidence_links": evidence,
        "input_fingerprint": _digest(fingerprint_payload),
        "self_contained": True,
    }
    return output_path, report_path, html_bytes, report


def _render_html(data: Mapping[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return _HTML_TEMPLATE.replace("__TITLE__", "Item atlas playground").replace(
        "__RUN_ID__", str(data.get("runId") or "")
    ).replace("__PAYLOAD__", payload)


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>__TITLE__</title>
<style>
:root { color-scheme: dark; --ink:#f4f0e8; --muted:#a9a49b; --line:#393832; --panel:#171715; --accent:#ffbd59; --stage:#252522; --ok:#7bd88f; --bad:#ff7a6b; --warn:#e8c66b; }
* { box-sizing:border-box; scrollbar-width:thin; scrollbar-color:var(--line) #0d0d0c; }
*::-webkit-scrollbar { width:10px; height:10px; }
*::-webkit-scrollbar-track { background:#0d0d0c; }
*::-webkit-scrollbar-thumb { background:var(--line); border:2px solid #0d0d0c; border-radius:999px; }
body { margin:0; min-width:320px; background:#0d0d0c; color:var(--ink); font:14px/1.45 ui-monospace, SFMono-Regular, Consolas, monospace; }
button, select, input, textarea { font:inherit; }
button, select { color:var(--ink); background:#22221f; border:1px solid var(--line); border-radius:5px; }
button { min-height:32px; padding:5px 10px; cursor:pointer; }
button:hover, select:focus-visible, input:focus-visible, textarea:focus-visible { border-color:var(--accent); outline:2px solid transparent; }
input[type="search"] { min-height:32px; padding:5px 9px; background:#22221f; border:1px solid var(--line); border-radius:5px; color:var(--ink); }
header { padding:18px 22px 14px; border-bottom:1px solid var(--line); }
.eyebrow { margin:0 0 5px; color:var(--accent); font-size:11px; letter-spacing:.14em; text-transform:uppercase; }
h1 { margin:0; font:600 clamp(18px, 2.6vw, 26px)/1.1 ui-sans-serif, system-ui, sans-serif; letter-spacing:-.03em; word-break:break-all; }
.stats { display:flex; flex-wrap:wrap; gap:8px 18px; margin-top:10px; color:var(--muted); font-size:12px; }
.stats b { color:var(--ink); font-weight:600; }
.toolbar { display:flex; flex-wrap:wrap; align-items:center; gap:8px; padding:12px 22px; border-bottom:1px solid var(--line); position:sticky; top:0; background:#0d0d0cEE; backdrop-filter:blur(4px); z-index:5; }
.toolbar .gap { flex:1; }
.toolbar select { min-height:32px; padding:5px 24px 5px 8px; }
.chip { min-height:26px; padding:3px 9px; font-size:12px; border-radius:999px; }
.chip[aria-pressed="true"] { color:#15120d; background:var(--accent); border-color:var(--accent); }
.progress { color:var(--muted); font-size:12px; }
main { display:grid; grid-template-columns:minmax(0,1fr) 340px; min-height:0; }
.cards { display:grid; grid-template-columns:repeat(auto-fill, minmax(148px,1fr)); gap:10px; padding:16px 22px 24px; align-content:start; }
.card { display:grid; justify-items:center; gap:6px; padding:10px 8px 8px; background:var(--panel); border:1px solid var(--line); border-radius:8px; cursor:pointer; text-align:center; }
.card:hover { border-color:var(--accent); }
.card[aria-current="true"] { border-color:var(--accent); box-shadow:0 0 0 1px var(--accent); }
.card .thumb { display:grid; place-items:center; width:100%; height:104px; border-radius:5px; background:#333026; background-image:linear-gradient(45deg,#2c2c29 25%,transparent 25%),linear-gradient(-45deg,#2c2c29 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#2c2c29 75%),linear-gradient(-45deg,transparent 75%,#2c2c29 75%); background-position:0 0,0 8px,8px -8px,-8px 0; background-size:16px 16px; overflow:hidden; }
.card canvas { image-rendering:pixelated; image-rendering:crisp-edges; max-width:100%; max-height:100px; }
.card .id { font-size:10px; color:var(--muted); word-break:break-all; }
.card .dims { font-size:11px; }
.card .marks { display:flex; flex-wrap:wrap; gap:4px; justify-content:center; min-height:16px; }
.mark { font-size:9px; padding:1px 6px; border-radius:999px; border:1px solid var(--line); color:var(--warn); }
.mark.approved { color:var(--ok); border-color:var(--ok); }
.mark.rejected { color:var(--bad); border-color:var(--bad); }
aside { border-left:1px solid var(--line); background:var(--panel); padding:16px; display:flex; flex-direction:column; gap:14px; }
.stage { display:grid; place-items:center; min-height:280px; overflow:auto; border:1px solid var(--line); border-radius:8px; }
.stage[data-background="checker"] { background-image:linear-gradient(45deg,#333 25%,transparent 25%),linear-gradient(-45deg,#333 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#333 75%),linear-gradient(-45deg,transparent 75%,#333 75%); background-position:0 0,0 8px,8px -8px,-8px 0; background-size:16px 16px; }
.stage[data-background="black"] { background:#000; }
.stage[data-background="gray"] { background:#808080; }
.stage[data-background="white"] { background:#fff; }
.stage canvas { image-rendering:pixelated; image-rendering:crisp-edges; }
.meta { display:grid; grid-template-columns:auto 1fr; gap:4px 12px; font-size:12px; }
.meta dt { color:var(--muted); }
.meta dd { margin:0; word-break:break-all; }
.decision { display:flex; gap:6px; }
.decision button { flex:1; }
.decision button[aria-pressed="true"] { color:#15120d; background:var(--accent); border-color:var(--accent); }
.decision button[data-status="approved"][aria-pressed="true"] { background:var(--ok); border-color:var(--ok); }
.decision button[data-status="rejected"][aria-pressed="true"] { background:var(--bad); border-color:var(--bad); }
textarea { width:100%; min-height:56px; resize:vertical; background:#22221f; border:1px solid var(--line); border-radius:5px; color:var(--ink); padding:7px 9px; }
.controls { display:flex; flex-wrap:wrap; gap:6px; }
details.previews { border:1px solid var(--line); border-radius:8px; padding:10px; }
details.previews summary { cursor:pointer; color:var(--muted); }
details.previews img { display:block; width:100%; margin-top:8px; border:1px solid var(--line); border-radius:5px; image-rendering:pixelated; }
.evidence-list { list-style:none; margin:0; padding:0; font-size:12px; }
.evidence-list a { color:var(--ink); text-decoration:none; }
.evidence-list a:hover { color:var(--accent); }
.apply-box { border:1px solid var(--line); border-radius:8px; padding:10px; font-size:12px; }
.apply-box code { display:block; margin-top:6px; padding:8px; background:#0d0d0c; border:1px solid var(--line); border-radius:5px; white-space:pre-wrap; word-break:break-all; color:var(--accent); }
.hint { color:var(--muted); font-size:11px; }
.empty { color:var(--muted); font-style:italic; padding:22px; }
.atlas-source { display:none; }
kbd { border:1px solid var(--line); border-bottom-width:2px; border-radius:3px; padding:0 4px; font-size:11px; }
@media (max-width:900px) { main { grid-template-columns:1fr; } aside { border-left:0; border-top:1px solid var(--line); } }
</style>
</head>
<body>
<header>
  <p class="eyebrow">Deterministic item atlas</p>
  <h1>__RUN_ID__</h1>
  <div class="stats" id="stats"></div>
</header>
<div class="toolbar">
  <input type="search" id="query" placeholder="Filter by item id" aria-label="Filter by item id" style="min-width:180px">
  <select id="status-filter" aria-label="Filter by decision">
    <option value="all">All decisions</option>
    <option value="pending">Pending</option>
    <option value="approved">Approved</option>
    <option value="rejected">Rejected</option>
    <option value="flagged">Flagged only</option>
  </select>
  <select id="sort" aria-label="Sort items">
    <option value="default">Manifest order</option>
    <option value="area-desc">Area: large to small</option>
    <option value="area-asc">Area: small to large</option>
    <option value="id">Item id</option>
  </select>
  <button class="chip" id="bulk-approve" title="Approve every item passing the current filters">Approve shown</button>
  <button class="chip" id="bulk-reset">Reset shown</button>
  <span class="gap"></span>
  <span class="progress" id="progress"></span>
  <button id="export" style="border-color:var(--accent); color:var(--accent)">Export item-review.json</button>
</div>
<main>
  <section aria-label="Item grid">
    <div class="cards" id="cards"></div>
    <p class="empty" id="empty" hidden>No items match the current filters.</p>
  </section>
  <aside aria-label="Selected item">
    <div class="stage" data-background="checker" id="stage"><canvas id="detail-canvas" role="img" alt="Selected item"></canvas></div>
    <div class="controls">
      <button id="prev" aria-label="Previous item">&#8592;</button>
      <button id="next" aria-label="Next item">&#8594;</button>
      <select id="zoom" aria-label="Zoom"><option value="1">1x</option><option value="2">2x</option><option value="4">4x</option><option value="8">8x</option></select>
      <select id="background" aria-label="Background">
        <option value="checker">Checker</option><option value="black">Black</option><option value="gray">Gray</option><option value="white">White</option>
      </select>
    </div>
    <dl class="meta" id="meta"></dl>
    <div class="decision" role="group" aria-label="Review decision">
      <button data-status="pending">Pending</button>
      <button data-status="approved">Approve</button>
      <button data-status="rejected">Reject</button>
    </div>
    <textarea id="notes" placeholder="Notes for this item (kept in the exported review)"></textarea>
    <details class="previews" id="previews"><summary>Sheet previews</summary></details>
    <ul class="evidence-list" id="evidence"></ul>
    <div class="apply-box">
      Apply the exported review, then validate the successor:
      <code id="apply-command"></code>
      <p class="hint">Undecided items stay <b>pending</b>; applying them requires <b>--allow-pending</b> or a full decision set. The playground never edits the run.</p>
    </div>
    <p class="hint"><kbd>&#8592;</kbd><kbd>&#8594;</kbd> move &#183; <kbd>A</kbd> approve &#183; <kbd>X</kbd> reject &#183; <kbd>P</kbd> pending</p>
  </aside>
</main>
<div id="page-images" class="atlas-source"></div>
<script type="application/json" id="playground-data">__PAYLOAD__</script>
<script>
(() => {
  'use strict';
  const data = JSON.parse(document.getElementById('playground-data').textContent);
  const pageBox = document.getElementById('page-images');
  const pages = {};
  data.pages.forEach(page => {
    const img = document.createElement('img');
    img.src = page.dataUri; img.alt = '';
    pageBox.append(img);
    pages[page.id] = img;
  });
  const decisions = new Map(data.items.map(item => [item.id, { status: item.status || 'pending', notes: item.notes || '' }]));
  const cardsBox = document.getElementById('cards');
  const emptyBox = document.getElementById('empty');
  const statsBox = document.getElementById('stats');
  const progressBox = document.getElementById('progress');
  const stage = document.getElementById('stage');
  const detailCanvas = document.getElementById('detail-canvas');
  const detailContext = detailCanvas.getContext('2d');
  const metaBox = document.getElementById('meta');
  const notesBox = document.getElementById('notes');
  const queryBox = document.getElementById('query');
  const statusFilter = document.getElementById('status-filter');
  const sortBox = document.getElementById('sort');
  const zoomBox = document.getElementById('zoom');
  const backgroundBox = document.getElementById('background');
  const decisionButtons = Array.from(document.querySelectorAll('.decision button'));
  let selected = data.items[0].id;
  let visible = data.items.slice();

  function decisionOf(id) { return decisions.get(id); }
  function itemById(id) { return data.items.find(item => item.id === id); }
  function counts() {
    const summary = { pending: 0, approved: 0, rejected: 0, replace: 0, regenerate: 0 };
    decisions.forEach(entry => { summary[entry.status] = (summary[entry.status] || 0) + 1; });
    return summary;
  }
  function area(item) { return (item.size ? item.size[0] * item.size[1] : 0); }
  function visibleItems() {
    const query = queryBox.value.trim().toLowerCase();
    const mode = statusFilter.value;
    let list = data.items.filter(item => {
      if (query && !item.id.toLowerCase().includes(query)) return false;
      const status = decisionOf(item.id).status;
      if (mode === 'flagged') return item.flags.length > 0;
      if (mode !== 'all' && status !== mode) return false;
      return true;
    });
    if (sortBox.value === 'area-desc') list = list.slice().sort((a, b) => area(b) - area(a));
    else if (sortBox.value === 'area-asc') list = list.slice().sort((a, b) => area(a) - area(b));
    else if (sortBox.value === 'id') list = list.slice().sort((a, b) => a.id.localeCompare(b.id));
    return list;
  }
  function drawThumb(canvas, item) {
    const source = pages[item.pageId];
    const frame = item.frame;
    canvas.width = frame[2]; canvas.height = frame[3];
    const context = canvas.getContext('2d');
    context.clearRect(0, 0, frame[2], frame[3]);
    context.drawImage(source, frame[0], frame[1], frame[2], frame[3], 0, 0, frame[2], frame[3]);
  }
  function flagLabel(flag) { return data.flagLabels[flag] || flag; }
  function renderCards() {
    visible = visibleItems();
    cardsBox.replaceChildren();
    emptyBox.hidden = visible.length > 0;
    const pending = document.createDocumentFragment();
    visible.forEach(item => {
      const card = document.createElement('button');
      card.type = 'button'; card.className = 'card'; card.dataset.id = item.id;
      card.setAttribute('aria-current', String(item.id === selected));
      const thumb = document.createElement('div'); thumb.className = 'thumb';
      const canvas = document.createElement('canvas');
      thumb.append(canvas);
      const dims = document.createElement('div'); dims.className = 'dims';
      dims.textContent = item.size ? item.size[0] + ' x ' + item.size[1] : '';
      const id = document.createElement('div'); id.className = 'id'; id.textContent = item.id;
      const marks = document.createElement('div'); marks.className = 'marks';
      const status = decisionOf(item.id).status;
      if (status !== 'pending') {
        const mark = document.createElement('span'); mark.className = 'mark ' + status; mark.textContent = status;
        marks.append(mark);
      }
      item.flags.forEach(flag => {
        const mark = document.createElement('span'); mark.className = 'mark'; mark.title = flag; mark.textContent = flagLabel(flag);
        marks.append(mark);
      });
      card.append(thumb, dims, marks, id);
      card.addEventListener('click', () => { selected = item.id; render(); });
      pending.append(card);
      drawThumb(canvas, item);
    });
    cardsBox.append(pending);
  }
  function renderStats() {
    const summary = counts();
    const flagged = data.stats.flagged;
    statsBox.replaceChildren();
    const add = (label, value) => {
      const span = document.createElement('span');
      span.innerHTML = label.replace('__V__', '<b>' + value + '</b>');
      statsBox.append(span);
    };
    add('items <b>__V__</b>', data.stats.items);
    add('flagged <b>__V__</b>', flagged);
    add('pending px <b>__V__</b>', data.stats.pendingPixels == null ? 'n/a' : data.stats.pendingPixels);
    add('pages <b>__V__</b>', data.pages.length);
    add('classification <b>__V__</b>', data.stats.classificationComplete ? 'complete' : 'unclassified');
    add('source <b>__V__</b>', data.sourceProvenance || 'n/a');
    progressBox.textContent = 'reviewed ' + (summary.approved + summary.rejected) + ' / ' + data.stats.items;
  }
  function renderDetail() {
    const item = itemById(selected);
    if (!item) { metaBox.replaceChildren(); return; }
    const source = pages[item.pageId];
    const frame = item.frame;
    detailCanvas.width = frame[2]; detailCanvas.height = frame[3];
    const zoom = Number(zoomBox.value);
    detailCanvas.style.width = frame[2] * zoom + 'px';
    detailCanvas.style.height = frame[3] * zoom + 'px';
    detailContext.clearRect(0, 0, frame[2], frame[3]);
    detailContext.drawImage(source, frame[0], frame[1], frame[2], frame[3], 0, 0, frame[2], frame[3]);
    if (item.pivot) {
      detailContext.fillStyle = 'rgba(255,189,89,.85)';
      const px = Math.round(item.pivot[0] * frame[2]) - .5;
      const py = Math.round(item.pivot[1] * frame[3]) - .5;
      detailContext.fillRect(px, 0, 1, frame[3]);
      detailContext.fillRect(0, py, frame[2], 1);
    }
    const rows = [
      ['item id', item.id],
      ['native', item.size ? item.size.join(' x ') : ''],
      ['frame (atlas)', frame.join(', ')],
      ['cellRect', item.cellRect ? item.cellRect.join(', ') : ''],
      ['source bbox', item.bbox ? item.bbox.join(', ') : ''],
      ['pixels', item.assigned != null ? 'assigned ' + item.assigned + ' / strong ' + item.strong + ' / weak ' + item.weak : ''],
      ['classification', item.classificationSource === 'unclassified' ? 'unclassified' : [item.family, item.type].filter(Boolean).join(' / ') + (item.tags.length ? ' [' + item.tags.join(', ') + ']' : '')],
    ];
    metaBox.replaceChildren();
    rows.forEach(([label, value]) => {
      const dt = document.createElement('dt'); dt.textContent = label;
      const dd = document.createElement('dd'); dd.textContent = value || '-';
      metaBox.append(dt, dd);
    });
    const entry = decisionOf(item.id);
    decisionButtons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.status === entry.status)));
    notesBox.value = entry.notes;
    notesBox.disabled = false;
  }
  function applyCommand() {
    const summary = counts();
    const pending = summary.pending > 0;
    const run = '<run-dir>';
    return 'python SKILLS/spritesheet-expert/scripts/apply_item_review.py'
      + ' --manifest ' + run + '/' + data.manifestFilename
      + ' --review ' + run + '/item-review.json'
      + ' --output-dir ' + run + '/reviewed'
      + (pending ? ' --allow-pending' : '');
  }
  function renderEvidence() {
    const previews = document.getElementById('previews');
    data.previews.forEach(preview => {
      const img = document.createElement('img');
      img.src = preview.dataUri; img.alt = preview.label;
      previews.append(img);
    });
    if (!data.previews.length) previews.hidden = true;
    const list = document.getElementById('evidence');
    if (!data.evidence.length) { list.replaceChildren(); return; }
    data.evidence.forEach(entry => {
      const li = document.createElement('li');
      const link = document.createElement('a');
      link.href = entry.href; link.target = '_blank'; link.rel = 'noopener'; link.textContent = entry.label;
      li.append(link); list.append(li);
    });
    document.getElementById('apply-command').textContent = applyCommand();
  }
  function setStatus(id, status) {
    decisionOf(id).status = status;
    if (status === 'pending') { /* keep notes */ }
    render();
    const index = visible.findIndex(item => item.id === selected);
    if (status !== 'pending' && index >= 0 && index < visible.length - 1) { selected = visible[index + 1].id; render(); }
  }
  function render() {
    if (!itemById(selected)) selected = (visible[0] || data.items[0]).id;
    renderStats(); renderCards(); renderDetail();
  }
  function buildReview() {
    const summary = counts();
    return {
      schemaVersion: 'item-review-v1',
      kind: 'deterministic-item-review',
      reviewId: (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + '-playground'),
      runId: data.runId,
      sourceManifest: { filename: data.manifestFilename, sha256: data.manifestSha256 },
      createdAt: new Date().toISOString(),
      reviewer: { kind: 'human' },
      items: data.items.map(item => {
        const entry = decisionOf(item.id);
        return { itemId: item.id, status: entry.status, notes: entry.notes, classification: null, replacement: null };
      }),
      summary,
    };
  }
  queryBox.addEventListener('input', render);
  statusFilter.addEventListener('change', render);
  sortBox.addEventListener('change', render);
  zoomBox.addEventListener('change', renderDetail);
  backgroundBox.addEventListener('change', () => { stage.dataset.background = backgroundBox.value; });
  decisionButtons.forEach(button => button.addEventListener('click', () => setStatus(selected, button.dataset.status)));
  notesBox.addEventListener('input', () => { decisionOf(selected).notes = notesBox.value; });
  document.getElementById('prev').addEventListener('click', () => step(-1));
  document.getElementById('next').addEventListener('click', () => step(1));
  function step(delta) {
    const index = visible.findIndex(item => item.id === selected);
    if (index < 0) return;
    const next = visible[(index + delta + visible.length) % visible.length];
    selected = next.id; render();
  }
  document.getElementById('bulk-approve').addEventListener('click', () => {
    visibleItems().forEach(item => decisionOf(item.id).status = 'approved');
    render();
  });
  document.getElementById('bulk-reset').addEventListener('click', () => {
    visibleItems().forEach(item => { const original = itemById(item.id); decisionOf(item.id).status = original.status; });
    render();
  });
  document.getElementById('export').addEventListener('click', () => {
    const blob = new Blob([JSON.stringify(buildReview(), null, 2)], { type: 'application/json' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'item-review.json';
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 5000);
    document.getElementById('apply-command').textContent = applyCommand();
  });
  document.addEventListener('keydown', event => {
    if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLSelectElement) return;
    if (event.key === 'ArrowLeft') { event.preventDefault(); step(-1); }
    else if (event.key === 'ArrowRight') { event.preventDefault(); step(1); }
    else if (event.key.toLowerCase() === 'a') setStatus(selected, 'approved');
    else if (event.key.toLowerCase() === 'x') setStatus(selected, 'rejected');
    else if (event.key.toLowerCase() === 'p') setStatus(selected, 'pending');
  });
  function boot() { render(); renderEvidence(); }
  const unloaded = data.pages.map(page => pages[page.id]).filter(img => !img.complete);
  if (unloaded.length) {
    let remaining = unloaded.length;
    unloaded.forEach(img => img.addEventListener('load', () => { if (--remaining === 0) boot(); }, { once: true }));
  } else boot();
})();
</script>
</body>
</html>
"""

__all__ = ["ItemPlaygroundError", "prepare_playground", "DEFAULT_OUTPUT", "DEFAULT_REPORT"]
