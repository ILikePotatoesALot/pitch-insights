"""Write stored commentary for the sample matches with the agents.

    python scripts/generate_commentary.py                     # every sample in ../samples
    python scripts/generate_commentary.py comeback-POT-CAR    # one match
    python scripts/generate_commentary.py 117093-38min_ft     # the real-footage clip, in samples/video/
    python scripts/generate_commentary.py --force             # rewrite even if up to date
    python scripts/generate_commentary.py --limit 5           # first 5 moments only, printed, not saved

Moments already written from the same facts, by the same provider, model and prompt version, are
kept, so re-running is cheap. Kept lines written before the safety check existed are screened
by Azure AI Content Safety without calling the model again. Uses the provider in .env
(LLM_PROVIDER). Stops without saving if the provider refuses the key, access or deployment.

The clip's moments (video/moments.py) go to the video narrator and its file, samples/video/<name>.commentary.json,
carries the video prompt version, so the synthetic matches' files stay as they are. With no names, every sample match
and every clip the app lists is done.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from pitch_insights.agents.desk import CommentaryDesk, ProviderConfigError, file_header, writer_from_settings
from pitch_insights.agents.memory import memory_for
from pitch_insights.agents.prompts import input_hash
from pitch_insights.agents.safety import safety_from_settings
from pitch_insights.agents.settings import load_settings
from pitch_insights.agents.store import load_commentary, summarise, write_commentary
from pitch_insights.agents.tracing import flush_tracing, setup_tracing
from pitch_insights.explain.moments import MatchBrain
from pitch_insights.generator.io import read_match
from pitch_insights.video.moments import load_clip_moments
from pitch_insights.video.replay import APP_CLIPS, CLIP_DIR, stored_path

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def is_clip(path: Path) -> bool:
    """A clip's stored files are named as if for `samples/video/<name>.jsonl` (see video.replay.stored_path)."""
    return path.parent.name == CLIP_DIR


def sample_paths(names: list[str]) -> list[Path]:
    """The samples to do: named ones (a sample match or a clip), or all of them."""
    if not names:
        return sorted(SAMPLES.glob("*.jsonl")) + [stored_path(SAMPLES, n) for n in APP_CLIPS]
    return [stored_path(SAMPLES, n) if (SAMPLES / CLIP_DIR / f"{n}.frames.jsonl").exists() else SAMPLES / f"{n}.jsonl"
            for n in names]


def exists(path: Path) -> bool:
    if path.stem == "continuous-prototype":
        return True
    return (SAMPLES / CLIP_DIR / f"{path.stem}.frames.jsonl").exists() if is_clip(path) else path.exists()


async def run_match(path: Path, writer, header: dict, force: bool, limit: int | None,
                    concurrency: int, safety=None) -> dict:
    if is_clip(path):  # moments from the detected events, written by the video narrator
        meta, all_moments = load_clip_moments(SAMPLES, path.stem)
        header = file_header(writer, video=True)
    elif path.stem == "continuous-prototype":
        from pitch_insights.generator.continuous import prototype
        from pitch_insights.explain.simulation import prototype_moments
        meta = prototype()[0]
        all_moments = prototype_moments()
        from pitch_insights.agents.prompts import SIMULATION_PROMPT_VERSION
        header = header | {"prompt_version": SIMULATION_PROMPT_VERSION}
    else:
        meta, events = read_match(path)
        brain = MatchBrain(meta, memory=memory_for(path, meta))
        for ev in events:
            brain.update(ev)
        all_moments = brain.moments
    desk = CommentaryDesk(writer, meta, safety=safety)
    moments = [m for m in all_moments if desk.wants(m)][:limit]
    old = load_commentary(path)
    reuse = not force and all(old.get(k) == header[k] for k in ("provider", "model", "prompt_version"))
    sem = asyncio.Semaphore(concurrency)

    async def one(m: dict) -> dict:
        kept = old["moments"].get(m["id"]) if reuse else None
        if (kept and (kept["status"] == "ok" or kept.get("pending")) and kept.get("input_hash") == input_hash(m, meta)
                and kept.get("provider", header["provider"]) == header["provider"]):
            async with sem:
                return await desk.screen(kept, m)
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
    tracing = setup_tracing(settings, "seize-the-game-commentary")
    writer = writer_from_settings(settings)
    safety = safety_from_settings(settings)
    if safety is None:
        print("Content Safety isn't configured in .env, so no line is screened; see .env.example")
    header = file_header(writer)
    paths = sample_paths(args.names)
    missing = [p.stem for p in paths if not exists(p)]
    if missing:
        print("No such sample: " + ", ".join(missing))
        return 1
    try:
        for path in paths:
            await run_match(path, writer, header, args.force, args.limit, settings.concurrency, safety)
    except ProviderConfigError as e:
        print(f"Stopped, nothing saved for {path.stem}: {e}")
        return 2
    finally:
        await writer.aclose()
        if safety is not None:
            await safety.aclose()
        if tracing:
            flush_tracing()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
