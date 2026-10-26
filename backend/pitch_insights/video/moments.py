"""Moments for the video clip: the evidence packs the commentary agents write from.

A synthetic match gets its moments from the Interpreter and the Moment Scorer. The clip has no Interpreter (no
squads, no score), so this module builds the same kind of moment straight from what the video path measured:

- the detected events (passes, carries, interceptions) are grouped into **passages of play**: a gap of more than
  `GAP_S` seconds between two events starts a new one. A lost pass followed at once by the other side's
  interception is a `turnover`; everything else is a `passage`;
- each moment's facts carry the numbers a writer may use: every event with how sure the model was (as a
  percentage), pass lengths and carry distances in metres, the fastest players in that window from the tracking
  frames (km/h), and each side's shape at that moment (players in the attacking and defensive thirds, width and
  depth in metres).

Deterministic code, no model and no network. A moment has the fields of a synthetic one (`explain/moments.py`) so
the app's moment feed draws it, plus `source: "video"`. We don't know the real score, so `score` is empty, and
players are only ever "Left #11": a tracker number, not a shirt number, and never a name (DESIGN.md, Video path).
Every figure is a whole number: the video can't be that exact, and a writer's rounding can't then fail the
groundedness check.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from pathlib import Path

from pitch_insights.video.replay import (
    SIDES, Clip, clip_meta, describe, event_length, find_clip, mmss, player_label,
)

GAP_S = 6.0           # a longer gap between two events (start to start) ends the passage of play
PAD_S = 2.0           # frames this far before the first event and after the last are read for speeds
SUSTAIN = 5           # frames in a row (1 s at 5 fps) a speed must be held to count
LOW_CONFIDENCE = 0.6  # the model was not sure below this; the facts say so, and the writer hedges
TOP_SPEED_MS = 9.5    # m/s (34 km/h): a faster reading is an ID switch (DESIGN.md: they reach 11.7 m/s)
MIN_TOP_KMH = 10      # slower than this isn't worth a mention
ATTACKING_X, OWN_X = 70.0, 35.0  # the thirds of a 105 m pitch, in each side's own attacking frame
MIN_TRACKED = 3       # fewer tracked players on a side than this and its shape says nothing
IMPORTANCE = (0.35, 0.59)  # always "notable" (0.35 to 0.6, as in explain/moments.py)


def clip_moments(clip: Clip) -> list[dict]:
    """The clip's moments, in order: `C-1`, `C-2`, ... See the module's docstring."""
    out: list[dict] = []
    for group in _passages(clip.events):
        out.append(_moment(clip, group, len(out) + 1))
    return out


# ------------------------------------------------------------------ grouping

def _passages(events: list[dict]) -> list[list[dict]]:
    groups: list[list[dict]] = []
    for ev in sorted(events, key=lambda e: (e["t"], e["seq"])):
        if groups and ev["t"] - groups[-1][-1]["t"] <= GAP_S:
            groups[-1].append(ev)
        else:
            groups.append([ev])
    return groups


def _turnover(group: list[dict]) -> tuple[dict, dict] | None:
    """The first lost pass that the other side's interception follows directly, as (the pass, the interception)."""
    for lost, nxt in zip(group, group[1:]):
        if (lost["type"] == "pass" and lost.get("outcome") != "complete"
                and nxt["type"] == "interception" and nxt["team_id"] != lost["team_id"]):
            return lost, nxt
    return None


# ------------------------------------------------------------------ one moment

def _moment(clip: Clip, group: list[dict], n: int) -> dict:
    first, last = group[0], group[-1]
    turnover = _turnover(group)
    if turnover:
        lost, won = turnover
        team, player = won["team_id"], won["player_id"]
        headline = f"{SIDES[team][0]} wins the ball after {SIDES[lost['team_id']][0]}'s pass goes astray"
    else:
        team = Counter(e["team_id"] for e in group).most_common(1)[0][0]  # ties go to the earlier event
        player = Counter(e["player_id"] for e in group if e["team_id"] == team).most_common(1)[0][0]
        headline = describe(first)[0] if len(group) == 1 else f"{SIDES[team][0]} on the ball: {_parts(group)}"
    mean_conf = sum(e["confidence"] for e in group) / len(group)
    lo, hi = IMPORTANCE
    importance = round(min(hi, lo + 0.04 * min(len(group), 5) + (0.1 if turnover else 0.0) + 0.1 * mean_conf), 3)
    return {
        "id": f"C-{n}", "seq": last["seq"], "t": last["t"], "match_time": last["t"], "clock": mmss(last["t"]),
        "minute": last["minute"], "period": 1, "type": "turnover" if turnover else "passage",
        "team_id": team, "player_id": player, "player_name": player_label(player),
        "importance": importance, "rank": importance, "tier": "notable", "headline": headline,
        "facts": _facts(clip, group), "signals": [], "score": {}, "source": "video",
    }


KINDS = {"carry": ("carry", "carries"), "pass": ("pass", "passes"), "interception": ("interception", "interceptions")}


def _counts(group: list[dict]) -> dict[str, int]:
    """How many carries, passes and interceptions the passage is made of (those it has)."""
    count = Counter(e["type"] for e in group)
    return {KINDS[t][1]: count[t] for t in KINDS if count[t]}


def _parts(group: list[dict]) -> str:
    """"2 carries and 1 pass": what the passage is made of."""
    parts = [f"{k} {KINDS[t][k != 1]}" for t in KINDS if (k := _counts(group).get(KINDS[t][1]))]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


