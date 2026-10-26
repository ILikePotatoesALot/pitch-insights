"""Stored commentary: one JSON file per sample match, next to it in samples/.

    samples/comeback-POT-CAR.commentary.json

The replay server streams stored commentary, so the demo never waits on a model or hits
a rate limit. Each file records the provider, model and prompt version that wrote it.
"""

from __future__ import annotations

import json
from pathlib import Path

from pitch_insights.agents.prompts import input_hash


def sibling_path(match_path: Path, suffix: str) -> Path:
    """A file stored next to a match: samples/<name><suffix>."""
    return match_path.with_name(match_path.stem + suffix)


def write_json(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return path


def commentary_path(match_path: Path) -> Path:
    return sibling_path(match_path, ".commentary.json")


def load_commentary(match_path: Path) -> dict:
    """The stored file, or an empty one if there isn't one (or it can't be read)."""
    path = commentary_path(match_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"moments": {}}
    data.setdefault("moments", {})
    return data


def with_commentary(moment: dict, stored: dict, meta: dict) -> dict:
    """The moment plus its stored commentary, if the agents wrote some from these same facts.
    Commentary written for different facts (the file is older than the code) is left out."""
    rec = stored["moments"].get(moment["id"])
    if not rec or rec.get("input_hash") != input_hash(moment, meta):
        return moment
    # A draft kept as `pending` hasn't passed the safety check: it never leaves the server.
    return moment | {"commentary": {k: v for k, v in rec.items() if k != "pending"}}


def commentary_info(stored: dict) -> dict | None:
    """Who wrote the stored commentary, for the app's AI-generated label (None when there is none)."""
    if not stored["moments"]:
        return None
    return {k: stored.get(k) for k in ("ai_generated", "provider", "model", "prompt_version", "summary")}


def summarise(records: list[dict]) -> dict:
    ok = [r for r in records if r["status"] == "ok"]
    scores = [r["grounding"]["score"] for r in records if r.get("grounding")]
    return {
        "moments": len(records), "ok": len(ok), "fallback": len(records) - len(ok),
        "retried": sum(r["attempts"] > 1 for r in records),
        "grounding_mean": round(sum(scores) / len(scores), 3) if scores else None,
        "safety_checked": sum(bool(r.get("safety")) for r in records),
        "safety_blocked": sum(bool(r.get("safety")) and not r["safety"]["passed"] for r in records),
    }


def write_commentary(match_path: Path, header: dict, records: list[dict]) -> Path:
    data = header | {"match": match_path.stem, "summary": summarise(records),
                     "moments": {r["moment_id"]: r for r in records}}
    return write_json(commentary_path(match_path), data)
