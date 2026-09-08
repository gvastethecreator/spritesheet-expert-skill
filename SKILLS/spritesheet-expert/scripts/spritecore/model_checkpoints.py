"""Prepared local checkpoints; inference never resolves mutable remote refs."""
import json
import os
import re
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2]


def model_cache():
    if os.environ.get("SPRITE_MODEL_CACHE") or os.environ.get("HF_HOME"):
        return Path(os.environ.get("SPRITE_MODEL_CACHE") or os.environ["HF_HOME"]).resolve()
    config = SKILL / ".local/item-model-runtime.json"
    if config.exists():
        return Path(json.loads(config.read_text(encoding="utf-8"))["modelCacheDir"]).resolve()
    return SKILL / ".local/model-cache"


def checkpoint(profile, role, *, cache=None, model=None, revision=None):
    cache = Path(cache).resolve() if cache is not None else model_cache()
    receipt = json.loads((cache / f"checkpoints-{profile}.json").read_text(encoding="utf-8"))
    if receipt.get("schemaVersion") != "item-model-checkpoints-v1" or receipt.get("profile") != profile:
        raise ValueError("checkpoint receipt contract or profile mismatch")
    entry = receipt["models"][role]
    return verified_snapshot(entry, cache, model=model, revision=revision)


def verified_snapshot(entry, cache, *, model=None, revision=None):
    cache = Path(cache).resolve()
    if not isinstance(entry.get("revision"), str) or not re.fullmatch(r"[a-f0-9]{40}", entry["revision"]):
        raise ValueError("checkpoint revision must be an immutable commit")
    if model is not None and entry["id"] != model:
        raise ValueError("requested model differs from prepared checkpoint")
    if revision is not None and entry["revision"] != revision:
        raise ValueError("requested revision differs from prepared checkpoint")
    folder = (cache / entry["snapshot"]).resolve()
    if not folder.is_relative_to(cache) or not folder.is_dir():
        raise ValueError("missing or escaping checkpoint snapshot")
    if not (folder / "config.json").is_file() or not any(folder.glob("*.safetensors")):
        raise ValueError("checkpoint configuration or safetensors weights are missing")
    for index in folder.glob("*.safetensors.index.json"):
        shards = json.loads(index.read_text(encoding="utf-8"))["weight_map"].values()
        if any(Path(shard).name != shard or not (folder / shard).is_file() for shard in shards):
            raise ValueError("checkpoint shard is missing or unsafe")
    return {**entry, "path": str(folder)}


def capabilities(config_path):
    result = {"runtimePrepared": False, "modelProfiles": [], "backgroundModels": [], "errors": []}
    try:
        config = json.loads(Path(config_path).read_text(encoding="utf-8"))
        if not Path(config["python"]).is_file():
            raise ValueError("runtime Python is missing; rebuild the environment")
        result["runtimePrepared"] = True
        for profile in ("standard", "light", "lucida", "ben2"):
            try:
                for role in (("vision", "mask") if profile in {"standard", "light"} else ("background",)):
                    checkpoint(profile, role, cache=config["modelCacheDir"])
                if profile in {"standard", "light"}:
                    result["modelProfiles"].append(profile)
                elif profile in config.get("capabilities", []):
                    result["backgroundModels"].append(profile)
            except (ValueError, OSError, KeyError) as error:
                result["errors"].append(f"{profile}: {error}")
    except (ValueError, OSError, KeyError) as error:
        result["errors"].append(str(error))
    result["inferenceTested"] = False
    return result
