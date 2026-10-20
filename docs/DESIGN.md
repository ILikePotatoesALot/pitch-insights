# Design: event format and synthetic generator v1

Agreed 20 Oct 2026. See [PLAN.md](PLAN.md) for the overall plan.

## Event format v1

### Messages

All messages are JSON Lines (one JSON object per line).

| Message | When | Contents |
|---|---|---|
| `match_meta` | Once, at the start | Match info, teams, lineups, players, history, pitch directions |
| `event` | Every on-ball action | See event types below |
| `frame` | v2 only | Positions of all players and the ball, 10 times a second |

Hidden generator values (match form, the script) go in a separate `match_debug` file, never in `match_meta`, so agents can't read them.

### Pitch and clock

- Pitch is 105 × 68 m. Coordinates are always from the acting team's attacking direction: `x = 105` is the goal they attack. `match_meta` records which way each team attacks in each period, so the frontend can flip back.
- `t` is seconds since the current period started. `period` is 1 or 2. `clock` is display text such as `"45+2'"`. `minute` is the minute number used for stats (first-half stoppage counts as 45).

### Fields on every event

`schema`, `match_id`, `seq` (starts at 1, no gaps), `source` (`synthetic` or `video`), `t`, `period`, `clock`, `minute`, `type`, `team_id`, `player_id`, `possession_id`, `x`, `y`, `under_pressure`, `confidence` (1.0 for synthetic).

### Event types (exactly 12)

| Type | Extra fields |
|---|---|
| `match_state` | `state`: kickoff, half_time, full_time |
| `pass` | `end_x`, `end_y`, `receiver_id`, `outcome` (complete, incomplete, out), `length`, `height` (ground, low, high), `kind` (open_play, cross, through_ball, long_ball, corner, free_kick, throw_in, goal_kick, kickoff), `difficulty` (0–1) |
| `carry` | `end_x`, `end_y`, `duration` (only carries over 3 m) |
| `dribble` | `outcome` (won, lost), `opponent_id` |
| `shot` | `xg`, `outcome` (goal, saved, off_target, blocked, woodwork), `body_part`, `kind` (open_play, penalty, free_kick, header, corner), `keeper_id` |
| `pressure` | `target_player_id` |
| `tackle`, `interception`, `recovery`, `clearance` | `outcome` |
| `foul` | `victim_id`, `card` (none, yellow, red) |
| `substitution` | `player_off_id`, `player_on_id` |

- A goal is a `shot` with outcome `goal`. A save is a `shot` with outcome `saved` and a `keeper_id`.
- Set pieces are a `pass` or `shot` with a `kind`.
- Not in v1: offside (future), injuries, VAR, shootouts, ball-receipt events.

### IDs

- Clubs: 3-letter codes, e.g. `POT`.
- Players: club plus squad number, e.g. `POT-07`.
- Matches: `SYN-<seed>`. Demo matches keep their seed and get a friendly file name in `samples/`.

### Enforcement

Pydantic models in Python validate every event. They are exported to JSON Schema, which generates the frontend's TypeScript types.

## Synthetic generator v1

### Engine

A loop of possessions. Each step:
1. Picks an action from the pitch zone, the player's role and attributes, the team's style and the script.
2. Picks a target (passes).
3. Decides the outcome. Pass success and `difficulty` come from a logistic formula on distance, pressure, forwardness and skill.
4. Adds defensive events (pressure from nearby opponents; tackles, interceptions or recoveries on turnovers).
5. Moves the clock by a realistic duration per action.

Shots: xG from distance, angle, header or foot, and pressure. Goals are decided by a roll adjusted for shooter skill and the keeper's rating.

### Positions

Recalculated every action:

```
position = formation anchor
         + team shift toward the ball
         + phase squeeze (defending) or stretch (attacking)
         + jitter (±1–2 m), clamped to the pitch
```

### Clubs and players

- 4 fictional clubs in a fictional league, one per style: possession, high press, direct, counter-attack. Named after vegetables: Potato FC (possession), Carrot FC (high press), Broccoli FC (direct), Cauliflower FC (counter).
- 20 players per club. Names use blended surnames and invented first names; no real full name or whole real surname.
- Attributes 0–100 (hidden ability): passing, vision, dribbling, shooting, pace, defending, pressing, stamina, aerial, plus goalkeeping. Also position, preferred foot, and a hidden match form value (−5 to +5) set by the seed.
- Match ratings (3.0–10.0, start at 6.0) are a separate, visible scale worked out from events in the Interpret stage.

### Match rules

- Matchday squad 11 + 9 on the bench; up to 5 subs in at most 3 windows (half-time doesn't count).
- Subs driven by fatigue, low match rating and yellow cards; like-for-like positions.
- Home advantage: about +3% on the home side's pass and shot quality.
- Fatigue: effectiveness drops after 60', faster for low-stamina players and high-press teams.
- Full 90' plus stoppage time, about 1,600–2,000 events.

### History (in `match_meta`)

- Players: season appearances, goals, assists, clean sheets, career goals for the club, last 5 match ratings.
- Teams: league position, last 5 results, current run, head-to-head record.
- Generated from the seed and the attributes.

### Scripts and seeds

- Scripts nudge probabilities only. Red cards and subs can be forced.
- A seed-search tool runs many seeds and keeps matches with a chosen storyline.
- The same seed always gives an identical match.

### Output

- Batch: a `.jsonl` file per match.
- Live: replay of the pre-generated match on the match clock at 1×, 5× or 20×, with seek and pause. Downstream code never sees ahead of the current event.

### Realism check

Averages over 100 matches must fall in these ranges, and each style must be visible (the high-press club has the most pressures, the possession club the highest pass accuracy, the direct club the longest average pass). The check fails otherwise.

| Stat | Target |
|---|---|
| Passes per team | 400–600 |
| Pass accuracy | 75–88% |
| Shots per team | 8–18 |
| xG per match | 2.5–3.5 |
| Goals per match | 2.5–3.0 |
| Yellow cards per match | 3–4 |

The check also covers fouls, corners, tackles, pressures, subs, penalties, red cards and events per match; see `backend/scripts/validate_realism.py` for the full list. It runs 300 matches by default, because 100 is too small a sample for goals.

### Tests

Same seed gives the same output; every event passes the schema; clock and `seq` always go up; lineups change only through subs.

### Environment

Python 3.12 `.venv` with pip. 2–3 demo matches committed in `samples/`; other output goes in the ignored `data/`.

## Later (not v1)

- v2 tracking frames by interpolating positions. Synthetic speed and distance labelled as estimates; the video path gives measured ones.
- Offside.
- A Scenario Director agent that writes scripts from a prompt.
