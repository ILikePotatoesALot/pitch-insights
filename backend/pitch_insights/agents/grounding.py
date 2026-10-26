"""Groundedness check: does commentary only use names and numbers from the evidence pack?

Code, not a model, so it's fast, free and gives the same answer every time. It checks two
kinds of claim:

- numbers: every number in the text must match one in the moment (its facts, clock, score
  and values), allowing for rounding, percentages, and stoppage time written as a minute
  ("90+6'" may become "96th minute");
- names: any player or club the league knows that the text mentions must appear in the
  moment (the two clubs playing are always allowed).

It can't catch made-up claims without a name or a number ("a stunning volley"); the prompt
rules and, later, Foundry's groundedness evaluator cover those.

Moments detected from video (`source == "video"`) get two more checks, because the detector only sees passes,
carries and interceptions and is often unsure: words for things it can't see or that no fact says (goals, shots,
fouls, cards, a score, tactical labels, directions, shirt numbers) count as unsupported claims, and a version of the
commentary must hedge when an event under 60% confidence is in the moment (`hedging`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pitch_insights.generator.players import load_clubs

NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
CLOCK = re.compile(r"(\d+)\+(\d+)")
NUMBER_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty".split())}
TENS = {w: 10 * i for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split(), 2)}
# Ordinals count only at the end of a compound ("ninety-third" is 93); on their own ("second half",
# "first goal") they're rarely numbers.
ORDINALS = {w: i for i, w in enumerate("first second third fourth fifth sixth seventh eighth ninth".split(), 1)}


def number_phrases(text: str) -> list[tuple[str, int]]:
    """Numbers written as words, read whole: "ninety-three" is 93 (not 90 and 3), "a hundred
    and five" is 105. Returns (the words, their value) for each run of number words."""
    words = re.findall(r"[a-z]+", text.lower())  # hyphens split, so "ninety-three" is two words
    out, i = [], 0
    while i < len(words):
        value, used = None, []
        while i < len(words):
            w, after_hundred = words[i], value is not None and value >= 100 and value % 100 == 0
            if w in TENS and (value is None or after_hundred):
                value = (value or 0) + TENS[w]
            elif w in NUMBER_WORDS and (value is None or after_hundred
                                        or (value % 100 >= 20 and value % 10 == 0 and NUMBER_WORDS[w] < 10)):
                value = (value or 0) + NUMBER_WORDS[w]
            elif w in ORDINALS and value is not None and value % 100 >= 20 and value % 10 == 0:
                value += ORDINALS[w]
                used.append(w)
                i += 1
                break  # an ordinal ends the number
            elif w == "hundred" and (value is None or 1 <= value <= 9):
                value = (value or 1) * 100  # "hundred", "a hundred", "three hundred"
            elif not (w == "and" and used and used[-1] == "hundred" and i + 1 < len(words)
                      and (words[i + 1] in NUMBER_WORDS or words[i + 1] in TENS)):
                break
            used.append(w)
            i += 1
        if used:
            out.append((" ".join(u for u in used if u != "and"), value))
        else:
            i += 1
    return out


def word_claims(text: str) -> list[tuple[str, int]]:
    """Number phrases in commentary that count as claims. A lone "one" or "zero" is left out:
    "one of", "no one" and "one-sided" are rarely counts, and the prompt asks for digits anyway."""
    return [(phrase, n) for phrase, n in number_phrases(text) if n >= 2 or " " in phrase]


@dataclass
class Grounding:
    score: float                      # share of claims the pack supports (1.0 when there are none)
    claims: int
    unsupported: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.unsupported

    def to_dict(self) -> dict:
        return {"score": round(self.score, 3), "claims": self.claims, "unsupported": self.unsupported}


def moment_text(moment: dict) -> str:
    """Everything the writer was shown, as one string."""
    parts = [moment.get("headline", ""), moment.get("clock", ""), moment.get("player_name") or ""]
    parts += [f.get("text", "") for f in moment.get("facts", [])]
    return " ".join(parts)


def _values(obj) -> list[int | float]:
    """Every number inside a fact value (dicts and lists included), keeping int or float."""
    if isinstance(obj, bool):
        return []
    if isinstance(obj, (int, float)):
        return [obj]
    if isinstance(obj, dict):
        return [v for x in obj.values() for v in _values(x)]
    if isinstance(obj, (list, tuple)):
        return [v for x in obj for v in _values(x)]
    return []


def supported_numbers(moment: dict) -> set[float]:
    text = moment_text(moment)
    nums = {float(n) for n in NUMBER.findall(text)}
    for _, n in number_phrases(text):
        nums.add(float(n))  # "the last five minutes" backs "5 minutes"
    for base, extra in CLOCK.findall(text):
        nums.add(float(int(base) + int(extra)))  # 90+6' is the 96th minute
    if moment.get("minute") is not None:
        nums.add(float(moment["minute"]))
    nums.update(_values(moment.get("score")))
    for f in moment.get("facts", []):
        for v in _values(f.get("value")):
            nums.add(float(v))
            # A probability or share written as a percentage. Only fractions: whole-number counts and
            # scores (a score of 1) mustn't back "100".
            if isinstance(v, float) and 0 < v < 1:
                nums.add(float(round(v * 100)))
    return nums


