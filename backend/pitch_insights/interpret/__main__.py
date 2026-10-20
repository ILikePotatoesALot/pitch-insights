"""Interpret a match file: stats, patterns, win probability, ratings and signals.

    python -m pitch_insights.interpret ../samples/comeback-POT-CAR.jsonl
    python -m pitch_insights.interpret ../samples/comeback-POT-CAR.jsonl --at 70
    python -m pitch_insights.interpret ../samples/comeback-POT-CAR.jsonl --player Madekuta
    python -m pitch_insights.interpret ../samples/comeback-POT-CAR.jsonl --json out.json

--at stops at that minute of the broadcast clock, showing the state as it was then.
"""

from __future__ import annotations

import argparse
import json
import sys

from pitch_insights.generator.io import read_match
from pitch_insights.generator.stream import match_seconds, start_seconds
from pitch_insights.interpret.interpreter import Interpreter

TEAM_ROWS = [
    ("Possession %", "possession_pct"), ("Shots (on target)", None), ("xG", "xg"), ("Big chances", "big_chances"),
    ("Passes", "passes"), ("Pass accuracy %", "pass_accuracy_pct"), ("Progressive passes", "progressive_passes"),
    ("Final-third entries", "final_third_entries"), ("Threat added (xT)", "xt_added"), ("Corners", "corners"),
    ("High pressures", "pressures_high"), ("PPDA", "ppda"), ("Tackles won", "tackles_won"),
    ("Interceptions", "interceptions"), ("Fouls", "fouls"), ("Yellow / red", None),
]


def stop_index(events: list[dict], minute: float | None) -> int:
    """Index of the first event at or after `minute` on the broadcast clock (all events if None)."""
    if minute is None:
        return len(events)
    cutoff = start_seconds(events, minute)
    return next((i for i, t in enumerate(match_seconds(events)) if t >= cutoff), len(events))


def main(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("match")
    ap.add_argument("--at", type=float, help="stop at this minute")
    ap.add_argument("--player", help="show the full rating breakdown for a player (part of the name)")
    ap.add_argument("--top", type=int, default=8, help="how many players to list")
    ap.add_argument("--json", help="write the full snapshot and signals to this file")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    meta, events = read_match(args.match)
    it = Interpreter(meta)
    for ev in events[:stop_index(events, args.at)]:
        it.update(ev)
    snap = it.snapshot()
    home, away = meta["home"], meta["away"]
    h, a = snap["teams"][home["id"]], snap["teams"][away["id"]]

    print(f"{home['name']} {snap['score'][home['id']]}-{snap['score'][away['id']]} {away['name']}   "
          f"({'full time' if snap['finished'] else snap['clock']})")
    wp = snap["win_probability"]
    print(f"Win probability: {home['short_name']} {wp['home']:.0%}  draw {wp['draw']:.0%}  {away['short_name']} {wp['away']:.0%}\n")

    print(f"{'':<22}{home['short_name']:>12}{away['short_name']:>12}")
    for label, key in TEAM_ROWS:
        if label.startswith("Shots"):
            hv, av = f"{h['shots']} ({h['shots_on_target']})", f"{a['shots']} ({a['shots_on_target']})"
        elif label.startswith("Yellow"):
            hv, av = f"{h['yellows']} / {h['reds']}", f"{a['yellows']} / {a['reds']}"
        else:
            hv, av = h[key], a[key]
            hv, av = ("-" if hv is None else hv), ("-" if av is None else av)
        print(f"{label:<22}{hv!s:>12}{av!s:>12}")

    p = snap["patterns"]
    lead = home["short_name"] if p["momentum"] > 0.1 else away["short_name"] if p["momentum"] < -0.1 else "neither side"
    print(f"\nLast {p['window_minutes']:.0f} minutes: momentum {p['momentum']:+.2f} ({lead} on top), "
          f"chaos {p['chaos']:.2f}, tempo {p['tempo']} passes/min")
    print(f"  High pressures/min: {home['short_name']} {p['pressure'][home['id']]}, {away['short_name']} {p['pressure'][away['id']]}"
          f"   Field tilt: {home['short_name']} {p['field_tilt'][home['id']]:.0%}")

    ranked = sorted(snap["players"].values(), key=lambda x: -x["rating"])
    print(f"\nTop {args.top} ratings:")
    for x in ranked[:args.top]:
        extra = ", ".join(f"{k} {v:+.2f}" for k, v in list(x["by_category"].items())[:3])
        print(f"  {x['rating']:>4}  {x['name']:<20} {x['team_id']} {x['position']:<3} {x['minutes']:>4.0f}'  {extra}")

    if args.player:
        match = [x for x in snap["players"].values() if args.player.lower() in x["name"].lower()]
        for x in match:
            print(f"\n{x['name']} ({x['team_id']} {x['position']}), rating {x['rating']} after {x['minutes']:.0f} minutes")
            print(f"  Passes {x['passes_complete']}/{x['passes']}, key passes {x['key_passes']}, shots {x['shots']} "
                  f"(xG {x['xg']}), goals {x['goals']}, assists {x['assists']}, dribbles {x['dribbles_won']}/{x['dribbles']}, "
                  f"tackles won {x['tackles_won']}, interceptions {x['interceptions']}, threat added {x['xt_added']}")
            print("  By category: " + ", ".join(f"{k} {v:+.2f}" for k, v in x["by_category"].items()))
            print("  Biggest moments:")
            for m in x["key_moments"]:
                print(f"    {m['clock']:>6}  {m['delta']:+.2f}  {m['label']}")

    print(f"\nSignals ({len(it.signals)}):")
    for s in it.signals:
        who = s.get("player_name") or s.get("team_id") or ""
        d = s["data"]
        detail = ""
        if s["type"] == "goal":
            detail = f"win prob swing {d['win_prob_swing']:+.0%}" + (f", assist {d['assist_player_name']}" if d.get("assist_player_name") else "")
        elif s["type"] == "milestone":
            detail = f"{d['milestone'].replace('_', ' ')} {d.get('count', '')}".strip()
        elif s["type"] in ("rating_jump", "rating_drop", "rating_milestone"):
            detail = f"now {d['rating']}"
        elif s["type"] in ("momentum_swing", "dominance"):
            detail = f"momentum {d['momentum']:+.2f}"
        elif s["type"] == "pressing_spell":
            detail = f"{d['high_pressures_per_min']} high pressures/min"
        print(f"  {s['clock']:>6}  {s['type']:<18} {who:<22} {detail}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"snapshot": snap, "signals": it.signals}, f, indent=1, ensure_ascii=False)
        print(f"\nWrote {args.json}")


if __name__ == "__main__":
    main()
