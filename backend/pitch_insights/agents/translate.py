"""Translator: each moment's headline, facts and commentary in the viewer's language.

Azure AI Translator (text translation v3.0) over plain REST. Player and club names are
wrapped in `<span class="notranslate">`, which the service leaves alone when the text is sent
as HTML, so "Potato FC" never becomes "Patate FC":
https://learn.microsoft.com/en-us/azure/ai-services/translator/text-translation/how-to/prevent-translation

Every translation is then checked in code, like the commentary: each name and number in the
English text must still be in the translation. One that fails keeps the English text.

Translations for the sample matches are made ahead and stored next to each match, so a replay
never calls the network:

    samples/comeback-POT-CAR.translations.json
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import re
from pathlib import Path

import httpx

from pitch_insights.agents.clients import post_with_retry, ssl_context
from pitch_insights.agents.store import sibling_path, write_json
from pitch_insights.generator.players import load_clubs

API_VERSION = "3.0"
# Bump when what's protected or how output is cleaned changes, so stored translations are redone.
TRANSLATION_VERSION = "2026-10-22.2"
# English is the source. Chosen 22 Oct for a global audience.
LANGUAGES = {"es": "Español", "fr": "Français", "de": "Deutsch", "nl": "Nederlands", "zh-Hans": "简体中文"}
MAX_CHARS = 1_000     # source characters per request; the service allows 50,000 counted across all target languages
MAX_ITEMS = 1_000     # texts per request, the service's limit
# Characters are counted once per target language. The free tier (F0) allows 2 million a month and
# about 33,300 a minute; stay under that so requests aren't refused:
# https://learn.microsoft.com/en-us/azure/ai-services/translator/service-limits
PER_MINUTE = 30_000
SPAN = re.compile(r'<span class="notranslate">(.*?)</span>', re.S)
# Digits only on the boundary: Chinese characters count as word characters, so the grounding check's
# pattern would miss the 0.75 in "高0.75".
NUMBER = re.compile(r"(?<![0-9.])[0-9]+(?:\.[0-9]+)?")


def names_for(meta: dict) -> list[str]:
    """Every name that must not be translated: both squads' players (full name and surname) and
    every club in the league (name and short name). Longest first, so "Potato FC" wins over "Potato"."""
    names = set()
    for side in ("home", "away"):
        for p in meta[side]["players"]:
            names.add(p["name"])
            names.add(p["name"].split()[-1])
    for club in load_clubs().values():
        names.update((club.name, club.short_name))
    return sorted(names, key=lambda n: (-len(n), n))


CLOCK = r"[0-9]+(?:\+[0-9]+)?'"  # 6', 45+2': protected too, or German reads 6' as six feet


def _names_pattern(names: list[str]) -> re.Pattern:
    """Names and match clocks: what a translation must keep exactly as written."""
    alternatives = [re.escape(html.escape(n, quote=False)) for n in names] + [CLOCK]
    return re.compile(r"(?<!\w)(" + "|".join(alternatives) + r")(?!\w)")


def protect(text: str, pattern: re.Pattern) -> str:
    """The text as HTML, with every name wrapped so the service leaves it alone."""
    return pattern.sub(r'<span class="notranslate">\1</span>', html.escape(text, quote=False))


def unprotect(text: str, lang: str = "") -> str:
    """Plain text again. The service drops the space next to a protected span ("Potatozweite"),
    so outside Chinese, put one back where a word runs into a name."""
    if lang != "zh-Hans":
        text = re.sub(r"(</span>)(?=\w)", r"\1 ", text)
        text = re.sub(r'(?<=\w)(<span class="notranslate">)', r" \1", text)
    return html.unescape(SPAN.sub(r"\1", text))


def _numbers(text: str) -> list[str]:
    """Numbers in a text, with a decimal comma read as a point ("3,88" in German is 3.88)."""
    return NUMBER.findall(re.sub(r"(?<=\d),(?=\d)", ".", text))


def check(source: str, translated: str, pattern: re.Pattern) -> list[str]:
    """What the translation lost: names or numbers in the English that aren't in it."""
    lost = [n for n in dict.fromkeys(pattern.findall(html.escape(source, quote=False)))
            if html.unescape(n) not in translated]
    have = _numbers(translated)
    # Small ordinals may be written as words ("3rd" is "drittes", "tercer"), which is right.
    as_words = {m for m in re.findall(r"(?<![0-9])([0-9]+)(?:st|nd|rd|th)\b", source) if int(m) <= 20}
    for n in _numbers(source):
        if n in have:
            have.remove(n)
        elif n not in as_words:
            lost.append(n)
    return lost


