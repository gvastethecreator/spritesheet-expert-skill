"""Input-bound review scopes shared by writers and final delivery validation."""
from copy import deepcopy
from hashlib import sha256
import json

SCOPES = ("pixels", "semantics", "placement")


def fingerprints(item, source_hash):
    classification = item.get("classification", {})
    inputs = {
        "pixels": [source_hash, item["contentSha256"], item["source"]["bbox"]],
        "semantics": [item["contentSha256"], {k: v for k, v in classification.items()
            if k not in {"source", "confidence", "model", "revision", "notes"}}],
        "placement": item["geometry"],
    }
    return {scope: sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            for scope, value in inputs.items()}


def reconcile_review(item, source_hash, review, *, approve=()):
    """Retain only approvals whose scoped inputs still match the current item."""
    if any(scope not in SCOPES for scope in approve):
        raise ValueError("unknown review scope")
    result = deepcopy(review)
    old = result.get("scopes", {})
    result["scopes"] = {}
    for scope, fingerprint in fingerprints(item, source_hash).items():
        prior = old.get(scope, {})
        accepted = scope in approve or (prior.get("status") == "approved" and prior.get("inputSha256") == fingerprint)
        result["scopes"][scope] = {"status": "approved" if accepted else "pending", "inputSha256": fingerprint}
    if result.get("status") not in {"rejected", "replace", "regenerate"}:
        result["status"] = "approved" if all(s["status"] == "approved" for s in result["scopes"].values()) else "pending"
    return result


def stale_scopes(item, source_hash):
    scopes = item.get("review", {}).get("scopes", {})
    return [scope for scope, digest in fingerprints(item, source_hash).items()
            if scopes.get(scope, {}).get("status") != "approved" or scopes[scope].get("inputSha256") != digest]