# ------------------------------------------------------------------ facts

def _facts(clip: Clip, group: list[dict]) -> list[dict]:
    t0, t1 = group[0]["t"], group[-1]["t"]
    facts = [_summary(group, t0, t1)]
    facts += [_event_fact(e) for e in group]
    facts += _speed_facts(clip, t0 - PAD_S, t1 + PAD_S)
    facts += _shape_facts(clip, t1)
    return facts


def _summary(group: list[dict], t0: float, t1: float) -> dict:
    n = len(group)
    if n == 1:
        return {"kind": "detected", "value": {"events": 1},
                "text": f"The video model detected 1 event, at {mmss(t0)}."}
    seconds = max(1, round(t1 - t0))
    return {"kind": "detected", "value": {"events": n, "seconds": seconds} | _counts(group),
            "text": f"The video model detected {n} events within {seconds} s of {mmss(t0)}: {_parts(group)}."}


def _event_fact(ev: dict) -> dict:
    """One detected event, with the model's confidence as a percentage and the distance when it has one."""
    who = player_label(ev["player_id"])
    pct = round(100 * ev["confidence"])
    metres = round(event_length(ev)) if ev["type"] in ("pass", "carry") and event_length(ev) is not None else None
    if ev["type"] == "pass" and ev.get("outcome") == "complete":
        to = player_label(ev["receiver_id"]) if ev.get("receiver_id") else "a team-mate"
        what = f"{who} passes to {to}" + (f", {metres} m" if metres is not None else "")
    elif ev["type"] == "pass":
        what = f"{who}'s pass" + (f" of {metres} m" if metres is not None else "") + " goes astray"
    elif ev["type"] == "carry":
        what = f"{who} runs with the ball" + (f" for {metres} m" if metres is not None else "")
    else:
        what = f"{who} wins the ball"
    sure = (f"the model was only {pct}% sure (low confidence)" if ev["confidence"] < LOW_CONFIDENCE
            else f"the model was {pct}% sure")
    value = {"confidence_pct": pct} | ({"metres": metres} if metres is not None else {})
    kind = "pass_incomplete" if ev["type"] == "pass" and ev.get("outcome") != "complete" else ev["type"]
    return {"kind": kind, "value": value, "text": f"{mmss(ev['t'])} {what}; {sure}."}


def _speed_facts(clip: Clip, start: float, end: float) -> list[dict]:
    """The two fastest tracked players in the window, as whole km/h. The frames' `speed` is in m/s and one ID switch
    makes a lone reading jump to 11 m/s, so a speed counts only when the same track held it for `SUSTAIN` frames in
    a row (the highest such speed on the clip is 7.1 m/s, 26 km/h)."""
    recent: dict[str, list[float]] = {}  # each track's latest consecutive speeds
    held: dict[str, float] = {}          # the best speed a track held for SUSTAIN frames
    for f in clip.frames:
        if not start <= f["t"] <= end:
            continue
        seen = set()
        for p in f["players"]:
            s = p.get("speed")
            if p.get("team_id") in SIDES and s is not None and s <= TOP_SPEED_MS:
                seen.add(p["id"])
                run = recent.setdefault(p["id"], [])
                run.append(s)
                del run[:-SUSTAIN]
                if len(run) == SUSTAIN:
                    held[p["id"]] = max(held.get(p["id"], 0.0), min(run))
        for pid in set(recent) - seen:  # missing from this frame, or no usable speed: the run is broken
            recent[pid] = []
    fastest = sorted(held.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
    return [{"kind": "top_speed", "value": kmh,
             "text": f"{player_label(pid)} was tracked at {kmh} km/h or more for at least a second around then "
                     f"(tracker speeds can be off)."}
            for pid, ms in fastest if (kmh := round(ms * 3.6)) >= MIN_TOP_KMH]


def _shape_facts(clip: Clip, t: float) -> list[dict]:
    """Each side's shape in the frame nearest `t`: how many of its tracked players are in its attacking third and in
    its own, and how far they spread across and along the pitch. Positions are in each side's own attacking frame."""
    times = [f["t"] for f in clip.frames]
    i = bisect_left(times, t)
    frame = min(clip.frames[max(0, i - 1):i + 1], key=lambda f: abs(f["t"] - t))
    out = []
    for side in ("L", "R"):
        pts = [(p["x"], p["y"]) for p in frame["players"] if p.get("team_id") == side]
        if len(pts) < MIN_TRACKED:
            continue
        xs, ys = [x for x, _ in pts], [y for _, y in pts]
        attacking, own = sum(x >= ATTACKING_X for x in xs), sum(x < OWN_X for x in xs)
        width, depth = round(max(ys) - min(ys)), round(max(xs) - min(xs))
        out.append({"kind": "shape", "value": {"attacking_third": attacking, "own_third": own, "tracked": len(pts),
                                               "width_m": width, "depth_m": depth},
                    "text": f"At {mmss(frame['t'])} {SIDES[side][0]} had {attacking} of its {len(pts)} tracked players in "
                            f"the attacking third and {own} in its own third, spread {width} m across the pitch "
                            f"and {depth} m from back to front."})
    return out


def load_clip_moments(samples: Path, name: str) -> tuple[dict, list[dict]] | None:
    """(the clip's `match_meta`, its moments) for `samples/video/<name>.*`, or None when there is no such clip. What
    the scripts that write or check stored commentary and translations read, like `read_match` for a synthetic match."""
    clip = find_clip(samples, name)
    return None if clip is None else (clip_meta(clip), clip_moments(clip))