class Translator:
    def __init__(self, endpoint: str, key: str, region: str = "global", timeout_s: float = 20.0,
                 client: httpx.AsyncClient | None = None, per_minute: int = PER_MINUTE):
        self.url = endpoint.rstrip("/") + "/translate"
        self._headers = {"Ocp-Apim-Subscription-Key": key, "Ocp-Apim-Subscription-Region": region}
        self.client = client or httpx.AsyncClient(verify=ssl_context(), timeout=timeout_s)
        self.characters = 0  # characters counted (source x languages), for the free tier's 2 million a month
        self.per_minute = per_minute

    async def aclose(self) -> None:
        await self.client.aclose()

    async def translate(self, texts: list[str], languages: list[str]) -> list[dict[str, str]]:
        """HTML texts -> for each, {language: translated HTML}. Batched within the service's limits;
        raises httpx.HTTPError if the service fails after its retries."""
        out: list[dict[str, str]] = []
        batch: list[str] = []

        async def flush():
            if not batch:
                return
            r = await post_with_retry(
                self.client, self.url, headers=self._headers, json=[{"Text": t} for t in batch],
                params=[("api-version", API_VERSION), ("from", "en"), ("textType", "html")]
                + [("to", lang) for lang in languages])
            r.raise_for_status()
            for item in r.json():
                out.append({t["to"]: t["text"] for t in item["translations"]})
            counted = sum(len(t) for t in batch) * len(languages)
            self.characters += counted
            batch.clear()
            if self.per_minute:
                await asyncio.sleep(60.0 * counted / self.per_minute)  # spread the minute's budget evenly

        size = 0
        for t in texts:
            if batch and (size + len(t) > MAX_CHARS or len(batch) >= MAX_ITEMS):
                await flush()
                size = 0
            batch.append(t)
            size += len(t)
        await flush()
        return out


def translator_from_settings(settings) -> Translator | None:
    if not settings.translator_key:
        return None
    return Translator(settings.translator_endpoint, settings.translator_key, settings.translator_region,
                      settings.timeout_s)


# ---------------------------------------------------------------- what a moment shows

def moment_texts(moment: dict) -> dict[str, str]:
    """The texts a viewer sees for a moment, by key: headline, each fact, and the commentary lines
    (only when the agents wrote some; a fallback repeats the headline)."""
    texts = {"headline": moment["headline"]}
    for i, f in enumerate(moment.get("facts", [])):
        if f.get("text"):
            texts[f"fact.{i}"] = f["text"]
    c = moment.get("commentary")
    if c and c.get("status") == "ok":
        texts["casual"], texts["analyst"] = c["casual"], c["analyst"]
    return texts


def source_hash(texts: dict[str, str]) -> str:
    return hashlib.sha256("\x1f".join(f"{k}={v}" for k, v in sorted(texts.items())).encode()).hexdigest()[:16]


def translated_moment(moment: dict, entry: dict | None, lang: str) -> dict:
    """The moment in `lang`, from a stored entry made from these same texts; otherwise unchanged
    (English). Keys the stored entry lacks (a translation that failed its check) stay English."""
    if lang not in LANGUAGES or not entry or entry.get("source_hash") != source_hash(moment_texts(moment)):
        return moment
    tr = entry.get(lang) or {}
    m = moment | {"lang": lang, "headline": tr.get("headline", moment["headline"])}
    m["facts"] = [f | {"text": tr.get(f"fact.{i}", f["text"])} if f.get("text") else f
                  for i, f in enumerate(moment.get("facts", []))]
    if m.get("commentary") and ("casual" in tr or "analyst" in tr):
        c = m["commentary"]
        m["commentary"] = c | {"casual": tr.get("casual", c["casual"]), "analyst": tr.get("analyst", c["analyst"])}
    return m


# ---------------------------------------------------------------- stored translations

def translations_path(match_path: Path) -> Path:
    return sibling_path(match_path, ".translations.json")


def load_translations(match_path: Path) -> dict:
    import json

    try:
        data = json.loads(translations_path(match_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"moments": {}}
    data.setdefault("moments", {})
    return data


def write_translations(match_path: Path, entries: dict[str, dict], kept_english: dict[str, int]) -> Path:
    return write_json(translations_path(match_path), {
        "service": "azure-translator", "api_version": API_VERSION, "version": TRANSLATION_VERSION,
        "source": "en", "languages": list(LANGUAGES),
        "machine_translated": True, "kept_english": kept_english, "moments": entries,
    })
