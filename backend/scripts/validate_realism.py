"""Check that generated matches look like real football.

Generates N matches across all pairings and compares averages with target ranges,
then checks each club's style shows up in its numbers. Exits 1 if any check fails.

    python scripts/validate_realism.py            # 300 matches
    python scripts/validate_realism.py -n 300 --start 1000
"""

from __future__ import annotations

import argparse
import itertools
import statistics
import sys
from collections import defaultdict

from pitch_insights.generator.engine import simulate
from pitch_insights.generator.players import load_clubs

# (label, key, low, high) – averages per team unless stated
TARGETS = [
    ("Passes per team", "passes", 400, 600),
    ("Pass accuracy %", "pass_acc", 75, 88),
    ("Shots per team", "shots", 8, 18),
    ("xG per match", "xg_match", 2.5, 3.5),
    ("Goals per match", "goals_match", 2.5, 3.0),
    ("Yellow cards per match", "yellows_match", 3, 4),
    ("Fouls per team", "fouls", 9, 13),
    ("Corners per team", "corners", 4, 7),
    ("Tackles per team", "tackles", 12, 22),
    ("Pressures per team", "pressures", 100, 180),
    ("Subs per team", "subs", 3, 5),
    ("Penalties per match", "pens_match", 0.2, 0.4),
    ("Red cards per match", "reds_match", 0.05, 0.2),
    ("Events per match", "events_match", 1600, 2000),
]


def team_stats(events: list[dict], team: str) -> dict:
    mine = [e for e in events if e.get("team_id") == team]
    passes = [e for e in mine if e["type"] == "pass"]
    shots = [e for e in mine if e["type"] == "shot"]
    return dict(
        passes=len(passes),
        pass_acc=100 * sum(e["outcome"] == "complete" for e in passes) / max(1, len(passes)),
        avg_pass_len=statistics.fmean(e["length"] for e in passes) if passes else 0,
        shots=len(shots),
        xg=sum(e["xg"] for e in shots),
        goals=sum(e["outcome"] == "goal" for e in shots),
        yellows=sum(e["type"] == "foul" and e["card"] == "yellow" for e in mine),
        fouls=sum(e["type"] == "foul" for e in mine),
        corners=sum(e["type"] == "pass" and e["kind"] == "corner" for e in mine),
        tackles=sum(e["type"] == "tackle" for e in mine),
        pressures=sum(e["type"] == "pressure" for e in mine),
        subs=sum(e["type"] == "substitution" for e in mine),
        pens=sum(e["kind"] == "penalty" for e in shots),
        reds=sum(e["type"] == "foul" and e["card"] == "red" for e in mine),
    )


def run(n: int, start: int) -> int:
    clubs = sorted(load_clubs())
    pairings = list(itertools.permutations(clubs, 2))
    per_team: list[dict] = []
    per_match: list[dict] = []
    by_club: dict[str, list[dict]] = defaultdict(list)
    home_results = {"W": 0, "D": 0, "L": 0}
    for i in range(n):
        home, away = pairings[i % len(pairings)]
        meta, events, _ = simulate(start + i, home, away)
        h, a = team_stats(events, home), team_stats(events, away)
        per_team += [h, a]
        by_club[home].append(h)
        by_club[away].append(a)
        per_match.append(dict(xg_match=h["xg"] + a["xg"], goals_match=h["goals"] + a["goals"],
                              yellows_match=h["yellows"] + a["yellows"], events_match=len(events),
                              pens_match=h["pens"] + a["pens"], reds_match=h["reds"] + a["reds"]))
        home_results["W" if h["goals"] > a["goals"] else "D" if h["goals"] == a["goals"] else "L"] += 1

    failed = 0
    print(f"{n} matches, seeds {start}-{start + n - 1}\n")
    print(f"{'Check':<26}{'Average':>10}   Target")
    for label, key, lo, hi in TARGETS:
        rows = per_match if key.endswith("_match") else per_team
        avg = statistics.fmean(r[key] for r in rows)
        ok = lo <= avg <= hi
        failed += not ok
        print(f"{label:<26}{avg:>10.1f}   {lo}-{hi}  {'ok' if ok else 'FAIL'}")
    print(f"\nHome W/D/L: {home_results['W']}/{home_results['D']}/{home_results['L']} (real football: about 45/25/30 %)")

    print(f"\n{'Club':<6}{'style':<12}{'pass acc':>9}{'pass len':>9}{'pressures':>10}{'shots':>7}{'goals':>7}")
    means = {}
    for club_id, rows in sorted(by_club.items()):
        m = {k: statistics.fmean(r[k] for r in rows) for k in rows[0]}
        means[club_id] = m
        print(f"{club_id:<6}{load_clubs()[club_id].style:<12}{m['pass_acc']:>9.1f}{m['avg_pass_len']:>9.1f}"
              f"{m['pressures']:>10.1f}{m['shots']:>7.1f}{m['goals']:>7.2f}")

    style_of = {cid: c.style for cid, c in load_clubs().items()}
    def top(metric):
        return max(means, key=lambda c: means[c][metric])
    style_checks = [
        ("High-press club has the most pressures", style_of[top("pressures")] == "high_press"),
        ("Possession club has the best pass accuracy", style_of[top("pass_acc")] == "possession"),
        ("Direct club has the longest average pass", style_of[top("avg_pass_len")] == "direct"),
    ]
    print()
    for label, ok in style_checks:
        failed += not ok
        print(f"{label:<46}{'ok' if ok else 'FAIL'}")
    print(f"\n{'All checks passed' if not failed else f'{failed} check(s) failed'}")
    return 1 if failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=300)
    ap.add_argument("--start", type=int, default=1)
    args = ap.parse_args()
    sys.exit(run(args.n, args.start))
