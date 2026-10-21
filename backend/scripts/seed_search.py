"""Find seeds whose match tells a chosen story, for demo matches.

    python scripts/seed_search.py --story comeback --home POT --away CAR
    python scripts/seed_search.py --story late_winner --count 3 --save ../samples --name late-winner-POT-CAR

Stories: comeback, late_winner, red_card_swing, high_scoring, goalless, thriller
"""

from __future__ import annotations

import argparse

from pitch_insights.generate import summary
from pitch_insights.generator.engine import simulate
from pitch_insights.generator.io import write_match


def goals(events):
    return [e for e in events if e["type"] == "shot" and e["outcome"] == "goal"]


def score_before(events, home, away, seq=float("inf")):
    """Score from the goals before event `seq` (the final score by default)."""
    g = [e for e in goals(events) if e["seq"] < seq]
    return sum(e["team_id"] == home for e in g), sum(e["team_id"] == away for e in g)


def story_matches(story: str, meta: dict, events: list[dict]) -> bool:
    home, away = meta["home"]["id"], meta["away"]["id"]
    fh, fa = score_before(events, home, away)
    if story == "comeback":
        at70 = next(e["seq"] for e in events if e["period"] == 2 and e["minute"] >= 70)
        h70, a70 = score_before(events, home, away, at70)
        return (h70 < a70 and fh > fa) or (a70 < h70 and fa > fh)
    if story == "late_winner":
        if fh == fa:
            return False
        winner = home if fh > fa else away
        last = goals(events)[-1]
        return last["team_id"] == winner and last["minute"] >= 85 and abs(fh - fa) == 1
    if story == "red_card_swing":
        reds = [e for e in events if e["type"] == "foul" and e["card"] == "red"]
        if not reds:
            return False
        red_team = reds[0]["team_id"]
        other = away if red_team == home else home
        before = score_before(events, home, away, reds[0]["seq"])
        lead_before = (before[0] - before[1]) * (1 if other == home else -1)
        lead_after = (fh - fa) * (1 if other == home else -1)
        return lead_before <= 0 < lead_after
    if story == "high_scoring":
        return fh + fa >= 5
    if story == "goalless":
        return fh + fa == 0
    if story == "thriller":
        return fh + fa >= 4 and abs(fh - fa) <= 1
    raise ValueError(f"unknown story {story!r}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--story", required=True)
    ap.add_argument("--home")
    ap.add_argument("--away")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--max", type=int, default=2000, help="how many seeds to try")
    ap.add_argument("--count", type=int, default=5, help="stop after this many matches")
    ap.add_argument("--save", help="folder to save the first match found")
    ap.add_argument("--name", help="file name for the saved match")
    args = ap.parse_args()

    found = 0
    for seed in range(args.start, args.start + args.max):
        meta, events, debug = simulate(seed, args.home, args.away)
        if not story_matches(args.story, meta, events):
            continue
        found += 1
        print(f"seed {seed}: {summary(meta, events).split('  |')[0]}")
        if args.save and found == 1:
            print(f"  saved to {write_match(args.save, meta, events, debug, name=args.name)}")
        if found >= args.count:
            break
    if not found:
        print("No match found; try a larger --max")


if __name__ == "__main__":
    main()
