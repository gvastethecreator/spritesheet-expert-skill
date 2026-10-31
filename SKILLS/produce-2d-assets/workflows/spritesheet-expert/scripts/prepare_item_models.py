#!/usr/bin/env python3
"""Download immutable checkpoints separately from runtime installation."""
import argparse
import json
import os
import re
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--profile", choices=("standard", "light", "lucida", "ben2"), default="standard")
    parser.add_argument("--offline", action="store_true", help="check and reuse recorded snapshots without network access")
    args = parser.parse_args()
    cache = args.cache_dir.resolve()
    os.environ["HF_HOME"] = str(cache)
    from huggingface_hub import HfApi, snapshot_download
    models = {"vision": f"Qwen/Qwen3-VL-{'4B' if args.profile == 'standard' else '2B'}-Instruct",
              "mask": "facebook/sam2.1-hiera-small"}
    if args.profile in {"lucida", "ben2"}:
        models = {"background": "egeorcun/lucida" if args.profile == "lucida" else "PramaLLC/BEN2"}
    receipt_path = cache / f"checkpoints-{args.profile}.json"
    recorded = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.exists() else None
    if recorded and (recorded.get("schemaVersion") != "item-model-checkpoints-v1" or recorded.get("profile") != args.profile):
        raise ValueError("checkpoint receipt contract or profile mismatch")
    receipt = {"schemaVersion": "item-model-checkpoints-v1", "profile": args.profile, "models": {}}
    for role, name in models.items():
        if args.offline and recorded is None:
            raise ValueError("offline preparation requires a recorded checkpoint receipt")
        revision = (recorded["models"][role]["revision"] if recorded else
                    "6ee11122534c8de59402a589d2293c198cfbf848" if args.profile == "lucida" else HfApi().model_info(name).sha)
        if not re.fullmatch(r"[a-f0-9]{40}", revision) or (recorded and recorded["models"][role]["id"] != name):
            raise ValueError("checkpoint model or immutable revision mismatch")
        folder = snapshot_download(name, revision=revision, cache_dir=str(cache / "hub"),
            local_files_only=args.offline,
            allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "*.jinja", "*.py"])
        entry = {"id": name, "revision": revision, "snapshot": Path(folder).relative_to(cache).as_posix()}
        from spritecore.model_checkpoints import verified_snapshot
        verified_snapshot(entry, cache, model=name, revision=revision)
        receipt["models"][role] = entry
    cache.mkdir(parents=True, exist_ok=True)
    output = cache / f"checkpoints-{args.profile}.json"
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(receipt, indent=2)+"\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({"status": "pass", "receipt": str(output)}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "failed", "error": str(error)}))
        raise SystemExit(1)
