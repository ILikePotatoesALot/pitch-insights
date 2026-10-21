"""Watch a match play out in the terminal, on the match clock.

    python -m pitch_insights.watch ../samples/comeback-POT-CAR.jsonl
    python -m pitch_insights.watch ../samples/comeback-POT-CAR.jsonl --speed 60 --from 80
    python -m pitch_insights.watch ../samples/thriller-CAR-BRO.jsonl --all --speed 5

By default only key moments are shown (shots, cards, subs, kickoffs); --all shows every event.
--speed 1 is real time; --speed 60 plays one match minute per second.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from pitch_insights.generator.io import read_match
from pitch_insights.generator.stream import Replay, match_seconds, start_seconds

KEY_TYPES = {"shot", "foul", "substitution", "match_state"}


class Commentary:
    def __init__(self, meta: dict):
        self.meta = meta
        self.names = {p["id"]: p["name"] for side in ("home", "away") for p in meta[side]["players"]}
        self.short = {meta[s]["id"]: meta[s]["short_name"] for s in ("home", "away")}
        self.home, self.away = meta["home"]["id"], meta["away"]["id"]
        self.score = {self.home: 0, self.away: 0}

    def scoreline(self) -> str:
        return (f"{self.meta['home']['name']} {self.score[self.home]}-{self.score[self.away]} "
                f"{self.meta['away']['name']}")

    def name(self, pid: str | None) -> str:
        return self.names.get(pid, "?").split()[-1] if pid else "?"

    def update(self, ev: dict):
        if ev["type"] == "shot" and ev["outcome"] == "goal":
            self.score[ev["team_id"]] += 1

    def describe(self, ev: dict) -> str | None:
        """One line for an event, or None if there is nothing to say."""
        t = ev["type"]
        team = self.short.get(ev.get("team_id"), "")
        who = self.name(ev.get("player_id"))
        if t == "match_state":
            label = {"kickoff": "Kick-off" if ev["period"] == 1 else "Second half under way",
                     "half_time": "Half-time", "full_time": "Full-time"}[ev["state"]]
            return f"=== {label}: {self.scoreline()} ==="
        if t == "shot":
            kind = {"penalty": " from the penalty spot", "free_kick": " from a free kick",
                    "header": " with a header"}.get(ev["kind"], "")
            if ev["outcome"] == "goal":
                return f"GOAL! {who} ({team}){kind}, xG {ev['xg']:.2f}  ->  {self.scoreline()}"
            result = {"saved": "saved", "off_target": "off target", "blocked": "blocked",
                      "woodwork": "off the woodwork!"}[ev["outcome"]]
            return f"Shot: {who} ({team}){kind}, {result} (xG {ev['xg']:.2f})"
        if t == "foul":
            card = {"yellow": "  [YELLOW CARD]", "red": "  [RED CARD]"}.get(ev["card"], "")
            pen = "  -> PENALTY" if ev.get("penalty") else ""
            return f"Foul by {who} ({team}) on {self.name(ev['victim_id'])}{card}{pen}"
        if t == "substitution":
            return f"Sub ({team}): {self.name(ev['player_on_id'])} on, {self.name(ev['player_off_id'])} off"
        if t == "pass":
            kind = "" if ev["kind"] == "open_play" else f" {ev['kind'].replace('_', ' ')}"
            if ev["outcome"] == "complete":
                return f"{who}{kind} to {self.name(ev.get('receiver_id'))}"
            return f"{who}{kind}, {'out of play' if ev['outcome'] == 'out' else 'misplaced'}"
        if t == "carry":
            return f"{who} carries the ball forward"
        if t == "dribble":
            return f"{who} {'beats' if ev['outcome'] == 'won' else 'is stopped by'} {self.name(ev['opponent_id'])}"
        if t == "pressure":
            return f"{who} presses {self.name(ev['target_player_id'])}"
        if t == "tackle":
            return f"{who} {'wins the ball' if ev['outcome'] == 'won' else 'misses a tackle'} ({team})"
        if t in ("interception", "recovery", "clearance"):
            return f"{who} {t.replace('interception', 'intercepts').replace('recovery', 'picks up the loose ball').replace('clearance', 'clears')} ({team})"
        return None


async def watch(path: str, speed: float, from_minute: float, show_all: bool, out=sys.stdout):
    meta, events = read_match(path)
    c = Commentary(meta)
    start = start_seconds(events, from_minute) if from_minute else 0.0
    times = match_seconds(events)
    for ev, et in zip(events, times):
        if et >= start:
            break
        c.update(ev)
    print(f"{meta['match']['competition']}, matchday {meta['match']['matchday']}, {meta['match']['venue']}", file=out)
    print(f"{c.scoreline()}  (seed {meta['match']['seed']}, {speed:g}x speed)", file=out)
    if from_minute:
        print(f"Starting from {from_minute:g}'", file=out)
    print(file=out)
    async for ev in Replay(events, speed=speed, start_at=start):
        c.update(ev)
        if not show_all and ev["type"] not in KEY_TYPES:
            continue
        line = c.describe(ev)
        if line:
            print(f"{ev['clock']:>7}  {line}", file=out, flush=True)


def positive(value: str) -> float:
    f = float(value)
    if f <= 0:
        raise argparse.ArgumentTypeError("must be more than 0")
    return f


def main(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("match", help="path to a match .jsonl file")
    ap.add_argument("--speed", type=positive, default=20.0)
    ap.add_argument("--from", dest="from_minute", type=float, default=0.0, help="start at this minute")
    ap.add_argument("--all", action="store_true", help="show every event, not just key moments")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        asyncio.run(watch(args.match, args.speed, args.from_minute, args.all))
    except KeyboardInterrupt:
        pass
    except (BrokenPipeError, OSError):  # output closed early, e.g. piped into `head`
        sys.stdout = None


if __name__ == "__main__":
    main()