def _number_ok(n: float, supported: set[float]) -> bool:
    if n.is_integer():  # whole numbers must match exactly: "4" isn't backed by an xG of 3.88
        return any(abs(n - s) < 1e-9 for s in supported)
    return any(abs(n - s) <= 0.0051 or abs(round(s, 1) - n) < 1e-9 for s in supported)


def known_names(meta: dict) -> dict[str, str]:
    """Lower-case name as it might be written -> how to report it. Players (full name and
    surname) from both squads, plus every club in the league."""
    names: dict[str, str] = {}
    for side in ("home", "away"):
        for p in meta[side]["players"]:
            names[p["name"].lower()] = p["name"]
            names[p["name"].split()[-1].lower()] = p["name"]
    for club in load_clubs().values():
        names[club.name.lower()] = club.name
        names[club.short_name.lower()] = club.name
    return names


# What video commentary must not say. The detector sees passes, carries and interceptions only, the real score isn't
# known, the facts hold no directions or tactics, and the numbers after "#" are tracker IDs, not shirt numbers.
VIDEO_BANNED = re.compile(
    r"(?<!\w)(goals?|shots?|fouls?|cards?|penalt(?:y|ies)|offsides?|corners?|sav(?:e|es|ed|ing)|scor(?:e|es|ed|ing)|shirts?"
    r"|pressing|presses|counter-?attack\w*|dominat\w+|forwards?|backwards?|number \d+)(?!\w)", re.I)
LOW_CONFIDENCE_PCT = 60
HEDGES = re.compile(
    r"\b(appears?|seems?|seemingly|looks?|suggests?|possibly|apparently|likely|unsure|uncertain|not sure|"
    r"(?:was|is|were)n't (?:sure|certain)|confidence is low|only \d+% (?:sure|confident)|low confidence|may|might)\b", re.I)


def _is_low_confidence_event(fact: dict) -> bool:
    value = fact.get("value")
    return (fact.get("kind") in ("pass", "pass_incomplete", "carry", "interception") and isinstance(value, dict)
            and isinstance(value.get("confidence_pct"), (int, float)) and value["confidence_pct"] < LOW_CONFIDENCE_PCT)


def hedging(casual: str, analyst: str, moment: dict) -> list[str]:
    """The versions that state a video moment flatly although it holds an event the model was under 60% sure of.
    Empty for any other moment, and for a video moment whose events were all 60% or more."""
    if moment.get("source") != "video" or not any(_is_low_confidence_event(f) for f in moment.get("facts", [])):
        return []
    return [f"{name}: no hedge on events the model was under {LOW_CONFIDENCE_PCT}% sure of"
            for name, text in (("casual", casual), ("analyst", analyst)) if not HEDGES.search(text)]


def with_hedging(grounded: "Grounding", casual: str, analyst: str, moment: dict) -> "Grounding":
    """`grounded` with the hedging problems added to what is unsupported (and to the claims, which lowers the score)."""
    problems = hedging(casual, analyst, moment)
    if not problems:
        return grounded
    claims = grounded.claims + len(problems)
    unsupported = grounded.unsupported + problems
    return Grounding(score=(claims - len(unsupported)) / claims, claims=claims, unsupported=unsupported)


def _mentions(name: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text) is not None


def check(text: str, moment: dict, meta: dict) -> Grounding:
    supported = supported_numbers(moment)
    unsupported: list[str] = []
    claims = 0
    for raw in NUMBER.findall(text):
        claims += 1
        if not _number_ok(float(raw), supported):
            unsupported.append(raw)
    for phrase, n in word_claims(text):  # "ninety-three goals" is checked like "93 goals"
        claims += 1
        if not _number_ok(float(n), supported):
            unsupported.append(phrase)

    source = moment_text(moment).lower()
    playing = {meta[s][k].lower() for s in ("home", "away") for k in ("name", "short_name")}
    low = text.lower()
    reported: set[str] = set()
    # Longest names first, so "Potato FC" is judged before "Potato".
    for name, label in sorted(known_names(meta).items(), key=lambda kv: -len(kv[0])):
        if label in reported or not _mentions(name, low):
            continue
        reported.add(label)
        claims += 1
        if name not in playing and not _mentions(name, source):
            unsupported.append(label)
    if moment.get("source") == "video":
        for word in dict.fromkeys(m.group(1).lower() for m in VIDEO_BANNED.finditer(text)):
            claims += 1
            unsupported.append(word)
    score = 1.0 if claims == 0 else (claims - len(unsupported)) / claims
    return Grounding(score=score, claims=claims, unsupported=unsupported)
