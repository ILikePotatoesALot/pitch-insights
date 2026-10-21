"""Stored commentary: one JSON file per sample match, next to it in samples/.

    samples/comeback-POT-CAR.commentary.json

The replay server streams stored commentary, so the demo never waits on a model or hits
a rate limit. Each file records the provider, model and prompt version that wrote it.
"""

from __future__ import annotations

import json
from pathlib import Path


def commentary_path(match_path: Path) -> Path:
    return match_path.with_name(match_path.stem + ".commentary.json")


def load_commentary(match_path: Path) -> dict:
    """The stored file, or an empty one if there isn't one (or it can't be read)."""
    path = commentary_path(match_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"moments": {}}
    data.setdefault("moments", {})
    return data


def summarise(records: list[dict]) -> dict:
    ok = [r for r in records if r["status"] == "ok"]
    scores = [r["grounding"]["score"] for r in records if r.get("grounding")]
    return {
        "moments": len(records), "ok": len(ok), "fallback": len(records) - len(ok),
        "retried": sum(r["attempts"] > 1 for r in records),
        "grounding_mean": round(sum(scores) / len(scores), 3) if scores else None,
    }


def write_commentary(match_path: Path, header: dict, records: list[dict]) -> Path:
    path = commentary_path(match_path)
    data = header | {"match": match_path.stem, "summary": summarise(records),
                     "moments": {r["moment_id"]: r for r in records}}
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return path
