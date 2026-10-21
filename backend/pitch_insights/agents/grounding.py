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


def _values(obj) -> list[float]:
    """Every number inside a fact value (dicts and lists included)."""
    if isinstance(obj, bool):
        return []
    if isinstance(obj, (int, float)):
        return [float(obj)]
    if isinstance(obj, dict):
        return [v for x in obj.values() for v in _values(x)]
    if isinstance(obj, (list, tuple)):
        return [v for x in obj for v in _values(x)]
    return []


def supported_numbers(moment: dict) -> set[float]:
    text = moment_text(moment)
    nums = {float(n) for n in NUMBER.findall(text)}
    for word in re.findall(r"[a-z]+", text.lower()):
        if word in NUMBER_WORDS:
            nums.add(float(NUMBER_WORDS[word]))  # "the last five minutes" backs "5 minutes"
    for base, extra in CLOCK.findall(text):
        nums.add(float(int(base) + int(extra)))  # 90+6' is the 96th minute
    if moment.get("minute") is not None:
        nums.add(float(moment["minute"]))
    nums.update(_values(moment.get("score")))
    for f in moment.get("facts", []):
        for v in _values(f.get("value")):
            nums.add(v)
            if 0 <= v <= 1:
                nums.add(round(v * 100))  # a probability or share written as a percentage
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
    score = 1.0 if claims == 0 else (claims - len(unsupported)) / claims
    return Grounding(score=score, claims=claims, unsupported=unsupported)
