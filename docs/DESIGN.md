# Design: event format and synthetic generator v1

Agreed 20 Oct 2026; Interpret stage added 20 Oct; video path designed, Moment Scorer and app added 21 Oct. See [PLAN.md](PLAN.md) for the overall plan.

## Event format v1

### Messages

All messages are JSON Lines (one JSON object per line).

| Message | When | Contents |
|---|---|---|
| `match_meta` | Once, at the start | Match info, teams, lineups, players, history, pitch directions |
| `event` | Every on-ball action | See event types below |
| `frame` | v2 only | Positions of all players and the ball, 10 times a second (see [Frame message](#frame-message-v2-planned)) |

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

- **Server** (`backend/pitch_insights/server.py`, FastAPI): `GET /api/matches`, `GET /api/matches/{name}`, and `WS /ws/replay/{name}?speed=20&from=0`. It streams `meta`, then `catchup` (when starting after kick-off: moments so far, state, and the last three minutes of events so the pitch redraws), then `event`, `moment` and `state` (about once a second, plus after shots and moments), then `end`. The browser can send speed, pause and resume; seeking reconnects with a new `from`. Speed is held between 0.1× and 600×. The replay and the command listener run together, so a disconnect (even while paused) ends both.
- **App** (`frontend/`, Vite + React + TypeScript + Three.js):
  - **3D pitch:** a 1 m grid whose height and colour come from each team's recent activity (fading over about two match minutes), so the seam between colours shows who controls which space. Shots rise as spikes sized by xG; goals glow. Pitch lines are a texture on the same surface, so they bend with it.
  - **Panels:** scoreboard with live win probability, a momentum chart, the key-moments feed with a "Why?" button that shows the evidence, live ratings with a player card (rating breakdown and biggest moments), and match stats.
  - **Viewer modes (first step of Personalise):** casual fans see headline moments only, without the stats panel; analysts see notable moments too (and minor ones if they ask), the stats panel, and an extra fact on the banner.
  - **Banner:** each headline moment that arrives live shows over the pitch for a few seconds (not ones restored by a catch-up).
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
8. **Personalizer**: picks what each viewer sees from their profile (casual or analyst, club, favourite player, language, focus metric).
9. **Overlay Director**: turns what's left into timed overlay cues (time, duration, priority, template, data) so the screen never clutters.
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
- **Fails closed:** a timeout (30 s for the whole check, retries included), a network error or an error status means the line isn't shown; the plain headline is (built in code from the facts, so it needs no check). An unchecked line isn't an unsafe one, so its draft is kept in the record as `pending`, and the next run of `generate_commentary.py` screens it again without calling the model; a stored line that hasn't been screened is left alone while the service is down. The free tier allows only a few requests a second, so 429s are retried with backoff that honours `Retry-After` (`clients.post_with_retry`, shared with the Translator).
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
| Memory (RAG) | Embed a written description of each moment (enrichment), not the raw data or the whole evidence pack | Done |
| Memory (RAG) | Filter on fields in code first (family, team, earlier only), then rank by cosine similarity, the metric recommended for Azure OpenAI embeddings | Done |
| Memory (RAG) | A similarity threshold set from test data and a small top-k; nothing returned when nothing is similar (vector search alone always returns k) | Done |
| Memory (RAG) | Same model for stored and query vectors; model and dimensions stored with the vectors; regenerate when either changes | Done |
| Memory (RAG) | `dimensions` 256 instead of 1,536 to keep files small; vectors normalised in code | Done |
| Memory (RAG) | Batch inputs (at most 2,048 a request and 300,000 tokens, or the request fails with 400); one request per match | Done |
| Memory (RAG) | The SDK's retries only (backoff, honours `retry-after-ms`); on failure, no memory facts and a pause, never a blocked match | Done |
| Memory (RAG) | Evaluate retrieval with labelled pairs, including queries that should return nothing; later, Foundry's Document Retrieval evaluator over a labelled set | Partly: pairs checked by hand on the samples; tests for no-match queries |
| Memory (RAG) | Check the model's retirement: `text-embedding-3-small` retires 9 Feb 2028, after judging | Checked |

Sources: [transient fault handling](https://learn.microsoft.com/en-us/azure/architecture/best-practices/transient-faults), [Azure OpenAI quotas and limits](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/quota), [keyless connections](https://learn.microsoft.com/en-us/azure/developer/ai/keyless-connections), [Agent Framework observability](https://learn.microsoft.com/en-us/agent-framework/agents/observability), [monitoring and diagnostics](https://learn.microsoft.com/en-us/azure/architecture/best-practices/monitoring), [system messages](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/concepts/system-message), [safety system messages](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/concepts/safety-system-message-templates), [transparency note](https://learn.microsoft.com/en-us/azure/ai-foundry/responsible-ai/openai/transparency-note), [RAG evaluators](https://learn.microsoft.com/en-us/azure/ai-foundry/concepts/evaluation-evaluators/rag-evaluators), [structured outputs](https://learn.microsoft.com/en-us/agent-framework/agents/structured-outputs), [middleware](https://learn.microsoft.com/en-us/agent-framework/agents/middleware/), [Well-Architected AI application design](https://learn.microsoft.com/en-us/azure/well-architected/ai/application-design), [API design](https://learn.microsoft.com/en-us/azure/architecture/best-practices/api-design), [embeddings how-to](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/embeddings), [embeddings REST reference (`dimensions`)](https://learn.microsoft.com/en-us/rest/api/microsoft-foundry/azureopenai/embeddings), [quotas and limits](https://learn.microsoft.com/en-us/azure/foundry/openai/quotas-limits), [model retirement schedule](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule), [RAG design and evaluation guide](https://learn.microsoft.com/azure/architecture/ai-ml/guide/rag/rag-solution-design-and-evaluation-guide), [RAG enrichment](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/rag/rag-enrichment-phase), [RAG retrieval and its evaluation](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/rag/rag-information-retrieval), [vector search (keep embeddings current)](https://learn.microsoft.com/en-us/azure/architecture/guide/technology-choices/vector-search), [Foundry RAG evaluators](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/rag-evaluators), [Content Safety Analyze Text](https://learn.microsoft.com/en-us/rest/api/contentsafety/text-operations/analyze-text?view=rest-contentsafety-2024-09-01), [Content Safety harm categories](https://learn.microsoft.com/en-us/azure/ai-services/content-safety/concepts/harm-categories), [Translator: prevent translation](https://learn.microsoft.com/en-us/azure/ai-services/translator/text-translation/how-to/prevent-translation), [Translator service limits](https://learn.microsoft.com/en-us/azure/ai-services/translator/service-limits), [evaluation SDK](https://learn.microsoft.com/azure/ai-studio/how-to/develop/evaluate-sdk), [Agent Framework context providers](https://learn.microsoft.com/en-us/agent-framework/concepts/agents/conversations/context-providers), [Agent Framework vector stores](https://learn.microsoft.com/en-us/agent-framework/integrations/by-component/vector-stores/).

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

### Rules this supports

- Microsoft Foundry is the first "hero technology" under Technological Implementation (20% of every score). Agent Framework and "Azure Apps and AI Services" are on the same list.
- The Multi-Agent prize accepts Agent Framework with any model provider; only the Foundry prize needs Foundry itself. A project can win one grand prize and up to one category prize (rule 8.2).

## Video path (planned)

Designed 21 Oct 2026. Turns real match video into the same messages as the synthetic generator: `frame` messages with player positions, and `event` messages with `source: "video"` and a `confidence` below 1.

### Source: SoccerTrack v2

- [SoccerTrack v2](https://atomscott.github.io/SoccerTrack-v2/) (Scott et al., [arXiv:2508.01802](https://arxiv.org/abs/2508.01802)): 10 full amateur university matches, 4K panoramic video from a fixed camera covering the whole pitch, 25 fps.
- License: CC BY 4.0 for video and annotations (MIT for their code). Players gave informed consent, collection had ethics approval, and there are no names, only shirt numbers. Credit in the README and the demo video.
- Hosted on Hugging Face (`atomscott/soccertrack-v2`), gated: downloads need a Hugging Face read token (`HF_TOKEN` in `.env`) from an account that has accepted the terms.
- Downloaded (21 Oct): match `117093`, first half, into the git-ignored `data/soccertrack/117093/`: video (3.35 GB), GSR tracking (2.71 GB; much larger than the video's annotations suggest, because it holds every frame) and BAS events (0.5 MB).
- In the demo, label these players by team side and shirt number ("Left #7"), never with our fictional names.

### Their annotations, and what to watch for

- **GSR (tracking ground truth):** per frame, each player's, goalkeeper's and referee's pitch position in metres, track ID, role, team side and shirt number. **The ball is not included.**
- **BAS (event ground truth):** 12 timestamped classes. A shot that scores is two annotations (`Shot` and `Goal`) at the same time. There is no penalty class.
- **Format traps (from their own docs):**
  - The shipped GSR files don't match the written spec. They are COCO-style objects (`images`, `annotations`, ...). Fields sit under `attributes`, shirt numbers are strings, and the position is `bbox_pitch.x_bottom_middle` / `y_bottom_middle`.
  - The declared image size (3840 × 1504) is wrong for nine of the ten matches. Use real pixel sizes from the video.
  - BAS `position` for second-half events counts from the start of the match, not the half. Subtract the first half's length (or use their loader's `t_ms_in_half`).
  - Team `left`/`right` is fixed per half and can swap between halves for the same team.
- Their loader (`src.data_utils.soccertrack_v2`) already handles some of this. Use it where possible, and check the result against a few frames by eye.

### Coordinates

- SoccerTrack: metres, origin at the centre spot, x from −52.5 to +52.5 (towards the right goal), y from −34 to +34.
- Ours: 0–105 × 0–68 from the acting team's attacking direction.
- The team on the left side at kickoff attacks towards +x in that half: `x = x_st + 52.5`, `y = y_st + 34`. The other team: `x = 52.5 − x_st`, `y = 34 − y_st`. This is the same 180° flip the generator uses, so both sources line up.

### Frame message (v2, planned)

```json
{"type": "frame", "schema": "1.1", "match_id": "ST-117093", "source": "video",
 "period": 1, "t": 12.48, "clock": "1'",
 "players": [{"id": "L-07", "team_id": "L", "x": 61.2, "y": 30.4, "speed": 5.8, "confidence": 0.91}],
 "ball": {"x": 63.0, "y": 31.1, "confidence": 0.42}}
```

- Positions in our attacking-team frame for each player's own team. `ball` is null when not detected.
- 10 frames a second for the stream (sampled from 25 fps). Speed is smoothed over about 0.5 s.
- The synthetic generator will produce the same message in v2, by interpolating its event positions and calibrating movement against SoccerTrack's real tracking.

### Detector

- **Chosen (21 Oct), needs no GPU quota:** RF-DETR (small) as released, already trained to find people and footballs, run on a short clip (one to two minutes, a few frames a second, each 4K frame cut into overlapping tiles). Scored against the GSR ground truth.
- **Main, if T4 GPU quota arrives in Azure ML:** RF-DETR (small), Apache-2.0, fine-tuned on SoccerTrack's player boxes. **Fallback:** YOLO (Ultralytics, AGPL-3.0). If time allows, fine-tune both on the same frames and compare.
- Classes: player, goalkeeper, referee, ball. The ball has no GSR ground truth, so its detection is a bonus, not a dependency.
- Panoramic view: players are small, so train and detect at 1280–1920 px, or on overlapping tiles.
- Before training, check current versions, licenses and GPU memory against the actual GPU.

### Training

- **Data:** a script turns SoccerTrack's image boxes into the detector's training format. Sample frames spaced out in time (not every frame), and split by time so test frames never sit next to training frames.
- **Where:** an Azure ML compute cluster in workspace `ML-pitch-insights` (East US 2) once T4 quota (family NCASv3_T4, low priority if offered) is granted on the Pay-As-You-Go subscription, or Austin's GPU machine.
- **Azure:** the run logs metrics and the final model to an Azure ML workspace through MLflow, which needs no compute quota. The model is registered in Azure ML.
- **Serving:** CPU detection in a container on Azure Container Apps. Clips are processed ahead of time, so speed is not critical.

### From detections to messages

1. **Detect** players (and, when possible, the ball) in each frame.
2. **Track** with ByteTrack for stable IDs.
3. **Team:** shirt-colour clustering. SoccerTrack's team labels are used only to score this, not as input.
4. **Pitch position:** from SoccerTrack's calibration maps (fixed camera), so speed and distance are measured, not estimated.
5. **Frames:** write `frame` messages.
6. **Events** (when the ball is tracked well enough): the nearest player within about 1.5 m has possession. A change of possession between teammates is a `pass`, a run with the ball is a `carry`, a change to an opponent is a turnover (`interception` or `tackle`), and fast ball movement towards goal is a `shot`. Each gets a `confidence`.

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

This conversion also lets the Interpreter run directly on SoccerTrack's ground-truth events, as a check that it works on real data.

### Benchmark

- **Tracking:** average position error in metres against GSR, and the share of players found. Use their `gs_hota` evaluation script for the standard score.
- **Events:** the share of BAS events we detect within ±1 s and ±5 s, by class (their `bas_map` script).
- Results go in the README and the demo video, for example "positions within X m; Y% of passes detected".

### Rules

The core pipeline stays on synthetic data (rule 4.7); SoccerTrack is licensed footage for the video path only, which Austin confirmed on 21 Oct is fine.

## Later (not v1)

- v2 tracking frames by interpolating positions, with movement calibrated against SoccerTrack's real tracking. Synthetic speed and distance labelled as estimates; the video path gives measured ones.
- Offside.
- A Scenario Director agent that writes scripts from a prompt.
- Live simulation mode: the engine plays step by step and accepts changes mid-match (planned for day 4–5).
- Generator: make the high press create more high turnovers, so the pressing club's PPDA looks like a real pressing side's.
