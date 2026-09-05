#!/usr/bin/env python3
"""Download immutable checkpoints separately from runtime installation."""
import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--profile", choices=("standard", "light"), default="standard")
    args = parser.parse_args()
    cache = args.cache_dir.resolve()
    os.environ["HF_HOME"] = str(cache)
    from huggingface_hub import HfApi, snapshot_download
    models = {"vision": f"Qwen/Qwen3-VL-{'4B' if args.profile == 'standard' else '2B'}-Instruct",
              "mask": "facebook/sam2.1-hiera-small"}
    receipt = {"schemaVersion": "item-model-checkpoints-v1", "profile": args.profile, "models": {}}
    for role, name in models.items():
        revision = HfApi().model_info(name).sha
        folder = snapshot_download(name, revision=revision, cache_dir=str(cache / "hub"),
            allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "*.jinja"])
        receipt["models"][role] = {"id": name, "revision": revision,
            "snapshot": Path(folder).relative_to(cache).as_posix()}
    cache.mkdir(parents=True, exist_ok=True)
    output = cache / f"checkpoints-{args.profile}.json"
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(receipt, indent=2)+"\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({"status": "pass", "receipt": str(output)}))


if __name__ == "__main__":
    main()
