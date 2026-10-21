"""Write stored commentary for the sample matches with the agents.

    python scripts/generate_commentary.py                     # every sample in ../samples
    python scripts/generate_commentary.py comeback-POT-CAR    # one match
    python scripts/generate_commentary.py --force             # rewrite even if up to date
    python scripts/generate_commentary.py --limit 5           # first 5 moments only, printed, not saved

Moments already written from the same facts, by the same model and prompt version, are
kept, so re-running is cheap. Uses the provider in .env (LLM_PROVIDER). Stops without
saving if the provider refuses the key, access or deployment.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from pitch_insights.agents.desk import CommentaryDesk, ProviderConfigError, file_header, writer_from_settings
from pitch_insights.agents.prompts import input_hash
from pitch_insights.agents.settings import load_settings
from pitch_insights.agents.store import load_commentary, summarise, write_commentary
from pitch_insights.explain.moments import MatchBrain
from pitch_insights.generator.io import read_match

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


async def run_match(path: Path, writer, header: dict, force: bool, limit: int | None,
                    concurrency: int) -> dict:
    meta, events = read_match(path)
    brain = MatchBrain(meta)
    desk = CommentaryDesk(writer, meta)
    for ev in events:
        brain.update(ev)
    moments = [m for m in brain.moments if desk.wants(m)][:limit]
    old = load_commentary(path)
    reuse = not force and all(old.get(k) == header[k] for k in ("model", "prompt_version"))
    sem = asyncio.Semaphore(concurrency)

    async def one(m: dict) -> dict:
        kept = old["moments"].get(m["id"]) if reuse else None
        if kept and kept["status"] == "ok" and kept.get("input_hash") == input_hash(m, meta):
            return kept
        async with sem:
            return await desk.comment(m)

    records = list(await asyncio.gather(*(one(m) for m in moments)))
    s = summarise(records)
    line = (f"{path.stem}: {s['moments']} moments, {s['ok']} ok, {s['fallback']} fallback, "
            f"{s['retried']} retried, mean groundedness {s['grounding_mean']}")
    if limit is not None:  # a quick check: show the lines, keep the stored file as it is
        print(line + "  (not saved: --limit)")
        for r in records:
            print(f"  {r['moment_id']} {r['agent']} {r['status']}: {r['analyst']}")
        return s
    print(f"{line}  ->  {write_commentary(path, header, records).name}")
    return s


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*", help="sample names (default: all)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--verbose", action="store_true", help="log each agent run")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(message)s")

    settings = load_settings()
    writer = writer_from_settings(settings)
    header = file_header(writer)
    paths = [SAMPLES / f"{n}.jsonl" for n in args.names] if args.names else sorted(SAMPLES.glob("*.jsonl"))
    missing = [p.name for p in paths if not p.exists()]
    if missing:
        print("No such sample: " + ", ".join(missing))
        return 1
    try:
        for path in paths:
            await run_match(path, writer, header, args.force, args.limit, settings.concurrency)
    except ProviderConfigError as e:
        print(f"Stopped, nothing saved for {path.stem}: {e}")
        return 2
    finally:
        await writer.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
