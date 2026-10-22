"""Translate each sample match's moments (headlines, facts, commentary) with Azure AI Translator.

    python scripts/translate_moments.py                     # every sample in ../samples
    python scripts/translate_moments.py comeback-POT-CAR    # one match

Run it after scripts/generate_commentary.py. Only moments whose English text changed are sent
again, so re-running costs nothing when nothing changed. A translation that loses a name or a
number keeps the English text, and isn't sent again unless you pass --retry. Writes
samples/<name>.translations.json.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from pitch_insights.agents.memory import memory_for
from pitch_insights.agents.settings import load_settings
from pitch_insights.agents.store import load_commentary
from pitch_insights.agents.translate import (
    LANGUAGES, TRANSLATION_VERSION, _names_pattern, check, load_translations, moment_texts, names_for, protect, source_hash,
    translator_from_settings, unprotect, write_translations,
)
from pitch_insights.explain.moments import MatchBrain
from pitch_insights.generator.io import read_match
from pitch_insights.server import with_commentary

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


async def run_match(path: Path, translator, retry: bool = False) -> None:
    meta, events = read_match(path)
    brain = MatchBrain(meta, memory=memory_for(path, meta))
    for ev in events:
        brain.update(ev)
    stored = load_commentary(path)
    moments = [with_commentary(m, stored, meta) for m in brain.moments]
    saved = load_translations(path)
    old = saved["moments"] if saved.get("version") == TRANSLATION_VERSION else {}  # redo after a method change
    pattern = _names_pattern(names_for(meta))

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
    paths = [SAMPLES / f"{n}.jsonl" for n in args.names] if args.names else sorted(SAMPLES.glob("*.jsonl"))
    try:
        for path in paths:
            await run_match(path, translator, args.retry)
    finally:
        await translator.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
