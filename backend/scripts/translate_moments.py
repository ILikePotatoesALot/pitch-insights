"""Translate each sample match's moments (headlines, facts, commentary) with Azure AI Translator.

    python scripts/translate_moments.py                     # every sample in ../samples
    python scripts/translate_moments.py comeback-POT-CAR    # one match
    python scripts/translate_moments.py 117093-38min_ft     # the real-footage clip, in samples/video/
    python scripts/translate_moments.py continuous-prototype  # the generated exhibition

Run it after scripts/generate_commentary.py. Only moments whose English text changed are sent
again, so re-running costs nothing when nothing changed. A translation that loses a name or a
number keeps the English text, and isn't sent again unless you pass --retry. Writes
samples/<name>.translations.json (samples/video/<name>.translations.json for the clip, whose moments come from
video/moments.py and whose commentary is the video narrator's). With no names, every sample match,
the continuous exhibition and every listed clip are done. The exhibition is generated from its seed;
it does not need a source JSONL file and translating it makes no commentary-model calls.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from pitch_insights.agents.memory import memory_for
from pitch_insights.agents.settings import load_settings
from pitch_insights.agents.store import load_commentary, with_commentary
from pitch_insights.agents.translate import (
    LANGUAGES, TRANSLATION_VERSION, _names_pattern, check, load_translations, moment_texts, names_for, protect, source_hash,
    translator_from_settings, unprotect, write_translations,
)
from pitch_insights.explain.moments import MatchBrain
from pitch_insights.generator.io import read_match
from pitch_insights.generator.continuous import NAME as SIMULATION, prototype
from pitch_insights.explain.simulation import prototype_moments
from pitch_insights.video.moments import load_clip_moments
from pitch_insights.video.replay import APP_CLIPS, CLIP_DIR, stored_path

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def is_clip(path: Path) -> bool:
    """A clip's stored files are named as if for `samples/video/<name>.jsonl` (see video.replay.stored_path)."""
    return path.parent.name == CLIP_DIR


def sample_paths(names: list[str]) -> list[Path]:
    if not names:
        matches = sorted(SAMPLES.glob("*.jsonl"))
        simulation = SAMPLES / f"{SIMULATION}.jsonl"
        if simulation not in matches:
            matches.append(simulation)
        return matches + [stored_path(SAMPLES, n) for n in APP_CLIPS]
    return [stored_path(SAMPLES, n) if (SAMPLES / CLIP_DIR / f"{n}.frames.jsonl").exists() else SAMPLES / f"{n}.jsonl"
            for n in names]


async def run_match(path: Path, translator, retry: bool = False) -> None:
    if is_clip(path):
        meta, all_moments = load_clip_moments(SAMPLES, path.stem)
    elif path.stem == SIMULATION:
        meta, all_moments = prototype()[0], prototype_moments()
    else:
        meta, events = read_match(path)
        brain = MatchBrain(meta, memory=memory_for(path, meta))
        for ev in events:
            brain.update(ev)
        all_moments = brain.moments
    stored = load_commentary(path)
    moments = [with_commentary(m, stored, meta) for m in all_moments]
    saved = load_translations(path)
    old = saved["moments"] if saved.get("version") == TRANSLATION_VERSION else {}  # redo after a method change
    pattern = _names_pattern(names_for(meta), trackers=meta.get("source") == "video")  # the clip's "Left #11" too

    # What still needs translating: every text of a moment whose English changed, and any text a
    # language is missing (it failed the check last time) when --retry is given.
    entries, todo = {}, {}  # todo: (moment id, key, English) -> languages wanted
    for m in moments:
        texts = moment_texts(m)
        h = source_hash(texts)
        entry = old.get(m["id"], {})
        if entry.get("source_hash") != h:
            entry = {"source_hash": h}
        entries[m["id"]] = entry
        for k, v in texts.items():
            missing = [lang for lang in LANGUAGES if k not in entry.get(lang, {})
                       and (retry or k not in entry.get("failed", {}).get(lang, []))]
            if missing:
                todo[(m["id"], k, v)] = missing

    before = translator.characters
    groups: dict[tuple, list] = {}
    for item, langs in todo.items():
        groups.setdefault(tuple(langs), []).append(item)
    for langs, items in groups.items():
        results = await translator.translate([protect(v, pattern) for _, _, v in items], list(langs))
        for (mid, key, source), by_lang in zip(items, results):
            for lang in langs:
                text = unprotect(by_lang[lang], lang)
                failed = entries[mid].setdefault("failed", {}).setdefault(lang, [])
                if check(source, text, pattern):
                    if key not in failed:
                        failed.append(key)
                else:
                    entries[mid].setdefault(lang, {})[key] = text
                    if key in failed:
                        failed.remove(key)
    for e in entries.values():  # tidy: drop empty failure lists
        e["failed"] = {lang: keys for lang, keys in e.get("failed", {}).items() if keys}
        if not e["failed"]:
            del e["failed"]
    kept_english = {lang: sum(len(e.get("failed", {}).get(lang, [])) for e in entries.values()) for lang in LANGUAGES}
    out = write_translations(path, entries, kept_english)
    print(f"{path.stem}: {len(moments)} moments, {len(todo)} texts sent ({translator.characters - before} characters counted "
          f"across {len(LANGUAGES)} languages); kept in English after the check: {kept_english}  ->  {out.name}")


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*", help="sample names (default: all)")
    ap.add_argument("--retry", action="store_true", help="also retry texts that failed the check before")
    args = ap.parse_args()
    translator = translator_from_settings(load_settings())
    if translator is None:
        print("Translator isn't configured; fill in AZURE_TRANSLATOR_KEY in .env (see .env.example)")
        return 1
    paths = sample_paths(args.names)
    try:
        for path in paths:
            await run_match(path, translator, args.retry)
    finally:
        await translator.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
