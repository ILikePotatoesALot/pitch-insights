# Design: event format and synthetic generator v1

Agreed 20 Oct 2026; Interpret stage added 20 Oct; video path designed, Moment Scorer and app added 21 Oct. See [PLAN.md](PLAN.md) for the overall plan.

## Event format v1

### Messages

All messages are JSON Lines (one JSON object per line).

| Message | When | Contents |
|---|---|---|
| `match_meta` | Once, at the start | Match info, teams, lineups, players, history, pitch directions |
| `event` | Every on-ball action | See event types below |
| `frame` | v2 only | Positions of all players and the ball, 10 times a second (see [Frame message](#frame-message-schema-11-as-built)) |

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
| `foul` | `victim_id`, `card` (none, yellow, red), `penalty` (true if the foul was in the fouling team's own box) |
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

## Interpret stage v1

Code in `backend/pitch_insights/interpret/`. The `Interpreter` reads events one at a time and never looks ahead, so it behaves the same on a live feed as on a replay. `snapshot()` returns the full state; `update()` returns any signals raised by that event.

### Stats

- **Team:** possession (share of passes), shots and shots on target, xG, big chances (xG 0.30+), passes and accuracy, progressive passes, final-third entries, crosses, corners, threat added (xT), pressures (and high pressures in the opponent's half), tackles, interceptions, recoveries, clearances, PPDA, fouls, cards, subs, men on the pitch.
- **Player:** minutes, touches, passes and accuracy, average pass difficulty and length, progressive passes and carries, key passes, assists, crosses, threat added, shots, xG, goals, dribbles, pressures, tackles, interceptions, recoveries, clearances, fouls committed and won, cards, saves, goals conceded.
- **Expected threat (xT):** a 12 x 8 grid learned from 400 generated matches with the standard Markov method (`scripts/build_xt.py`), stored in `interpret/xt_grid.json`. It can be relearned from real data without code changes.

### Patterns (rolling 5-minute window)

| Pattern | Meaning |
|---|---|
| Momentum | −1 (away on top) to +1 (home on top), from threat created (xT added + xG); smoothed minute by minute, plus a per-minute series for the chart, labelled with period, broadcast minute and clock |
| Pressure | High pressures per minute for each team |
| Chaos | 0 (calm) to 1 (frantic), from possession changes per minute |
| Tempo | Passes per minute, both teams |
| Field tilt | Each team's share of final-third passes |

### Win probability

Each team's goal rate for the rest of the match blends a prior (league average, adjusted for league position and home advantage, worth 45 minutes of evidence) with its xG rate so far. Each extra player is worth about 30% more goals. Remaining goals are Poisson, giving home/draw/away chances. At full time it is the result.

### Live player ratings

- Start at 6.0, range 3.0–10.0. Every event adds or subtracts points for the players involved, in categories: attacking, goals and assists, passing, defending, goalkeeping, discipline, errors, goals conceded.
- Goals and assists earn more when they swing the win probability (a 96th-minute winner is worth more than a fourth goal in a 4–0).
- Errors: a giveaway in a player's own third that leads to an opponent shot within 20 seconds costs points (more if it leads to a goal); so does giving away a penalty.
- Position weighting brings every position to a similar average while rewarding what that position is for. Goals and assists count fully for everyone.
- Playing-time damping: shown rating = 6.0 + points × minutes / (minutes + 15). Above 7.8, extra points count half (diminishing returns).
- Every contribution is logged, so each rating comes with totals per category and its biggest moments (for the "Why?" button). These are scaled exactly like the rating (damping, diminishing returns, limits), so they add up to the rating minus 6.0.
- Clean sheets: goalkeepers and defenders who played 60+ minutes earn a bonus, including those substituted late (not those sent off).
- Calibrated with `scripts/calibrate_ratings.py` against public rating systems: average 6.8, spread 0.76, best in match about 8.5, 9.5+ in about 10% of matches, and every position averaging 6.8–6.9 (see `docs/ratings-calibration.txt`).

### Signals

About 20 a match, each with the numbers behind it, for the Moment Scorer to rank: `goal` (with win-probability swing and assist), `red_card`, `penalty_awarded`, `big_chance_missed`, `momentum_swing`, `dominance`, `pressing_spell`, `chaos_spike`, `rating_jump`, `rating_drop`, `rating_milestone` (8.0, 9.0), `milestone` (brace, hat-trick, season goals and assists, club career goals, clean sheets, winning/unbeaten/losing runs extended or ended), `half_time`, `full_time` (with player of the match). Repeated signals have cooldowns.

### Known limits

- The generator's high press creates many pressures but not many extra high turnovers, so the high-press club's PPDA is not as low as a real pressing side's. The pressure index shows the pressing correctly.

## Explain stage: Moment Scorer v1

Code in `backend/pitch_insights/explain/moments.py`. `MatchBrain` wraps the Interpreter and the Moment Scorer: feed it events, get signals and moments back. It runs live, so each moment's importance is decided when it happens, from what is known then.

- **Grouping:** one moment per anchor signal (goal, red card, penalty awarded, big chance missed, half-time, full-time), with that event's milestones and rating signals attached. Without an anchor, a team's pattern signals merge into one moment, and a player's rating signals into another.
- **Importance (0–1):** goals from 0.6 plus up to 0.4 for the win-probability swing (more if late); red cards from 0.55 plus the swing; big chances from their xG, the score and the time; patterns, rating changes and milestones lower. Closer games and the last 15 minutes count a little more. Attached milestones add to the moment.
- **Tiers:** headline (0.6+), notable (0.35+), minor. Importance is capped at 1.0, but each moment also keeps its uncapped `rank`, so the biggest moments can still be ordered (the full-time summary lists the top three by rank). Calibrated over 120 matches (`scripts/calibrate_moments.py`): about 4 headlines and 10 headline-or-notable moments a match.
- **Evidence pack:** a list of facts, each with a `kind`, a plain-English `text` and the `value` behind it: score, win probability before and after, chance quality, assist, technique, goals this match and season, run of play, the last five minutes (momentum, field tilt, shots and corners), live rating, match totals. The Explainer agent may use only these facts.
- **Fallback headline:** plain-English text such as "Szobalenko puts Carrot ahead late", so the app works without a language model.

## Replay server and app v1

- **Server** (`backend/pitch_insights/server.py`, FastAPI): `GET /api/matches`, `GET /api/matches/{name}`, `GET /api/clubs` (the clubs and their squads, for the profile picker), and `WS /ws/replay/{name}?speed=20&from=0&at=0&lang=en&mode=casual&team=POT&player=POT-11&focus=xg` (the last four are the viewer's profile, see [Personalise](#personalise)). It streams `meta`, then `catchup` (when starting after kick-off: moments so far, state, and the last three minutes of events so the pitch redraws), then `event`, `moment`, `state` (about once a second, plus after shots and moments), `cue` and `cue_end` (overlays), then `end`. The browser can send speed, pause and resume; seeking reconnects with a new `from` (a minute on the broadcast clock) or `at` (match seconds, which wins): a minute can say 47:00 of the second half but not 45+2 of the first, so a language change, which reconnects at the same moment, goes by seconds. Speed is held between 0.1× and 600×. The replay and the command listener run together, so a disconnect (even while paused) ends both.
- **App** (`frontend/`, Vite + React + TypeScript + Three.js):
  - **3D pitch:** a 1 m grid whose height and colour come from each team's recent activity (fading over about two match minutes), so the seam between colours shows who controls which space. Shots rise as spikes sized by xG; goals glow. Pitch lines are a texture on the same surface, so they bend with it.
  - **Panels:** scoreboard with live win probability, a momentum chart, the key-moments feed with a "Why?" button that shows the evidence, live ratings with a player card (rating breakdown and biggest moments), and match stats.
  - **Viewer modes (the first step of [Personalise](#personalise), which now builds on them):** casual fans see headline moments only, without the stats panel; analysts see notable moments too (and minor ones if they ask), the stats panel, and an extra fact on the banner.
  - **Overlays:** timed cues from the [Overlay Director](#overlay-director) show over the pitch (not for moments restored by a catch-up); a Broadcast/Fan switch hides or shows the side panel. This replaced the first version's banner for each headline moment.
  - **Connection:** a dropped connection shows a message; jumping to a minute reconnects. A jump belongs to its match, so picking another match starts it from kick-off.

## Agents

Designed 21 Oct 2026; the core (steps 3, 4 and 7 below, plus stored commentary) and the Memory agent (step 2) built the same day and merged in ILikePotatoesALot/pitch-insights#4. The agents turn the Moment Scorer's evidence packs into commentary, check it, and fit it to each viewer. They are built with **Microsoft Agent Framework** and share one state: the `MatchBrain` (Interpreter plus Moment Scorer), which the agents read but never change.

### Model access

- **Subscription:** Austin's personal Pay-As-You-Go subscription (a free trial upgraded, so the free credit is spent first), with a US$20 monthly budget alert. Everything is in resource group `rg-pitch-insights`, region **East US 2**.
- **Deployed and tested (21 Oct):** `gpt-4o` (model version 2024-11-20, retires April 2027, after judging ends on 10 Nov) and `text-embedding-3-small`, both on the Foundry resource's **v1 API** (no API version needed).
- **Refused (21 Oct):** quota for `gpt-6-luna` (GPT-6's small, cheap tier). The agents stay on `gpt-4o`, so stored commentary and a low `max_tokens` keep costs down.
- **Why not the school subscription:** the Azure for Students subscription could only deploy to five Asian regions, had no chat-model quota in any of them, and quota requests were refused automatically. It's no longer used.

### Chat model provider

One setting in `.env`, `LLM_PROVIDER`, picks where chat calls go. The agent code doesn't change:

| Provider | Use | Notes |
|---|---|---|
| `foundry` (default) | Development, stored commentary, live mode | Foundry deployment from `.env` (GPT-4o), low rate limit |
| `github` | Fallback if Foundry has problems | GitHub Models: free with a GitHub token (`GITHUB_TOKEN`, Models permission); daily rate limits |
| `foundry_local` | Offline experiments | Foundry Local through Agent Framework's `FoundryLocalClient`; small models (Phi, Qwen) on the CPU, slow but free |

Every stored or streamed commentary line records which provider and model wrote it.

**Network note:** the development machine's network inspects HTTPS, so Python's bundled certificate list rejects Azure's certificates. The chat client verifies against the operating system's store through `truststore`; verification is never turned off.

### The agents and how they hand off

For each headline or notable moment, in order:

1. **Moment Scorer** (code, built): the moment and its evidence pack.
2. **Memory agent** (Foundry embeddings; built 21 Oct): finds similar earlier moments in this match ("Carrot's second big chance down the left") and adds them to the pack as `memory` facts. See [Memory agent](#memory-agent).
3. **Explainer** (chat model; built): why the moment matters, from the pack only. Two voices: casual (one or two plain sentences) and analyst (adds the numbers: xG, win-probability swing, momentum).
4. **Groundedness check** (code, no model needed; built): every number in the text, and every player or club the league knows, must be in the pack. Numbers may be rounded decimals (3.88 as 3.9), percentages of a probability (0.9669 as 97%), number words in the facts ("five minutes" backs "5 minutes") or stoppage time as a minute (90+6' as 96th); whole numbers must otherwise match exactly. Numbers written as words are read whole and checked the same way ("ninety-three" is 93, "ninety-third" is 93rd, "a hundred and five" is 105); a lone "one", "zero" or ordinal ("second half") isn't, since those are rarely counts. The two clubs playing are always allowed. The score is the share of claims the pack supports. If anything is unsupported, the writer gets one retry with the unsupported claims named; if it fails again, the moment falls back to the Moment Scorer's headline. What the check caught is kept (`corrected`) and shown under "Why?". It can't catch claims without a name or number ("dominating" with only 33% of final-third passes), so Foundry's groundedness evaluator gives a second opinion on the stored commentary (see [Foundry groundedness evaluator](#foundry-groundedness-evaluator)).
5. **Safety check** (Azure AI Content Safety; built 22 Oct): screens grounded text before it can reach the screen. Blocked at severity 2 or more in any category, and if the service can't be reached; either way the moment falls back to the plain headline. See [Safety check](#safety-check).
6. **Translator** (Azure AI Translator; built 22 Oct): the viewer's language (Spanish, French, German, Dutch, Simplified Chinese). Player and club names and match clocks are protected from translation, and each translation is checked for lost names and numbers. See [Translations](#translations).
7. **Narrator** (chat model; built): short lines between big moments (momentum turning, dominance, pressing spells, rating milestones), with the same checks. The order above is the data flow, not the build order.
8. **Personalizer** (deterministic code, not a model call; built 23 Oct): picks what each viewer sees from their profile (casual or analyst, club, favourite player, language, focus metric). The profile reaches the Overlay Director, which boosts, filters and adds alerts; the language picks the stored translation. See [Personalise](#personalise).
9. **Overlay Director** (deterministic code, not a model call; built 23 Oct): turns the moments, stats and rating changes into timed overlay cues (time, duration, priority, template, data) and applies the clutter rules, so the screen never fills up. See [Overlay Director](#overlay-director).
10. **Scenario Director** (live simulation only): steers a live match with interventions, logged so the match replays exactly.

Failure handling is part of the design, because the Multi-Agent prize judges recovery: a timeout, a rate limit or a failed check never blocks the match. The moment shows its fallback headline at once and is upgraded if better text arrives in time.

### Memory agent

Code in `backend/pitch_insights/agents/memory.py`. For each headline or notable moment worth remembering (goals, big chances, penalties, red cards, momentum swings, dominance and pressing spells):

1. **Describe.** One sentence on how the moment came about, built in code from the moment and the events of the attack that led to it: team, player, cross, through ball, corner, header, long-range, which flank (each a third of the pitch's width), on the break (within 15 s of winning the ball in its own half). For example, "Carrot FC goal down the middle: a shot from a pass, by Gyokerland." This sentence is what gets embedded, not the evidence pack, whose score, ratings and win probability would make every moment look alike. It names only the scorer, at the end, so a shared passer can't make two different chances look alike.
2. **Filter in code.** Only earlier moments of the same family (a goal and a big chance are both chances), from the same team (either team for red cards). It runs inside `MatchBrain` as each moment happens, so it can only see earlier moments; there are tests for that.
3. **Rank.** Cosine similarity of the sentences' embeddings (Foundry `text-embedding-3-small`, shortened to 256 dimensions). Keep the best two (chances) or one (the rest) at **0.83 or above**. Nothing similar enough means no memory facts at all.
4. **Add facts.** One `memory` fact per similar moment ("Earlier in this match, at 15': Gyokerland scored with a shot from Mbeulier's pass down the right (xG 0.18).") and a count made in code, never from similarity ("That makes 4 Carrot goals or big chances in this match, 3 of them down the middle."). The names, minutes and numbers are in the facts, so the groundedness check accepts them. The similarity is kept beside the fact, not in its `value`, so it can't back a number in the commentary. Like every fact, the count's numbers are then accepted anywhere in the text (a wrong "3 shots" would pass if the count is 3); the check can't tie a number to what it counts.

**Why a step in code, not an Agent Framework context provider.** A context provider's `before_run` would add the memories to the agent's instructions, outside the evidence pack. The groundedness check, the stored commentary's `input_hash` and the app's "Why?" all read the pack, so they wouldn't see them: the check would reject the names and minutes the memories bring, and changed memories wouldn't trigger regeneration. Agent Framework's vector store contracts are also still experimental. So the step is deterministic code, like the rest of the orchestration.

**Embeddings ahead of time.** `scripts/embed_moments.py` collects every description the agent would ask for, embeds only the ones not already stored (one request per match), and writes `samples/<name>.memory.json`: the model, the dimensions, and each description with its vector (base64 float32, about 1.4 KB each). Vectors are looked up by their exact description, so a changed description has no vector (and so no memory) until the script is re-run. The replay server and the stored-commentary script load these files (once per file version) and never call the network. The files must ship with the samples: without them, moments have no memory facts, so stored commentary written with those facts no longer matches and isn't shown. The server logs `memory_vectors_missing` when that happens, and a test checks that every sample's file covers every moment. Live mode can use `FoundryEmbedder` instead: a failure after the SDK's own retries means no memory facts for that moment and a one-minute pause; a 400 skips just that moment; a bad key, missing access or wrong deployment (401, 403, 404) turns memory off for the match.

**Calibration (22 Oct, after the code review).** Across the three samples, same-team chance pairs scored 0.58–1.0. Chances by the same scorer scored 0.81–1.0; by different scorers 0.58–0.83, and the flank barely moves the score (a goal down the middle against one down the left by another player: 0.82). So the threshold sits at 0.83, and in practice a chance links to the same player's earlier chances; the flank and build-up story comes from the count fact, which is exact. With it, 16 of the 52 commented moments get memory facts. The first version put the passer's name in the sentence too, which linked Musialetti's open-play equaliser to Mbeulier's corner goal at 0.87 only because Mbeulier was in both. Pattern moments of one family and team describe themselves identically, so for them the filter decides and similarity only breaks ties (the most recent wins).

**Not done: a season of other matches.** The design allowed memories from a generated season. Left out for now: `match_meta` already carries each player's and club's season history, generated separately, so memories from a season of simulated matches could contradict it ("his 3rd goal of the season" beside a season index that has him on five), and "in another generated match" reads oddly to a fan. Austin to decide.

### Safety check

Code in `backend/pitch_insights/agents/safety.py`, over plain REST (Content Safety `text:analyze`, API version 2024-09-01), so no extra package.

- **What's screened:** each moment's two lines together, after they pass the groundedness check. Ungrounded drafts never reach the service, since they fall back anyway.
- **Categories and threshold:** hate, self-harm, sexual and violence, at the four-level scale (0, 2, 4, 6). A line at **2 or more** in any category is blocked (`SAFETY_BLOCK_AT` in `.env`, 2 to 6). Commentary from match facts should score 0, so the strictest level costs nothing.
- **Threshold test (22 Oct):** all 104 stored lines scored 0 in every category, and so did rough football wording ("a crunching tackle", "hacked down in the box", "murdering them on the counter", "kill the game off"). A clearly threatening line about a referee scored Violence 4 and was blocked.
- **Fails closed:** a timeout (30 s for the whole check, retries included), a network error or an error status means the line isn't shown; the plain headline is (built in code from the facts, so it needs no check). An unchecked line isn't an unsafe one, so its draft is kept in the record as `pending`, and the next run of `generate_commentary.py` screens it again without calling the model; a stored line that was never screened is taken out of view too while the service is down: the headline stands in and its text waits as `pending`, so nothing unchecked is shown. `pending` stays on the server (`with_commentary` leaves it out of what the browser gets). The free tier allows only a few requests a second, so 429s are retried with backoff that honours `Retry-After` (`clients.post_with_retry`, shared with the Translator).
- **Stored commentary:** each record keeps the result (`safety`: passed, severities, flagged). Lines written before the check existed are screened by `generate_commentary.py` without calling the model again. All 52 stored moments are screened, none blocked.

### Translations

Code in `backend/pitch_insights/agents/translate.py` and `scripts/translate_moments.py`, over plain REST (Translator text translation v3.0, `textType=html`).

- **What's translated:** every moment's headline and facts, and its commentary lines when the agents wrote some, into Spanish, French, German, Dutch and Simplified Chinese. The app's labels stay English for now (that's part of Personalise).
- **Protected text:** every player (full name and surname) and club in the league, and every match clock (6', 45+2'), wrapped in `<span class="notranslate">`. Clocks matter: German read "at 6'" as six feet ("1,80 m").
- **Clean-up:** the service drops the space next to a protected name ("Potatozweite"), so outside Chinese a space is put back where a word runs into a name.
- **Check:** every protected name and clock, and every number, in the English must be in the translation, reading a decimal comma as a point (German "3,88") and digits next to Chinese characters ("高0.75"). Small ordinals may become words ("3rd" is "drittes", "tercer"). A text that fails keeps its English, isn't sent again unless the script is run with `--retry`, and is counted in the file (`kept_english`).
- **Ahead, not live:** stored in `samples/<name>.translations.json` with a hash of the English it came from, so a replay never calls the network and a changed English text isn't shown in a stale translation. The server sends moments in the language the app asks for (`lang` on the WebSocket; unknown languages fall back to English), and the app's language menu reconnects from the current minute.
- **Free tier:** characters count once per target language; the tier allows 2 million a month and about 33,300 a minute, so requests carry at most 1,000 source characters and are paced to 30,000 a minute.
- **Results (22 Oct):** 636 texts across the three samples, so 3,180 translations; 9 kept their English after the check (German 5, Simplified Chinese 4, Dutch 1). About 670,000 characters were counted across the day's runs and fixes, a third of the month's free allowance; re-running when nothing changed costs nothing.
- **Labelled:** the app says moments are machine-translated, and "Why?" names Azure AI Translator.
- **Known limit:** idioms can come out wrong while every name and number survives, so the check can't catch them. "Carrot turn up the pressure" became "把新闻加大点" in Chinese (roughly "turn up the news"). Changing language keeps the match where it was, paused or not.

### Overlay Director

Code in `backend/pitch_insights/director/` (`cues.py`: what to show; `scheduler.py`: what is on screen now; `sheet.py`: a whole match's cues worked out offline), built 23 Oct and merged in ILikePotatoesALot/pitch-insights#12. It is **deterministic code, not a model call**: Microsoft's guidance is to use the lowest level of complexity that reliably meets the requirements, and a fixed set of rules decides overlays predictably, auditably and with no GPT-4o call to ration. (It sits in the agents' hand-off list because it is the stage that turns their output into what the viewer sees.)

**Cues.** Each cue is plain JSON, the contract with the app (`frontend/src/types.ts`, `Cue`):

| Field | Meaning |
|---|---|
| `id` | `C-n`, assigned in the order cues are offered |
| `time` | match seconds of what the cue is about |
| `duration` | seconds on screen, whatever the replay speed |
| `priority` | 0-100: decides who is dropped, delayed or pre-empted |
| `template` | `lower_third`, `stat_card`, `player_tag`, `rating_alert`, `speed_popup` or `fan_alert` (added by [Personalise](#personalise)) |
| `tier`, `detail` | the moment's tier; who the cue is for (`casual` is everyone, `analyst` only analysts) |
| `about` | `{team_id, player_id}`, so a per-viewer filter (favourite club or player) can match on it |
| `topic` | a player's cards on one template, so he isn't announced twice in a row |
| `moment_id`, `data` | the moment it came from; what the template shows (numbers and keys; labels such as "Possession" belong to the app) |

**Cues from moments** (`CueBuilder`), built from the moment as the viewer sees it, so commentary text is already in their language, and from the live state for stats:

| Moment | Cues |
|---|---|
| goal, red card | lower-third (priority 90 or more, so always urgent) and a player tag (name, number, position, live rating) |
| penalty, big chance, milestone, momentum swing, dominance, pressing spell (notable or headline) | lower-third; story moments (milestones, patterns) are capped at 70 so they never outrank an event |
| half-time, full-time | lower-third and a summary stat card (possession, shots, on target, xG, pass accuracy); the summary cards are urgent, so another card's cooldown can't hold them back |
| momentum swing, dominance | "who is in control" stat card (field tilt, possession, shots, xG), analysts only |
| pressing spell | pressing stat card (high pressures, PPDA, tackles, interceptions), analysts only |
| rating jump, drop or milestone | rating alert, analysts only, priority 20-60 |
| (no source yet) | speed popup: built and tested; the video clip doesn't use it, because its speeds reach 11.7 m/s through ID switches (see [Clip in the app](#clip-in-the-app-built-23-oct-branch-claudevideo-clip-143958)) |

Priority is `50 + 50 * importance` for lower-thirds and `30 + 30 * importance` for stat cards; a lower-third stays up 6 seconds, plus a quarter second for each word past fifteen, up to 10 (each Chinese or Japanese character counts as 0.6 of a word, since those have no spaces).

**Clutter rules** (`Rules`, all config):

- one cue per template at a time, so **at most one lower-third**; at most **2 cards** (everything but the lower-third) and **3 cues** on screen;
- a **cooldown** after a card ends before the next of its template (stat card 20 s, rating alert 15 s, speed popup 12 s, player tag 8 s) and 45 s for the same player's card on one template; lower-thirds have none, and urgent cues (priority 90 and up) skip cooldowns, never the limits;
- **pre-emption:** a cue that outranks an occupant by 10 takes its place once the occupant has been up for its minimum hold (4 s for a lower-third, 2 s for a card), so nothing flashes; urgent cues don't queue behind each other: the newest replaces an older one on screen after the hold, never the other way round, and when an urgent cue starts it drops the older urgent cues of its template still waiting (`superseded`), so an older goal banner can't show after a newer one (two goals in quick succession both show);
- **delay, then drop:** a cue that can't start waits in a queue of 4, highest priority first, then oldest; it is dropped when it has waited longer than its template's `max_delay` (lower-third 8 s, stat card 12 s, player tag 3 s, rating alert 10 s, speed popup 2 s), because a late overlay is a wrong one, or when the queue is full (the lowest priority goes). Dropped cues are kept in `director.dropped` with the reason.

**Time.** The scheduler has no clock of its own; every call says what time it is, in *screen seconds*: match time divided by the replay speed in force when it passed (`ShowClock`, which pausing stops and a speed change only affects going forward). So a cue lasts as long on the screen at 60x as at 1x, and the same cues at the same times always give the same messages. The server runs one Director per connection, offers the cues when a moment arrives, and also wakes every 0.25 s between events so cues end and start on time in a quiet spell; a seek or language change reconnects, so cues start afresh. `cue_sheet(meta, events, pace)` runs the same Director over a whole match offline, one match at one speed giving the same sheet every time (`scripts/calibrate_director.py` prints it and checks the rules).

**Protocol.** The server sends `{"type": "cue", "cue": ...}` when a cue starts (with a `delay` if it waited) and `{"type": "cue_end", "id", "reason": "expired" | "preempted" | "withdrawn"}` when one goes. The server watches the time, so a pause freezes the overlays too, and the app only draws what it is told. After the final whistle the server sends `end` and keeps the connection open until the last cues are down, then closes it.

**App.** `components/Overlays.tsx` draws one flex layer over the pitch: a top band (rating alert and speed popup on the left, the stat card on the right, wrapping under the alerts on a narrow screen) above a bottom column (player tag over the lower-third). Flow layout rather than positioning each region means cues can't overlap whatever their height or the screen's width (checked at 390 px wide); if a short pitch ever runs out of room, the bottom column is clipped, not drawn over the top. Cues slide in sideways. Casual fans see the cues made for everyone (`detail: "casual"`: headline lower-thirds, goal tags, summary cards); analysts see all of them. **Broadcast** layout shows the pitch with its overlays only; **Fan** adds the side panel (moment feed, ratings, stats). The old banner and its timer are gone: the Director replaces them.

- **Results (23 Oct, `calibrate_director.py`):** the screen never broke a rule over the three samples at 1x, 20x and 60x. At 1x the comeback match shows 57 cues (25 lower-thirds, 16 stat cards, 11 rating alerts, 5 player tags), the other two 23 and 29; at 60x, 32, 19 and 25, with 7, 2 and 2 cues pre-empted and 16, 5 and 7 delayed. Every goal, red card and final whistle, and the full-time summary card, reaches the screen in every sample at 1x, 20x and 60x (checked in a test).
- **Viewer mode:** the app tells the server the viewer's mode (`{"cmd": "detail", "value": "casual" | "analyst"}`, sent when it connects and whenever the switch changes), and the server offers the Director only the cues that viewer gets, so analyst-only cues can't hold a slot, a cooldown or the card limit on a casual fan's screen (found in the browser: a casual fan's full-time card was dropped for a pressing card they never saw). [Personalise](#personalise) extends the same hook with the favourite club and player (cues carry `about`, `tier` and `detail`, which is what it matches on).
- **Switching mode mid-match:** the server notices at its next tick (0.25 s), takes down the cues on screen that the viewer would never see (`cue_end`, reason `withdrawn`) and drops the waiting ones, leaving no cooldown behind, so they can't hold slots or delay visible cues (`Director.withdraw`). Only the play task writes to the connection; the command handler just records the new mode.
- **Known limits:** a cue that was up when speed changes keeps its remaining screen seconds at the new speed. A speed change leaves a cue on screen for its remaining screen seconds at the new speed. The app's overlay labels ("Possession", "Match summary") are English only, like the rest of its chrome.

### Personalise

Built 23 Oct on branch `claude/personalise-95bc8a` (cut from the Overlay Director's). Code in `backend/pitch_insights/director/personalise.py` and, in the app, `profile.ts`, `components/ProfilePicker.tsx`, the spotlight in `pitch/PitchScene.ts`, the pinned card and focus strip in `components/Panels.tsx`, and `CompareView.tsx`. It is **deterministic code, not a model call**: the same profile over the same match gives the same cues (`cue_sheet(..., profile=...)` is the offline proof, and tests rerun it).

**The profile** is five choices and nothing else: mode (casual or analyst), language, favourite club, favourite player and one focus metric (win probability, xT, xG, pass accuracy, possession or shots). No name, account, id or history is stored or sent, and the app never infers anything from what a viewer does; every choice is explicit.

| Where | What |
|---|---|
| Browser | Saved with `localStorage` behind a three-method interface (`ProfileStore`: `load`, `save`, `clear`; every read and write in try/catch, and data read back is sanitised). The Azure deployment swaps in a `RemoteProfileStore` (Cosmos DB, one document per anonymous viewer, partitioned by that id) without touching the app. |
| First visit | A welcome picker (club, player, mode, language, focus); everything is optional, "Skip" saves the defaults. Editable later from the header's profile chip; "Clear my profile" deletes it. |
| Link | `/?team=POT&player=POT-11&mode=casual&lang=de&focus=xg` sets a profile for that tab only: it is never saved, so two tabs with two profiles don't overwrite each other, and edits update the link. Also `match=`, `layout=broadcast`, `speed=`. |
| Side by side | `/?compare=1` shows two panes (two iframes, each a whole app with its own link): a Potato fan watching casually in German and a Carrot analyst in English, on the same match. `a=` and `b=` take any pane's query string. The header's "Compare viewers" opens it for the current match. |
| Server | The profile goes with the WebSocket connection as `mode`, `team`, `player` and `focus` query parameters, so the Director knows the viewer before the first cue. `parse_profile` checks every value against the match: missing, malformed, over 40 characters, not a string, a club that isn't playing or a player nobody plays are each ignored (that choice falls back to its default; it never raises). The server answers with the profile as it applied it (`meta.profile`). A change of club, player, focus metric or language reconnects from the current second (as a language change already did); a change of mode needs no reconnect (`detail` command). |

**What the Director does with it** (`Personaliser`; thresholds in `PersonaliseRules`):

- **Boost.** A cue about the favourite player gains 20 priority and one about the favourite club 10, capped at 89 so a boost can never turn a story cue into an urgent one (urgent cues skip cooldowns and replace each other). Each boosted cue carries `why` (`favourite_player` or `favourite_club`), which the app shows as a star: the viewer can see why it is there. A viewer who picked only a player counts that player's club as their side.
- **Alerts** (`fan_alert` template, a card, made for everyone so casual fans get it): the favourite scoring (priority 92), a red card (90), an assist (82, from the goal moment's `assist` fact), a booking (70, from the foul event, since a yellow card makes no moment) or a rating jump, drop or milestone (65, the Interpreter's own thresholds). The alert carries their live rating and tally. It replaces the generic player tag or rating alert for the same moment, so the favourite isn't announced twice.
- **Relevance.** A viewer with a side doesn't spend a slot, a cooldown or the card limit on a rating alert or speed popup about a player of the other side (never the favourite player's own, never anything urgent). The other side's goals, cards, stats and lower-thirds still come.
- **Never hidden.** Every goal, red card, summary and the final whistle reaches every viewer (a test replays the match at 60x under three profiles). Personalising is for emphasis; it never removes the match.
- **Focus metric.** A stat card shows it as its first row, marked `focus` (a metric the card already had is moved to the front, not repeated). The app also shows it under the scoreboard for both teams, highlights it in the stats table and puts the favourite's own figure first on the pinned card.

**In the app.** The ring and beam follow the favourite player on the 3D pitch, with a label held inside the pitch's box. The synthetic events have positions but there is no tracking yet, so the spotlight sits where the player last took part (a pass, a carry, a pass received, a tackle) and glides there, and it hides while the player is off. The pinned card shows the live rating, its change over the last ten match minutes and a sparkline, and the stats that suit the mode (casual: goals, assists, shots, passes; analyst adds xG, xT added, key passes and tackles). A casual fan sees the big moments in their language; an analyst sees evidence, stats and rating alerts.

**What Microsoft's guidance says, and what we did** (the rows are in the practices table below):

- Azure AI Personalizer isn't an option: Microsoft stopped new resources on 20 Sep 2023 and retires the service on 25 Aug 2026, pointing to the open-source learning-loop. A bandit that learns from clicks also needs traffic we won't have in a three-minute demo, and the viewer's explicit choices already say what they want, so rules are the lowest level of complexity that works.
- Its data guidance applies to any personalisation: send aggregated features, never a user id, email or phone number; keep data only as long as needed and give the user a way to clear it; avoid personalising what is consequential and keep essential content in play.
- The HAX Toolkit's guidelines for human-AI interaction: G17 (provide global controls), G11 (make clear why the system did what it did) and G13/G14 (learning from behaviour, adapting cautiously: we deliberately don't learn from behaviour).

**Not built, for Austin to decide: a Personalizer model call.** It would add real value in exactly one place: a one-sentence full-time recap written for each viewer ("Madekuta scored twice and finished on 7.8: your best match of the season"), from the viewer's profile and the match's headline moments, through the Narrator with the same groundedness and safety checks. That is one GPT-4o call per viewer-match at the final whistle (about 200 tokens), so it should be stored for the demo viewers rather than live. Everything else a model could do here (choosing cues, ordering) the rules already do predictably and for free.

**Known limits.** The spotlight is approximate (the last event, not tracking; the video path's frames would give true positions). The app's labels, including the alerts' wording ("scores", "is booked"), are English only, like the rest of its chrome. The sparkline starts again when the match is jumped back or the player changes. Cues on screen and waiting are cleared when a profile change reconnects (the same as a language change). Two compare panes start at the same time but are each on their own server clock, so they can drift by a second or two. A profile can't be moved between browsers until the Cosmos DB store exists.

**Tests** (`tests/test_personalise.py`, plus the server's): parsing and validation (each bad input kind, case and spaces forgiven, each choice checked on its own), the boost (club, player, cap below urgent, the original cue untouched, a boosted cue pre-empting where an unboosted one wouldn't), relevance, focus rows for every metric on a real state, each alert on the comeback sample (the scorer's goal at 1' and 61', the passer's assists, a booking, rating changes, the tag replaced only for the favourite's own goal), determinism for three profiles, the clutter rules and every goal still shown under each profile at 60x, and over the wire: the profile echoed back, junk ignored, the alert reaching a casual fan, two viewers getting different cues.

**Checked in the browser (23 Oct):** a Potato fan (casual, German, xG) and a Carrot analyst (English, xT) side by side on the comeback match looked clearly different (language, side-panel and stat-card content, pinned card, focus strip, spotlight in each club's colour); the spotlight moved with the player; alerts fired for the scorer (1'), then for a second viewer's player: booked (47'), scoring (88') and assisting (90+6'); a profile change mid-match carried on from the same minute; the stored profile held only the five choices. At 390 px wide, over a full match at 60x in two profiles, the overlay layer never had two cues overlapping, never more than three on screen and no horizontal page scroll.

### Stored commentary for the demo

- `scripts/generate_commentary.py` runs the agents over each sample match (headline and notable moments only) and stores the results in `samples/<name>.commentary.json`. The file records `ai_generated`, provider, model, prompt version and a summary; each moment's record has the agent, status (`ok` or `fallback`), both voices, attempts, the groundedness result, what was `corrected`, and an `input_hash` of exactly what the writer was shown.
- Re-running only redoes moments whose facts, provider, model or prompt version changed (each record also names its provider and model), so it's cheap. `--force` redoes everything.
- In replay, the server adds each moment's stored commentary to the `moment` and `catchup` messages and says who wrote it in the `meta` message, so judges never hit a rate limit or a missing key. Live simulation will call the model.
- First full run (21 Oct, GPT-4o, prompt 2026-10-21.2): 52 moments across the three samples, all grounded, none fell back. Earlier runs caught and corrected made-up numbers in first drafts.
- After the Memory agent (21 Oct): the 19 moments with new memory facts were redone, 19 GPT-4o calls, all grounded first time. After the review fixes (22 Oct): 5 more moments redone, 5 calls, all grounded first time.
- The app shows the casual or analyst line under each moment's headline and on the live banner, an "AI-generated" note under the feed, and under "Why?" which agent wrote it, how many names and numbers were checked, and anything corrected.

### Code

`backend/pitch_insights/agents/`:

| Module | What it does |
|---|---|
| `settings.py` | Reads `.env` and the environment: provider, endpoint, key (never in `repr` or logs), model, timeout, retries, `max_tokens`, temperature, concurrency |
| `clients.py` | Builds the Agent Framework chat client (`OpenAIChatCompletionClient`) on the provider's OpenAI-compatible endpoint, with the timeout, the SDK's retry layer and OS certificate verification |
| `prompts.py` | Versioned system messages for the Explainer and Narrator, and the moment as the writer sees it |
| `grounding.py` | The groundedness check |
| `desk.py` | `CommentaryDesk`: routes each moment, runs the check, retries once, falls back. `AgentWriter`: the two Agent Framework agents, with structured output (`Lines`: casual, analyst) |
| `middleware.py` | Agent Framework middleware: one structured log line per agent run (agent, moment, time, tokens, error), never the prompt or reply |
| `store.py` | Reads and writes stored commentary |
| `memory.py` | The Memory agent: describes, filters, ranks and adds `memory` facts; stored vectors, the batched embeddings call, and the live embedder with its fallback |
| `safety.py` | The safety check: Azure AI Content Safety over REST, blocking level, fails closed |
| `translate.py` | Translations: names and clocks protected, the check for lost names and numbers, batching and pacing for the free tier, stored translations and the moment in a viewer's language |
| `tracing.py` | OpenTelemetry to Application Insights through Agent Framework's instrumentation, sensitive data off |

Tests (`tests/test_agents.py`, `tests/test_memory.py`, `tests/test_ai_services.py`) use a fake writer, fake embedders and faked HTTP services, so they need no key or network: grounded and made-up text, the retry naming the problems, fallbacks for 429, 500, 400, timeouts and missing structured output, settings, the cache key and the stored file; for memory, the filter, ranking, threshold, no look-ahead, the stored-vector round trip, batching and embedding failures.

### Engineering practices (Microsoft guidance)

The judging criteria ask for "quality software development practices", pointing to Microsoft Learn and the [Azure Architecture Center best practices](https://learn.microsoft.com/en-us/azure/architecture/best-practices/index-best-practices). What we follow, and where:

| Area | Practice | Status |
|---|---|---|
| Reliability | A timeout on every model call (`AGENT_TIMEOUT_S`, 20 s) and on the whole draft (45 s) | Done |
| Reliability | One retry layer only: the OpenAI SDK's (`AGENT_MAX_RETRIES`, 2), which backs off and honours `Retry-After`; it retries 429, 5xx and timeouts, never 400/401/403/404 | Done |
| Reliability | A degraded result instead of an error: every failure falls back to the plain headline | Done |
| Reliability | Limits in config, not code; failure paths tested with a fake client (429, 500, 400, timeout) | Done |
| Security | Keys only in `.env` (ignored by git) or environment variables; never logged, never in `repr`, never sent to the browser | Done |
| Security | Keyless auth with a managed identity and the "Cognitive Services OpenAI User" role; any remaining secrets in Key Vault | At deployment |
| Observability | Structured log lines per agent run and per moment, tied together by the moment ID; prompts and replies not logged | Done |
| Observability | OpenTelemetry traces from Agent Framework to Application Insights (`enable_instrumentation`, `configure_azure_monitor`), sensitive data off; our own `commentary` span per moment with agent, status, attempts, groundedness and safety | Done |
| Responsible AI | The evidence pack is the only source of facts; code groundedness check with retry and fallback; rates summarised per match | Done |
| Responsible AI | Tell users the commentary is AI-generated (the note under the feed; `ai_generated` in every stored file) | Done |
| Responsible AI | Content Safety on every line, at the strictest blocking level, failing closed | Done |
| Responsible AI | Foundry's groundedness evaluator as a second opinion on every stored line (judge model, 1–5, pass at 3) | Done |
| Responsible AI | Tell users when text is machine-translated; keep names and numbers exactly as the evidence has them, and keep English when a translation loses one | Done |
| Reliability | 429 and 5xx from the REST services retried with backoff that honours `Retry-After`; other errors not retried | Done |
| Cost | Translator requests sized and paced to stay inside the free tier's per-minute limit; Content Safety results and translations stored, so a replay calls neither | Done |
| Prompt design | System messages structured as role and task, grounding rules, safety rules, style, output format; the moment marked as data, not instructions | Done |
| Prompt design | Prompts versioned in code; the version stored with every line, so a change triggers regeneration | Done |
| Cost | `max_tokens` near the real output size (220); at most 3 calls in flight; stored commentary reused unless its inputs change | Done |
| Code quality | Structured output (a Pydantic model) instead of parsing free text; middleware for cross-cutting concerns; the model behind an interface (`Writer`) so providers and tests can swap in | Done |
| Orchestration | Deterministic code for a predictable flow (route, check, retry, fall back), not an agent deciding the order | Done |
| Orchestration | The Overlay Director is rules in code, not a model call: Microsoft's agent-orchestration guide says to use the lowest level of complexity that reliably meets the requirements (a direct call or plain code before agents), and deterministic code is predictable, testable and free of the model's rate limits | Done 23 Oct |
| Reliability | Priority Queue pattern for the cue queue: producers (the moments) set a priority, the consumer (the screen) serves the highest first; the pattern's warnings are handled: low priority can wait forever (here a cue is dropped once stale rather than shown late), and equal priorities are served oldest first, so ordering is the same every run | Done 23 Oct |
| Reliability | Load shedding and graceful degradation (Throttling pattern): shed the lowest-value work first and early, keep the essential flow unimpeded: a full queue drops its lowest priority, limits cap what is on screen, and goals and the final whistle always get through | Done 23 Oct |
| Reliability | Rate limiting by cooldowns (Rate Limiting pattern, applied to what the viewer sees): a minimum gap per template and a longer one per player, with urgent cues exempt from cooldowns but never from the limits | Done 23 Oct |
| Testing | The scheduler is a pure function of the cues and the times it is given, so tests need no clock, server or browser: limits under a flood of 300 random cues, pre-emption and its margin, cooldowns, queue order, stale drops, identical output on a rerun, and a WebSocket test that replays the end of a match and checks the screen against the rules after every message | Done 23 Oct |
| Observability | Everything that never reached the screen is recorded with its reason (`director.dropped`: stale or queue full) and `calibrate_director.py` reports shown, pre-empted and delayed cues per match and speed | Done 23 Oct |
| Personalisation | Rules in code, not a model: the Azure AI Personalizer service is retired (no new resources since 20 Sep 2023, retirement 25 Aug 2026), and its replacement needs click traffic; viewers state what they want, so deterministic rules are the lowest level of complexity that works | Done 23 Oct |
| Privacy | Send only aggregated or chosen features, never a user identifier (Personalizer data guidance: no user ID, email or phone as a feature): the profile is five choices, with no id, name or history, and the server doesn't log or keep it | Done 23 Oct |
| Privacy | Data retention and user control (Personalizer's retention and "clear data" controls): the profile lives only in the viewer's browser, "Clear my profile" deletes it, and a profile in a link is never saved | Done 23 Oct |
| Responsible AI | Don't personalise what is consequential or hide essential content (Personalizer transparency note): goals, red cards, summaries and the final whistle reach every viewer under every profile (tested at 60x under three profiles) | Done 23 Oct |
| Responsible AI | HAX G17 provide global controls (the profile picker, editable from the header, clearable), G11 make clear why the system did what it did (a star and "Your player" or "Your club" on every cue the profile boosted), G13 and G14 (no learning from behaviour: explicit choices only, so nothing shifts without the viewer choosing it) | Done 23 Oct |
| Security | Untrusted input validated at the edge: every profile value is checked against the match (allow-list, length cap, type), a bad one is ignored and never raises; stored data is sanitised on the way back in | Done 23 Oct |
| Code quality | Storage behind a small interface (`ProfileStore`) so the deployment can swap localStorage for Cosmos DB; localStorage always in try/catch because it can be blocked or empty | Done 23 Oct |
| Cosmos DB (planned) | One document per anonymous viewer, partitioned by that id (the access pattern is one read and one write by id, so a point read and a well-spread key), as Microsoft's data-modelling guidance asks you to start from the access patterns | At deployment |
| Testing | Determinism as a tested property: the same profile over the same match gives an identical cue sheet; the clutter rules checked under three profiles at 1x, 20x and 60x, and the must-show events under three profiles at 60x | Done 23 Oct |
| Memory (RAG) | Embed a written description of each moment (enrichment), not the raw data or the whole evidence pack | Done |
| Memory (RAG) | Filter on fields in code first (family, team, earlier only), then rank by cosine similarity, the metric recommended for Azure OpenAI embeddings | Done |
| Memory (RAG) | A similarity threshold set from test data and a small top-k; nothing returned when nothing is similar (vector search alone always returns k) | Done |
| Memory (RAG) | Same model for stored and query vectors; model, deployment and dimensions stored with the vectors; regenerate when any of them changes, checked even when the cache is complete (a file from before the deployment was stored is verified once, not assumed: one of its texts is embedded with the configured deployment and compared with the stored vector, and only a match, the same model and the same vector within rounding, lets the file be stamped; the three samples were verified and stamped on 22 Oct) | Done |
| Memory (RAG) | `dimensions` 256 instead of 1,536 to keep files small; vectors normalised in code | Done |
| Memory (RAG) | Batch inputs (at most 2,048 a request and 300,000 tokens, or the request fails with 400); one request per match | Done |
| Memory (RAG) | The SDK's retries only (backoff, honours `retry-after-ms`); on failure, no memory facts and a pause, never a blocked match | Done |
| Memory (RAG) | Evaluate retrieval with labelled pairs, including queries that should return nothing; later, Foundry's Document Retrieval evaluator over a labelled set | Partly: pairs checked by hand on the samples; tests for no-match queries |
| Memory (RAG) | Check the model's retirement: `text-embedding-3-small` retires 9 Feb 2028, after judging | Checked |
| Video (evaluation) | Score against a trusted ground truth (SoccerTrack's annotations) with several metrics, not one: recall, precision, position error (mean, median, 90th percentile), team accuracy, tracks per player, and event recall at two time windows | Done |
| Video (evaluation) | Keep fitting data and test data apart: the image-to-pitch mapping is fitted only on frames before the clip, and its degree is chosen on held-out calibration frames; the clip is used only for scoring | Done |
| Video (evaluation) | Training, validation and test data kept separate and non-overlapping: time stretches with 8-second gaps, the checkpoint chosen on validation only, the test frames used once, and the benchmark clip never trained on; training labels from a curated source (SoccerTrack's MOT boxes), not from the model's own output, which would only repeat its mistakes | Done 22 Oct: see Fine-tuning |
| Video (testing) | Unit tests for every deterministic part (loader, coordinate conversion, tile merging, tracker, spectator filter, events, scoring, frame message), on hand-made snippets with no video, model or network | Done |
| Video (MLOps) | Track each benchmark run in the Azure ML workspace with MLflow (parameters, metrics, the benchmark and calibration files as artifacts); `mlflow-skinny` for logging only; sign-in through azure-identity, no keys in code; the tracking URI from `.env` | Done 22 Oct: run `117093-38min-rfdetr-small-pretrained` in experiment `video-path-benchmark` of `ML-pitch-insights` (15 metrics, 10 parameters, 2 files), by `video/log_mlflow.py`. The subscription isn't in the account's home tenant, so the script looks up the subscription's tenant first; without that, every call returned 400 Bad Request |
| Video (Responsible AI) | People are found as bodies with pseudonymous track IDs ("L-t12"); no faces, no identification; consented, licensed footage; real players labelled by side and number only | Done |
| Video (Responsible AI) | A confidence on every detected player, ball and event, and the limits stated next to the numbers (5 fps, no shots, ball not scored, referees missing from the ground truth) | Done |
| Video (cost) | CPU only, clips processed ahead of time and resumably; no GPU quota needed for the pre-trained model | Done |
| Video (Responsible AI) | HAX G1 and G2 (make clear what the system can do, and how well): a credibility panel beside the clip says the positions are measured from real video by a model, and shows precision, recall, position error and team accuracy, the model and its fine-tuning, and the credit. The figures are read from the benchmark file the video path wrote, never typed into the app, so they can't drift from the evidence | Done 23 Oct |
| Video (Responsible AI) | The Responsible AI Standard v2 asks for performance metrics, error types and the limits of what the output represents: the panel's "What these numbers don't cover" says it is one 100-second clip scored against labels with no referees or ball, that the model saw four minutes of the same half, that numbers are tracker IDs and not shirt numbers, and that the ball is found in 45% of frames and shots aren't detected. A "Real footage" tag marks the clip wherever it is shown | Done 23 Oct |
| Video (Responsible AI) | HAX G11 (why the system did what it did): a tap on a marker gives its label, speed and the model's confidence; each detected event carries "Detected from the video · confidence 64%"; markers with no team are grey, a lost ball is dimmed and then dropped, not guessed | Done 23 Oct |
| Video (Responsible AI) | No AI commentary on the clip (nothing there to ground a model against, and no new model calls): the wording of events comes from fixed templates, with the detector's own precision and recall (79% and 30% within 5 s) printed under the feed; the wording is translated by us, not by Azure Translator, and the app says so when the language isn't English | Done 23 Oct |
| Video (Reliability) | Cache-Aside: the clip's three files are parsed and validated once per process and kept in memory, keyed by path and modification time so a changed file is read again; every replay then starts without reading disk | Done 23 Oct |
| Video (Security) | Untrusted input at the edge: the clip name must match an allow-list pattern and its files resolve inside `samples/video/` (no path traversal); every frame is checked against the `Frame` model on load and a bad file is refused with the reason, never half-served; `at`, `from`, `speed` and `lang` that are missing, malformed or out of range fall back to defaults | Done 23 Oct |
| Video (Reliability) | Load shedding on the stream (Throttling pattern): a frame already more than 1.5 frame intervals late is skipped, never queued, so a fast replay or a slow browser drops stale positions instead of falling behind; the app draws between the last two frames it has, so motion stays smooth at 0.5x to 5x | Done 23 Oct |
| Video (Cost) | The backend image needs no torch, opencv or rfdetr: the clip is stored output (a 0.9 MB frames file, a small events file and the benchmark), read from `samples/video/` (`PITCH_SAMPLES` moves it), so Container Apps serves it on the same small image | Done 23 Oct |
| Video (Testing) | The loader, validation failures, labels, event wording in six languages, cues, credibility figures and the whole WebSocket stream (every frame in order, seek with catch-up, bad query values, language, casual and analyst cues, pause and disconnect) are tested on the real sample files with no video or network; the motion's smoothness was measured in the browser by replaying real frame arrival times through the layer at four speeds (no stalls, no jumps over 0.5 m between draws at 1x) | Done 23 Oct |

Sources: [Personalizer data and privacy](https://learn.microsoft.com/en-us/azure/ai-services/personalizer/responsible-data-and-privacy), [Personalizer transparency note](https://learn.microsoft.com/en-us/azure/ai-services/personalizer/responsible-use-cases), [HAX Toolkit design library](https://www.microsoft.com/en-us/haxtoolkit/library/), [Cosmos DB: model and partition data from the access patterns](https://learn.microsoft.com/en-us/azure/cosmos-db/nosql/model-partition-example), [AI agent orchestration patterns (lowest level of complexity)](https://learn.microsoft.com/azure/architecture/ai-ml/guide/ai-agent-design-patterns), [Priority Queue pattern](https://learn.microsoft.com/azure/architecture/patterns/priority-queue), [Throttling pattern (shed load early, lowest-value work first)](https://learn.microsoft.com/azure/architecture/patterns/throttling), [Rate Limiting pattern](https://learn.microsoft.com/azure/architecture/patterns/rate-limiting-pattern), [transient fault handling](https://learn.microsoft.com/en-us/azure/architecture/best-practices/transient-faults), [Azure OpenAI quotas and limits](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/quota), [keyless connections](https://learn.microsoft.com/en-us/azure/developer/ai/keyless-connections), [Agent Framework observability](https://learn.microsoft.com/en-us/agent-framework/agents/observability), [monitoring and diagnostics](https://learn.microsoft.com/en-us/azure/architecture/best-practices/monitoring), [system messages](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/concepts/system-message), [safety system messages](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/concepts/safety-system-message-templates), [transparency note](https://learn.microsoft.com/en-us/azure/ai-foundry/responsible-ai/openai/transparency-note), [RAG evaluators](https://learn.microsoft.com/en-us/azure/ai-foundry/concepts/evaluation-evaluators/rag-evaluators), [structured outputs](https://learn.microsoft.com/en-us/agent-framework/agents/structured-outputs), [middleware](https://learn.microsoft.com/en-us/agent-framework/agents/middleware/), [Well-Architected AI application design](https://learn.microsoft.com/en-us/azure/well-architected/ai/application-design), [API design](https://learn.microsoft.com/en-us/azure/architecture/best-practices/api-design), [embeddings how-to](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/embeddings), [embeddings REST reference (`dimensions`)](https://learn.microsoft.com/en-us/rest/api/microsoft-foundry/azureopenai/embeddings), [quotas and limits](https://learn.microsoft.com/en-us/azure/foundry/openai/quotas-limits), [model retirement schedule](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule), [RAG design and evaluation guide](https://learn.microsoft.com/azure/architecture/ai-ml/guide/rag/rag-solution-design-and-evaluation-guide), [RAG enrichment](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/rag/rag-enrichment-phase), [RAG retrieval and its evaluation](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/rag/rag-information-retrieval), [vector search (keep embeddings current)](https://learn.microsoft.com/en-us/azure/architecture/guide/technology-choices/vector-search), [Foundry RAG evaluators](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/rag-evaluators), [Content Safety Analyze Text](https://learn.microsoft.com/en-us/rest/api/contentsafety/text-operations/analyze-text?view=rest-contentsafety-2024-09-01), [Content Safety harm categories](https://learn.microsoft.com/en-us/azure/ai-services/content-safety/concepts/harm-categories), [Translator: prevent translation](https://learn.microsoft.com/en-us/azure/ai-services/translator/text-translation/how-to/prevent-translation), [Translator service limits](https://learn.microsoft.com/en-us/azure/ai-services/translator/service-limits), [evaluation SDK](https://learn.microsoft.com/azure/ai-studio/how-to/develop/evaluate-sdk), [Agent Framework context providers](https://learn.microsoft.com/en-us/agent-framework/concepts/agents/conversations/context-providers), [Agent Framework vector stores](https://learn.microsoft.com/en-us/agent-framework/integrations/by-component/vector-stores/), [Well-Architected: test and evaluate AI workloads](https://learn.microsoft.com/en-us/azure/well-architected/ai/test), [configure MLflow for Azure Machine Learning](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-use-mlflow-configure-tracking), [query and compare runs with MLflow](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-track-experiments-mlflow), [Content Understanding video limits](https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/video/overview), [Microsoft Responsible AI principles](https://www.microsoft.com/ai/principles-and-approach), [HAX Toolkit guidelines G1, G2 and G11](https://www.microsoft.com/en-us/haxtoolkit/library/), [Microsoft Responsible AI Standard v2, general requirements (documentation, metrics, limitations)](https://blogs.microsoft.com/wp-content/uploads/prod/sites/5/2022/06/Microsoft-Responsible-AI-Standard-v2-General-Requirements-3.pdf), [Cache-Aside pattern](https://learn.microsoft.com/azure/architecture/patterns/cache-aside).

### Tracing

Code in `backend/pitch_insights/agents/tracing.py`. When `APPLICATIONINSIGHTS_CONNECTION_STRING` is set, `setup_tracing` connects OpenTelemetry to Application Insights (`configure_azure_monitor`) and turns on Agent Framework's instrumentation (`enable_instrumentation`) with sensitive data off, so agent runs, model calls and token counts are traced but prompts and replies aren't. The desk adds a `commentary` span per moment with the agent, status, attempts, reason, groundedness score and whether the safety check passed. `generate_commentary.py` turns it on and flushes before it exits; traces show in the Foundry project's Tracing page and in Application Insights. Checked 22 Oct: a two-moment run's spans were accepted by the ingestion endpoint. The exporter uses the operating system's certificate store (`truststore`), like every other client here.

### Foundry groundedness evaluator

`scripts/evaluate_groundedness.py` asks Foundry's `GroundednessEvaluator` (azure-ai-evaluation, with the GPT-4o deployment as judge) whether each stored line is supported by the facts the writer was shown, on a 1–5 scale (3 or more passes). It's a second opinion on what our code check can't see, such as a claim with no name or number. Results go in `samples/<name>.evaluation.json`, with the judge's reason for each score; only changed lines are sent again.

- **First run (22 Oct):** all 52 stored lines passed. Mean score 4.45 (comeback), 4.79 (thriller), 4.78 (red card); the lowest score was 4. 52 GPT-4o judge calls.
- It runs over the stored commentary only, not live: a judge call per line would double the model cost of live mode.

### Azure resources

All in `rg-pitch-insights`, East US 2:

- Foundry resource and project, with the `gpt-4o` and `text-embedding-3-small` deployments (done)
- Content Safety, Translator and Speech, each on the free F0 tier (Speech optional; first to cut)
- Application Insights, connected to the Foundry project for tracing
- At deployment: Container Apps (backend), Static Web Apps (app), Key Vault for the keys (read by the backend through a managed identity), and Cosmos DB on its free tier for viewer profiles and stored commentary

During development keys live in `.env` (ignored by git; `.env.example` holds placeholders only). They never reach the browser.

### Not used, and why

- **Foundry Agent Service:** possible now, but Agent Framework running in our own backend already gives us the handoffs, shared state and failure handling the Multi-Agent prize judges, with less to deploy.
- **AI Gateway (API Management):** it caps token use per project but doesn't add quota, and it costs money; the budget alert and low rate limits do the same job here.
- **Fine-tuning:** not needed for commentary from evidence packs.
- **Azure AI Content Understanding (video) for the video path:** it samples about one frame a second at 512 × 512 px, so distant players and quick touches are lost; player tracking needs a detector on tiles of every sampled frame. (Azure AI Vision's Spatial Analysis, which tracked people, was retired in March 2025.)

### Rules this supports

- Microsoft Foundry is the first "hero technology" under Technological Implementation (20% of every score). Agent Framework and "Azure Apps and AI Services" are on the same list.
- The Multi-Agent prize accepts Agent Framework with any model provider; only the Foundry prize needs Foundry itself. A project can win one grand prize and up to one category prize (rule 8.2).

## Video path

Designed 21 Oct 2026, built 22 Oct on branch `video-path`. Turns real, licensed match video into the same messages as the synthetic generator: `frame` messages with player positions, and `event` messages with `source: "video"` and a `confidence` below 1. Keep-or-cut decision on 24 Oct.

### Source: SoccerTrack v2

- [SoccerTrack v2](https://atomscott.github.io/SoccerTrack-v2/) (Scott et al., [arXiv:2508.01802](https://arxiv.org/abs/2508.01802)): 10 full amateur university matches, 4K panoramic video from a fixed camera covering the whole pitch, 25 fps.
- License: CC BY 4.0 for video and annotations (MIT for their code). Players gave informed consent, collection had ethics approval, and there are no names, only shirt numbers. Credit in the README and the demo video.
- Hosted on Hugging Face (`atomscott/soccertrack-v2`), gated: downloads need a Hugging Face read token (`HF_TOKEN` in `.env`) from an account that has accepted the terms.
- Downloaded (21 Oct): match `117093`, first half, into the git-ignored `data/soccertrack/117093/`: video (3.35 GB; 4096 × 1080, 25 fps, 67,625 frames, 45:05), GSR tracking (2.71 GB, every frame) and BAS events (0.5 MB, both halves).
- In anything shown, label these players by team side and shirt number ("Left #7"), never with our fictional names. Our own tracks are labelled by team and track ID ("L-t12"), since video can't read shirt numbers.

### Their annotations, as shipped (checked 22 Oct)

- **GSR (tracking ground truth):** COCO-style: `info`, `images` (67,625, with the real 4096 × 1080 size for this match), `annotations`, `categories`. Annotations are grouped by frame in order; `images` comes first and maps each `image_id` to a frame through its `file_name` (`000123.jpg`, 1-based).
  - People: fields under `attributes` (`role`, `jersey` as a string, `team` as `left`/`right`, `player_id`), the pitch position in `bbox_pitch.x_bottom_middle` / `y_bottom_middle`.
  - Positions sit on a grid of 1% of the pitch (1.05 m × 0.68 m), so they carry up to about 0.6 m of rounding.
  - `bbox_image` boxes are approximate: every box is exactly 43 px tall and they sit 10–40 px off the players. We use the pitch positions as the truth and never the image boxes.
  - The frames we read (the clip, and one every 5 s before it) have 22 people each: 20 players and 2 goalkeepers. **No referees and no ball.**
  - The GSR file has no camera calibration: each frame has a `pitch` annotation with line end points, which we don't use. (Calibration is in `raw/`, below.)
- **Other files in the dataset** (found 22 Oct while preparing fine-tuning; the first four are the small files downloaded into `data/soccertrack/117093/hf/`):
  - **`mot/117093.txt` (6.2 MB): tight boxes.** The curated subset of the MMSports 2025 challenge: 22 boxes a frame (players and goalkeepers; no referees, no ball) for the **first four minutes of the half**, MOT frame *k* (0-based) being video frame *k* + 1 (found by matching feet positions against the GSR frames). Their heights follow the image row as our own detector's do (43.9 against 44.5 px, 72.8 against 72.8 px), so, unlike the GSR image boxes, they are usable as detector labels. A paired 305 MB clip exists; we don't need it, because the frames are in the half's video.
  - **`ball/117093_1st_ball.npz` (0.13 MB): a ball track, but a reconstruction.** One row per frame, anchored at the annotated events and interpolated in straight constant-speed lines between them, per the dataset's README. It carries event timing, not the ball's real path, so it can't score per-frame ball tracking (only, roughly, the ball's position at event frames; not done).
  - **`raw/117093/`: SoccerTrack's own calibration.** 65 hand-annotated pitch keypoints, camera intrinsics, distortion maps (`mapx`, `mapy`) and a homography. We downloaded the homography, intrinsics, keypoints and padding file, not the 26 MB maps or the 216 MB tracker boxes. Our fitted polynomial (0.76 m on held-out frames) doesn't use them; undistorting with the intrinsics and applying the homography might fit better, and is untried.
  - `README.md` and `CHANGES_v1_*.md`: the dataset's own notes (frame and time conventions: game-state frame *k* is video frame *k*).
- **BAS (event ground truth):** 12 classes; `position` is in ms. This file's header says it counts from the half's own video, not from kickoff, so the loader only corrects second-half times when they are clearly match time. **A goal here is a lone `GOAL`, not `SHOT` plus `GOAL`.** No penalty class.
- `left`/`right` is the side in that half; the left team attacks +x. Sides swap at half-time, so the same team has a different label in each half.
- We don't use their loader (`src.data_utils.soccertrack_v2`): ours streams the file (about 25 s to the clip, never more than one annotation in memory) and needs no extra packages.

### Coordinates

- SoccerTrack: metres, origin at the centre spot, x from −52.5 to +52.5 (towards the right goal), y from −34 to +34 (towards the camera).
- Ours: 0–105 × 0–68 from the acting team's attacking direction.
- The left team attacks towards +x: `x = x_st + 52.5`, `y = y_st + 34`. The right team: `x = 52.5 − x_st`, `y = 34 − y_st`. This is the same 180° flip the generator uses, so both sources line up. Code: `pitch_insights/video/soccertrack.py` (`to_our_frame`, `from_our_frame`).

### Frame message (schema 1.1, as built)

```json
{"type": "frame", "schema": "1.1", "match_id": "ST-117093", "source": "video",
 "period": 1, "t": 2280.0, "clock": "39'", "ref_team_id": "L",
 "players": [{"id": "L-t12", "team_id": "L", "x": 61.2, "y": 30.4, "speed": 5.8, "confidence": 0.91}],
 "ball": {"x": 63.0, "y": 31.1, "confidence": 0.42}}
```

- The Pydantic model is `Frame` in `events/schema.py`, exported to `docs/schema/frame.schema.json`.
- Players' positions are in their own team's attacking frame. `ref_team_id` (added while building) names the team whose frame the ball and teamless people (referees, unclassified tracks: `team_id` null) use.
- `ball` is null when not detected; `speed` is null when a track is too short to measure, or over 12 m/s (a tracking glitch). Speed is smoothed over about 0.5 s.
- Positions just off the pitch (a throw-in taker) are clamped to its edge.
- Built at **5 frames a second**, not the planned 10: detection costs about 8 s a frame on CPU. The synthetic generator will produce the same message in v2.

### Pipeline as built

| Step | Code | What it does |
|---|---|---|
| 1. Ground truth | `video/extract_gsr.py` | Streams the 2.7 GB GSR once (about 25 s): the clip's truth at 5 fps, and calibration pairs from frames **before** the clip only |
| 2. Detect | `video/detect.py`, `video/detector.py` | RF-DETR small (COCO weights as released), the pitch band (rows 90–790) cut into 5 × 2 tiles with 96 px overlap, merged across tiles (`video/tiles.py` in the backend package); people and footballs kept; a shirt colour per person. Resumable |
| 3. Calibrate | `video/calibrate.py`, `video/calibration.py` | Fits image pixels to pitch metres (below) |
| 4. Track, teams, ball, messages, benchmark | `video/process.py` | Seconds; re-run freely |
| 5. Preview | `video/preview.py` | Draws our tracks and the ground truth on the clip (`data/video/117093/preview.mp4`, git-ignored) |

The pure-Python parts (loader, tile merging, tracker, events, scoring) live in `backend/pitch_insights/video/` and are covered by `backend/tests/test_video.py`; the backend gains no new dependencies. The detector runs in its own environment, `video\.venv` (torch, rfdetr 1.11.2, opencv, supervision, truststore): torch CPU on the organisation laptop, AMD's ROCm build on Austin's GPU machine.

**Tiles.** The whole frame at the model's 512 px input finds only 7 people. On the first clip frame: 4 × 2 tiles over the whole frame found 42 people in 6.4 s; 5 × 2 over the pitch band found 54 in 7.1 s; 6 × 2 found 57 in 8.2 s. 5 × 2 was chosen. A player cut off at a tile's edge is merged with the whole one by how much of the smaller box lies inside the other, not only by IoU; containment is checked first, because a crop that is exactly half of the whole box has an IoU of exactly the duplicate threshold and used to be kept alone, with the feet cut off (found in review, 22 Oct).

**Pitch positions.** SoccerTrack ships no calibration, and one homography can't describe a stitched panorama (4.2 m mean error). A 2-D polynomial of degree 5 does. It is fitted from **our detected feet** (the bottom middle of the RF-DETR box) to the GSR positions, on 76 frames before the clip (one every 30 s, 1,283 pairs). Fitting on SoccerTrack's own image boxes would have built their 10–40 px offset into every position. Degree chosen on held-out frames: 3 → 1.57 m, 4 → 0.97 m, **5 → 0.76 m** mean error. The fit is stored in `samples/video/117093-38min.calibration.json`. A detection counts as on the pitch only if it lies inside the pitch outline (plus 2 m) in the image *and* maps inside it, so the polynomial can't fold the stands back onto the pitch.

**Spectators.** The stand behind the far touchline is raised, so from this camera spectators' feet land on the far touchline and map onto the pitch; on the first 14 frames they were about 220 of 255 false detections. Filtering whole tracks didn't hold up over the full clip (a spectator's track hops to the next person on the stand), so detections are filtered *before* tracking: in the strip within 10 m of the far touchline, or just behind a goal line, a 2 m grid cell occupied in at least 15% of frames *and* in at least 3 of 5 equal parts of the clip is a static spot, and detections there are dropped (`static_spots` in `track.py`). Two grids offset by half a cell catch someone standing on a cell edge; the time spread keeps a player who holds one spot for a while; a keeper standing still on the pitch isn't in those zones. The same test over the whole pitch, without the time spread, removes the spare balls lying around it. It needs the whole clip, so it is an offline filter; a live version would need some seconds of history.

**Tracking.** supervision 0.31 no longer includes ByteTrack (it moved to Roboflow's separate `trackers` package). Rather than add a package, `video/track.py` follows ByteTrack's idea in pitch metres: confident detections (0.5 or more) match tracks first, then leftover tracks get a second chance with the low-confidence ones (0.3–0.5), which are often half-hidden players. Matching is closest pairs first, by distance after a constant-velocity prediction, within a 6 m gate that widens while a track is missing; tracks end after 5 s unseen. A 2.5 m gate with 2 s patience kept a player's ID for 69% of their frames; 6 m and 5 s, 80% (tuned on the first half of this clip). At 5 fps a running player can move a whole box width per frame, so box overlap would match poorly.

**Teams.** Each detection's shirt colour is the mean Lab colour of the upper body, grass masked out; each track's colour is the mean over its detections, and k-means puts the tracks in 4 groups. The two groups with the most detections are the teams; the others (keepers, officials, odd crops) get no team. With 3 groups the referee's dark shirt joined Left's blue. Per detection, Left's blue and Right's white separate only about 89% of the time even with the best possible grouping (far players are a few pixels wide and shadows change the lightness), and a track that hops between players mixes colours, so team accuracy is about 89%. The team with the lower mean x over the clip is Left, since a team defending the left goal sits deeper on average. SoccerTrack's labels are used only to score this.

**Ball.** RF-DETR's "sports ball" class, score 0.2 or more, on the pitch. Each frame takes the candidate nearest the previous ball (within 3 m plus 30 m/s), else a confident one (0.4 or more). No ground truth, so not scored directly.

**Events** (`pitch_insights/video/events.py`): the nearest player with a team within 2.5 m of the ball has it, over at least 2 frames (2 m found too few owners on this clip, 3 m is loose; one frame doubled the events but cut their precision from 63% to 36% on the first 60 s). Same team, different player next: `pass` (complete). Opponent next: `interception` (and the passer's `pass` incomplete) if the ball travelled 3 m or more, otherwise `tackle`. A player who moves 3 m or more with the ball: `carry`. Shots aren't attempted: at 5 fps the ball is often missed in flight, and the outcome can't be seen from the ball alone. Fields video can't see take neutral values (`height` ground, `kind` open_play, `difficulty` 0.5). Confidence is 0.9 × the mean ball-detection score around the event.

### Clip

Match 117093, first half, **38:00.0 to 39:40.0** (100 s, frames 57,001–59,500, 500 frames at 5 fps). Chosen from the BAS events: Left's attack that ends in their second goal (39:35), with three crosses, a free kick, a shot, three outs and a throw-in on the way. Defined in `video/clip.py`.

### Benchmark (refreshed 22 Oct on a GPU, after the tile-merge fix)

RF-DETR small on 500 frames (100 s at 5 fps), on Austin's GPU machine (AMD Radeon RX 9070 XT). **Pre-trained** is the COCO model as released; **fine-tuned** takes people from the model trained on SoccerTrack's MOT boxes (see [Fine-tuning](#fine-tuning-run-22-oct-on-austins-gpu-machine)) and the ball from the COCO one. Ground truth: 22 people a frame (11,000 in all); the GSR file has no referees or ball.

| Measure | Pre-trained | Fine-tuned |
|---|---|---|
| Players found (recall, within 3 m) | **90%** (9,941 of 11,000) | **93%** (10,245) |
| Precision (our people that are a real player) | **85%** (11,734 output); the rest are the referee and assistant referees (not in the ground truth), people behind the right goal, and spectators the filter missed by the far-left corner | **97%** (10,588 output) |
| People we gave a team | 97% precision, 69% recall (keepers and officials get no team) | 99% precision, 66% recall |
| Position error, matched players | **0.77 m mean, 0.59 m median**, 1.7 m at the 90th percentile | **0.76 m mean, 0.58 m median**, 1.6 m |
| Team from shirt colour | **93%** right | **95%** right |
| Track IDs | 73 tracks for 22 players; a player keeps their most common ID for 69% of their frames | 52 tracks; 69% |
| Image-to-pitch mapping (held-out calibration frames) | 0.77 m mean, 0.58 m median | 0.76 m mean, 0.57 m median |
| Before filtering (detections on the pitch) | 91% recall, 51% precision: spectators on the far stand, removed by the static-spot filter (7,678 detections, 50 spots) | 93% recall, 96% precision: the filter finds no static spots, because the model no longer detects the spectators |
| Ball | Followed in 227 of 500 frames (45%), after removing 8 spots where spare balls lie; not scored (SoccerTrack's ball file is a reconstruction, not per-frame truth) | 226 frames (6 spots) |
| Events derived (37 BAS events in the clip, `Out` left out) | 15 (6 passes, 6 carries, 3 interceptions) | 14 (7 passes, 5 carries, 2 interceptions) |
| Event recall within ±1 s / ±5 s | 19% / **30%** (passes 30%, carries 33%, shots 0 of 2 within 5 s) | 22% / **30%** (passes 35%, carries 27%) |
| Event precision within ±1 s / ±5 s | 47% / **73%** | 57% / **79%** |
| Detection time | 0.26 s a frame (2.2 min for the clip) | 0.47 s a frame (3.9 min; two models run) |

Before the refresh (CPU, 7.7 s a frame, the old tile merge) the pre-trained figures were: found 91%, precision 85%, 0.78 m mean and 0.59 m median, team 88%, ID consistency 72% (60 tracks), team recall 83%, ball 45%, events 19 with precision 74% and recall 38% within 5 s. The raw detections hardly changed between CPU and GPU, so the differences come from the merge fix: teams improved (88% → 93%) while tracks split more (60 → 73), fewer people got a team (83% → 69%) and event recall fell (38% → 30%).

How much of this to trust:

- **Fitted apart from the test:** the image-to-pitch mapping (frames before the clip) and the fine-tuned model (the first four minutes of the half, checkpoint chosen on `valid`).
- **Chosen while looking at the clip:** the static-spot filter's settings, 4 colour groups, the tracker's 6 m gate and 5 s patience, and the 2.5 m possession radius were each picked by comparing a few settings on the first half of the clip, before the merge fix. Detection, positions and the mapping weren't tuned on it. Treat the team, ID and event figures as optimistic until they are checked on a second clip.
- Recall and position error are the solid numbers: the mapping is honest, and SoccerTrack's own positions carry up to about 0.6 m of rounding, so 0.58 m median is close to that floor.

Positions are matched to the ground truth in pitch metres (closest pairs first, within 3 m). We didn't run SoccerTrack's `gs_hota` or `bas_map` scripts (they need their repository and packages); our numbers are simpler but computed the same way for every run. Full figures in `samples/video/117093-38min.benchmark.json` and `117093-38min_ft.benchmark.json`.

### Outputs (in `samples/video/`)

- `117093-38min.frames.jsonl`: 500 `frame` messages.
- `117093-38min.events.jsonl`: the derived events (event format v1, `source: "video"`).
- `117093-38min.benchmark.json`: the benchmark.
- `117093-38min.calibration.json`: the fitted mapping.
- `117093-38min_ft.*`: the same four files with the fine-tuned detector.
- `117093-boxes.eval.json`: the box check of pre-trained against fine-tuned on the held-out test frames.

No video, weights or ground truth are committed; intermediate files are in the git-ignored `data/video/117093/`.

### Mapping SoccerTrack events to ours (for scoring)

| BAS class | Our event |
|---|---|
| Pass | `pass`, height ground |
| High Pass | `pass`, height high |
| Cross | `pass`, kind cross |
| Throw In | `pass`, kind throw_in (pairs with the preceding Out) |
| Free Kick | `pass` or `shot`, kind free_kick |
| Out | previous pass's outcome becomes `out` |
| Drive | `carry` |
| Shot | `shot` |
| Goal | the matching `shot` gets outcome `goal` |
| Header | `shot` with body part head if it goes towards goal, otherwise a headed `pass` |
| Ball Player Block | `interception` (or a blocked `shot`) |
| Player Successful Tackle | `tackle`, outcome won |

Scoring leaves out `Out` (it changes the previous pass, it isn't an action) and counts `Goal` as a `shot`. Throw-ins and free kicks are `pass`es here, as in the table.

### Fine-tuning (run 22 Oct on Austin's GPU machine)

Code in `video/finetune/` (steps for the machine in its README), with the pure logic in `backend/pitch_insights/video/mot.py` and tests. Run on 22 Oct on Austin's own machine; results below.

- **Hardware:** the README installs AMD's ROCm 7.2.1 wheels for Windows (PyTorch 2.9.1, Python 3.12, Windows 11; supported Radeon cards on AMD's compatibility matrix) as well as the CUDA build. The training summary and detector metadata record the device and the PyTorch build. The route is newer than CUDA, so the brief stops on HIP errors instead of falling back to CPU; on 22 Oct it worked (see Machine, below).
- **Labels:** the MOT boxes (above), the only tight image boxes we have. (The GSR boxes are loose, and an earlier plan to use our own detections matched to the GSR positions would only have taught the model what it already does.)
- **Data:** each chosen frame is cut into the detector's own 5 × 2 tiles (`tiles_for`), each tile saved with the boxes inside it (clipped; kept when at least half is visible). People the file doesn't box (spectators, referees, staff) are background, which is what should teach the model to ignore them. 3,328 train tiles (11,403 boxes), 400 valid (1,121) and 400 test (1,086), in RF-DETR's Roboflow layout.
- **Splits:** stretches of the four minutes with 8-second gaps: train 0:00–2:24 (every 8th frame, 450 frames), valid 2:32–3:12 (40), test 3:20–3:59 (40). The benchmark clip (38:00–39:40) is a further test and is never trained on. The checkpoint is chosen on `valid`; `test` is used once, by `eval_boxes.py`.
- **Model:** RF-DETR small from the COCO weights, the head replaced by one class (`player`), 512 px input, batch 8 × accumulation 2, learning rate 1e-4, early stopping. RF-DETR realigns its head to a checkpoint's class count on load, so the fine-tuned file loads like any other.
- **Ball:** the labels have none, so a fine-tuned model would lose it. The detector therefore runs two models: people from the fine-tuned one, the ball from the COCO one (`TiledDetector(weights=...)`).
- **Checking it:** `eval_boxes.py` scores pre-trained and fine-tuned side by side on the test frames (precision and recall at IoU 0.5 and 0.75, raw and after the pitch filter), independent of our calibration. Results are in the table below. Then `VIDEO_TAG=_ft` runs the whole pipeline on the benchmark clip into separate files (`117093-38min_ft.*`) so the two benchmarks compare directly.
- **Caveats:** one match, one camera, four minutes of labels, so this adapts the model to this pitch and does not make it general. Referees and staff count as false positives for both models in the box check, because the file doesn't box them.
- **Machine:** AMD Radeon RX 9070 XT (16 GB), not NVIDIA, so PyTorch is AMD's ROCm build for Windows (2.9.1+rocm7.2.1, Python 3.12.10); it reports the card through `torch.cuda` like a CUDA build, trains in bf16 and needed no script changes. Two quirks: Triton isn't available, so RF-DETR's box matching uses a slower fallback; and a process that has run the detector on frames **decoded from the video** hangs at exit after its work is done, and can't be killed for a while (`detect.py` and `eval_boxes.py`; training is unaffected). The output is written before the hang, so the steps were run through a wrapper that ends the process once it prints its last line. Decoding in a child process, `os._exit` and `TerminateProcess` didn't avoid it; detecting on frames loaded from `.npy` did, so it is the AMD driver with video decoding in the same process.
- **Training runs** (at most two, chosen on `valid`):

  | Run | Settings | Time | Stopped | Best epoch | `valid` EMA mAP 50–95 / 75 / 50 |
  |---|---|---|---|---|---|
  | `rfdetr-small-default` (**used**) | defaults: lr 1e-4, batch 8 × 2 | 22.8 min | after epoch 8 (early stopping) | 0 | **0.707** / 0.894 / 0.993 |
  | `rfdetr-small-lr5e-5` | lr 5e-5, otherwise the same | 14.6 min | after epoch 8 | 0 | 0.697 / 0.848 / 0.991 |

  Both peak after the first epoch and then lose score at the stricter IoUs (to about 0.66) while recall and mAP at IoU 0.5 stay above 99%: with 450 frames of four minutes' play, the model learns what it can at once, and more epochs mainly fit the boxes to those frames. The best checkpoint (`checkpoint_best_total.pth`) is 127 MB.
- **Box check** (`eval_boxes.py`, the 40 test frames, 880 true boxes, score 0.3 or more):

  | Detector | IoU | Precision, all | Precision, on pitch | Recall |
  |---|---|---|---|---|
  | Pre-trained | 0.5 | 45.0% | 71.5% | 97.4% |
  | Pre-trained | 0.75 | 41.4% | 65.8% | 89.7% |
  | **Fine-tuned** | 0.5 | **98.1%** | **98.4%** | **97.7%** |
  | Fine-tuned | 0.75 | 81.8% | 82.0% | 81.5% |

  Fine-tuning removes almost every false person (1,049 to 17 at IoU 0.5) without losing recall, as expected. At IoU 0.75 its recall is lower (89.7% → 81.5%): its boxes are a little less tight than the pre-trained ones on some players, which barely shows in position error on the clip (0.77 → 0.76 m mean).
- **Decision:** use the fine-tuned model for people (tracked-player precision on the clip 85% → 97%, recall 90% → 93%). The weights stay out of git; they are on Austin's GPU machine and have to be copied to wherever detection runs.

### Clip in the app (built 23 Oct, branch `claude/video-clip-143958`)

The fine-tuned clip (`samples/video/117093-38min_ft.*`, chosen by Austin on 23 Oct) plays in the app as a real-footage entry in the match list: "Left v Right · real footage".

- **Backend** (no new dependencies): `pitch_insights/video/replay.py` loads and validates the files (cached), builds a `match_meta`-shaped description (Left is "home", with the attacking directions above, so the app's colours, overlays and event drawing work unchanged; no squads, so no names), the credibility block, the event wording and the cues. `pitch_insights/video/serve.py` is the WebSocket handler; `server.py` hands any name that is a clip in `samples/video/` to it. `GET /api/matches` lists the clip after the synthetic matches with `kind: "video"`; only the fine-tuned run is listed (`APP_CLIPS`), the pre-trained one can still be opened by name.
- **Stream:** `meta` (with `kind: "video"` and the `clip` block), `catchup` (events before a seek), then `frame` messages exactly as in the schema above, as the replay clock reaches them (5 a second at 1x), `event` messages with their words in the viewer's language, `cue` and `cue_end` from the same Overlay Director as the synthetic matches, and `end`. `at` is seconds into the clip (`from` the same in minutes); frames keep their own `t`, so 2280 is 38:00 on the match clock. Pause, resume, speed and the casual/analyst switch behave as for a match; seek reconnects. No state, moments or commentary messages: there is no Interpreter on video events yet.
- **Speeds:** 0.5x, 1x, 2x and 5x, starting at 1x (a synthetic match keeps 1x to 60x, starting at 20x). A speed belongs to the match it was chosen in.
- **On the pitch:** each tracked person is a marker in their side's colour (Left blue, Right white, shown as they are rather than lifted like club colours; grey where the model gave no team), with the tracker number above it. A tap picks the nearest marker and shows "Left #6 · 5 km/h · 86%". The ball appears where the video found it (it is solid while detected, dimmed for 1.2 s after it is lost, then hidden). A detected pass or carry draws a line that fades over 3.5 s, an interception a ring. The territory surface rises where each side's players have been (a small amount per second at each position), so it comes from tracking here, not from events.
- **Smooth motion:** the app keeps the last dozen frames and draws the pitch one and a half frame intervals in the past, between the two frames either side of that moment, so everyone moves in a straight line from one frame to the next at any replay speed; a pause settles on the newest frame.
- **Labels:** "Left #12" is side plus tracker number (not a shirt number: video can't read them, and a player can get a new ID); a track with no team is "Track #5". Never a name. The app says so under the pitch.
- **Events and cues:** the 14 detected events (passes, carries, interceptions) become lower-thirds: interceptions, passes that fail and passes of 20 m or more are for every viewer, short passes and carries are for analysts, priority 45 to 74 from the type and the detector's confidence. They go through the Director, so the clutter rules apply (one lower-third at a time, a wait and then a drop when it gets busy). The side panel lists every detected event with how sure the model was. A goal and a shot happen in the clip (39:35) but aren't detected, so there are no urgent cues, and no speed popups: the tracker's speeds reach 11.7 m/s only because of ID switches, which makes a "top speed" claim wrong.
- **Credibility panel and strip:** the strip under the controls (every layout) and the panel in Fan layout show precision, recall, mean and median position error, team accuracy, the model and fine-tuning, the credit "SoccerTrack v2 (CC BY 4.0)" with a link, and the limits. Every figure comes from `117093-38min_ft.benchmark.json`.
- **Personalisation:** mode and language apply (casual fans get the cues made for everyone; the event wording is in six languages, written by us, with the labels and numbers the same in each). Favourite clubs and players don't exist in the clip (a profile's club is ignored by the server and the chip says "not in this match"); there is no focus strip, rating card or scoreboard.
- **Tests:** `backend/tests/test_clip.py`, 20 tests on the real sample files.
- **Not done:** the Interpreter on video events (needs a `match_meta` with squads), a score or stats panel, shots, and a second clip.

### Later

- **Fine-tuning:** done on Austin's own GPU machine (above), because Azure ML GPU quota can't be requested from this account (Austin lacks a support role on the subscription). Still to do: log the run to Azure ML with `video\log_mlflow.py` (`VIDEO_TAG=_ft`), and check the fine-tuned model on a second clip or match, since it has only seen this pitch.
- **Serving:** CPU detection in a container on Azure Container Apps; clips are processed ahead of time, so speed isn't critical.
- A `match_meta` with squads for video matches, so the Interpreter can run on video events (the clip's own `match_meta` has none); and the Interpreter on SoccerTrack's ground-truth events, as a check on real data.

### Rules

The core pipeline stays on synthetic data (rule 4.7); SoccerTrack is licensed footage for the video path only, which Austin confirmed on 21 Oct is fine.

## Later (not v1)

- v2 tracking frames by interpolating positions, with movement calibrated against SoccerTrack's real tracking. Synthetic speed and distance labelled as estimates; the video path gives measured ones.
- Offside.
- A Scenario Director agent that writes scripts from a prompt.
- Live simulation mode: the engine plays step by step and accepts changes mid-match (planned for day 4–5).
- Generator: make the high press create more high turnovers, so the pressing club's PPDA looks like a real pressing side's.
