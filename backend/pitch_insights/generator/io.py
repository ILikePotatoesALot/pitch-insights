"""Reading and writing match files (JSON Lines: match_meta first, then events)."""

from __future__ import annotations

import json
from pathlib import Path


def write_match(out_dir: str | Path, meta: dict, events: list[dict], debug: dict | None = None,
                name: str | None = None) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = name or meta["match"]["id"]
    path = out_dir / f"{stem}.jsonl"
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    if debug is not None:
        (out_dir / f"{stem}.debug.json").write_text(json.dumps(debug, indent=2, ensure_ascii=False),
                                                    encoding="utf-8", newline="\n")
    return path


def read_match(path: str | Path) -> tuple[dict, list[dict]]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    meta = json.loads(lines[0])
    return meta, [json.loads(line) for line in lines[1:] if line.strip()]
