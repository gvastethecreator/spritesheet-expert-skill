#!/usr/bin/env python3
"""Export a verified static-item atlas as TexturePacker-compatible JSON Hash.

Native crop size is the logical sprite size; reserved cellRect is NOT a frame.
This adapter does not turn item collections into animation timelines.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile

from spritecore.item_delivery import DeliveryError, artifact, validate_delivery


def export_atlas(manifest_path: Path, output_dir: Path, *, draft: bool = False,
                 max_texture_size: int = 16384) -> dict:
    manifest_path, output = manifest_path.resolve(), output_dir.resolve()
    root = manifest_path.parent
    if output.exists() or output.is_relative_to(root) or root.is_relative_to(output):
        raise DeliveryError("export must use a new directory outside the input run")
    report = validate_delivery(manifest_path, draft=draft, max_texture_size=max_texture_size)
    if report["status"] != "pass":
        raise DeliveryError(json.dumps(report, ensure_ascii=False))
    manifest_bytes = manifest_path.read_bytes()
    if sha256(manifest_bytes).hexdigest() != report["manifestSha256"]:
        raise DeliveryError("manifest changed during export")
    manifest = json.loads(manifest_bytes)
    atlas_path = artifact(root, manifest["atlas"]["path"])
    atlas_bytes = atlas_path.read_bytes()
    if sha256(atlas_bytes).hexdigest() != manifest["atlas"]["sha256"]:
        raise DeliveryError("atlas changed during export")
    frames = {}
    for item in manifest["items"]:
        x, y, w, h = item["geometry"]["frame"]
        px, py = item["geometry"]["pivot"]
        frames[item["id"]] = {"frame": {"x": x, "y": y, "w": w, "h": h},
            "rotated": False, "trimmed": False,
            "spriteSourceSize": {"x": 0, "y": 0, "w": w, "h": h},
            "sourceSize": {"w": w, "h": h}, "pivot": {"x": px, "y": py}}
    atlas_json = {"frames": frames, "meta": {"app": "Spritesheet Expert",
        "version": "item-json-hash-v1", "image": "atlas.png", "format": "RGBA8888",
        "size": {"w": manifest["atlas"]["width"], "h": manifest["atlas"]["height"]}, "scale": "1"}}
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    try:
        (staging / "atlas.png").write_bytes(atlas_bytes)
        (staging / "atlas.json").write_text(json.dumps(atlas_json, indent=2) + "\n", encoding="utf-8")
        # Audit snapshot, not a relocatable source-run manifest: crops remain in the parent run.
        (staging / "source-manifest.snapshot.json").write_bytes(manifest_bytes)
        (staging / "delivery-check.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        receipt = {"schemaVersion": "item-runtime-delivery-v1", "draft": draft,
            "format": "texturepacker-json-hash", "sourceManifestSha256": report["manifestSha256"],
            "engineSmokeTested": False, "animation": False,
            "files": {p.name: sha256(p.read_bytes()).hexdigest() for p in sorted(staging.iterdir())}}
        (staging / "delivery.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        (staging / "README.txt").write_text(
            "STATIC ITEM ATLAS\nLoad atlas.png with atlas.json using a JSON Hash atlas loader.\n"
            "Frame keys are stable item IDs, not ordinal cell numbers. Pivots are normalized to native crop size.\n"
            "source-manifest.snapshot.json is audit evidence, NOT a portable source run.\n"
            "No animation order, durations, collisions, or world-footprint contract is inferred.\n"
            "Run your target engine/device smoke test before shipping.\n"
            + ("DRAFT: review blockers are recorded in delivery-check.json. NOT APPROVED FOR PRODUCTION.\n" if draft else ""),
            encoding="utf-8")
        # No force mode: never remove a prior successful delivery.
        if output.exists():
            raise DeliveryError("export destination appeared while preparing output")
        staging.rename(output)
        return receipt
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--max-texture-size", type=int, default=16384)
    args = parser.parse_args()
    try:
        receipt = export_atlas(args.manifest, args.output_dir, draft=args.draft,
                               max_texture_size=args.max_texture_size)
        print(json.dumps({"status": "pass", "output": str(args.output_dir), **receipt}))
        return 0
    except (DeliveryError, OSError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
