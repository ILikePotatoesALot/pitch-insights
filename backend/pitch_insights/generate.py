"""Generate synthetic matches.

    python -m pitch_insights.generate --seed 42
    python -m pitch_insights.generate --seed 42 --home POT --away CAR --out data
    python -m pitch_insights.generate --script scripts/derby.yaml
"""

from __future__ import annotations

import argparse
from collections import Counter

from pitch_insights.generator.engine import simulate
from pitch_insights.generator.io import write_match
from pitch_insights.generator.script import Script, load_script


def summary(meta: dict, events: list[dict]) -> str:
    home, away = meta["home"]["id"], meta["away"]["id"]
    goals = Counter(e["team_id"] for e in events if e["type"] == "shot" and e["outcome"] == "goal")
    types = Counter(e["type"] for e in events)
    return (f"{meta['match']['id']}: {meta['home']['name']} {goals[home]}-{goals[away]} {meta['away']['name']}"
            f"  |  {len(events)} events: " + ", ".join(f"{k} {v}" for k, v in types.most_common()))


def main(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--home")
    ap.add_argument("--away")
    ap.add_argument("--script", help="YAML match script")
    ap.add_argument("--out", default="data")
    ap.add_argument("--name", help="file name (without extension) instead of the match id")
    args = ap.parse_args(argv)

    script = load_script(args.script) if args.script else Script()
    seed = args.seed if args.seed is not None else script.seed
    if seed is None:
        ap.error("give --seed, or a script with a seed")
    meta, events, debug = simulate(seed, args.home, args.away, script)
    path = write_match(args.out, meta, events, debug, name=args.name)
    print(summary(meta, events))
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
