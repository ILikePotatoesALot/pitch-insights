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

Designed 21 Oct 2026; the core (steps 3, 4 and 7 below, plus stored commentary) built the same day on branch `agents`. The agents turn the Moment Scorer's evidence packs into commentary, check it, and fit it to each viewer. They are built with **Microsoft Agent Framework** and share one state: the `MatchBrain` (Interpreter plus Moment Scorer), which the agents read but never change.

### Model access

- **Subscription:** Austin's personal Pay-As-You-Go subscription (a free trial upgraded, so the free credit is spent first), with a US$20 monthly budget alert. Everything is in resource group `rg-pitch-insights`, region **East US 2**.
- **Deployed and tested (21 Oct):** `gpt-4o` (model version 2024-11-20, retires April 2027, after judging ends on 10 Nov) and `text-embedding-3-small`, both on the Foundry resource's **v1 API** (no API version needed).
- **Requested:** quota for `gpt-6-luna` (GPT-6's small, cheap tier: about US$0.10 / US$0.50 per million input / output tokens, far cheaper than GPT-4o). If it's approved, switch by changing the deployment name in `.env`.
- **Why not the school subscription:** the Azure for Students subscription could only deploy to five Asian regions, had no chat-model quota in any of them, and quota requests were refused automatically. It's no longer used.

### Chat model provider

One setting in `.env`, `LLM_PROVIDER`, picks where chat calls go. The agent code doesn't change:

| Provider | Use | Notes |
|---|---|---|
| `foundry` (default) | Development, stored commentary, live mode | Foundry deployment from `.env` (GPT-4o now, GPT-6 Luna if approved), low rate limit |
| `github` | Fallback if Foundry has problems | GitHub Models: free with a GitHub token (`GITHUB_TOKEN`, Models permission); daily rate limits |
| `foundry_local` | Offline experiments | Foundry Local through Agent Framework's `FoundryLocalClient`; small models (Phi, Qwen) on the CPU, slow but free |

Every stored or streamed commentary line records which provider and model wrote it.

**Network note:** the development machine's network inspects HTTPS, so Python's bundled certificate list rejects Azure's certificates. The chat client verifies against the operating system's store through `truststore`; verification is never turned off.

### The agents and how they hand off

For each headline or notable moment, in order:

1. **Moment Scorer** (code, built): the moment and its evidence pack.
2. **Memory agent** (Foundry embeddings): embeds the moment's facts and finds similar earlier moments in this match ("Carrot's second big chance down the left"), and in our generated season of matches. Adds them to the pack as `memory` facts.
3. **Explainer** (chat model; built): why the moment matters, from the pack only. Two voices: casual (one or two plain sentences) and analyst (adds the numbers: xG, win-probability swing, momentum).
4. **Groundedness check** (code, no model needed; built): every number in the text, and every player or club the league knows, must be in the pack. Numbers may be rounded decimals (3.88 as 3.9), percentages of a probability (0.9669 as 97%), number words in the facts ("five minutes" backs "5 minutes") or stoppage time as a minute (90+6' as 96th); whole numbers must otherwise match exactly. Numbers written as words (two to a hundred) are checked the same way; "one" and "zero" aren't, since they're rarely counts. The two clubs playing are always allowed. The score is the share of claims the pack supports. If anything is unsupported, the writer gets one retry with the unsupported claims named; if it fails again, the moment falls back to the Moment Scorer's headline. What the check caught is kept (`corrected`) and shown under "Why?". It can't catch claims without a name or number ("dominating" with only 33% of final-third passes); Foundry's groundedness evaluator is planned as a second opinion.
5. **Safety check** (Azure AI Content Safety): screens the text before it can reach the screen. Anything flagged falls back to the fallback headline.
6. **Translator** (Azure AI Translator): the viewer's language. Player and club names are protected from translation.
7. **Narrator** (chat model; built): short lines between big moments (momentum turning, dominance, pressing spells, rating milestones), with the same checks. The order above is the data flow, not the build order.
8. **Personalizer**: picks what each viewer sees from their profile (casual or analyst, club, favourite player, language, focus metric).
9. **Overlay Director**: turns what's left into timed overlay cues (time, duration, priority, template, data) so the screen never clutters.
10. **Scenario Director** (live simulation only): steers a live match with interventions, logged so the match replays exactly.

Failure handling is part of the design, because the Multi-Agent prize judges recovery: a timeout, a rate limit or a failed check never blocks the match. The moment shows its fallback headline at once and is upgraded if better text arrives in time.

### Stored commentary for the demo

- `scripts/generate_commentary.py` runs the agents over each sample match (headline and notable moments only) and stores the results in `samples/<name>.commentary.json`. The file records `ai_generated`, provider, model, prompt version and a summary; each moment's record has the agent, status (`ok` or `fallback`), both voices, attempts, the groundedness result, what was `corrected`, and an `input_hash` of exactly what the writer was shown.
- Re-running only redoes moments whose facts, provider, model or prompt version changed (each record also names its provider and model), so it's cheap. `--force` redoes everything.
- In replay, the server adds each moment's stored commentary to the `moment` and `catchup` messages and says who wrote it in the `meta` message, so judges never hit a rate limit or a missing key. Live simulation will call the model.
- First full run (21 Oct, GPT-4o, prompt 2026-10-21.2): 52 moments across the three samples, all grounded, none fell back. Earlier runs caught and corrected made-up numbers in first drafts.
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

Tests (`tests/test_agents.py`) use a fake writer, so they need no key or network: grounded and made-up text, the retry naming the problems, fallbacks for 429, 500, 400, timeouts and missing structured output, settings, the cache key and the stored file.

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
| Observability | OpenTelemetry traces from Agent Framework to Application Insights, sensitive data off | Next step |
| Responsible AI | The evidence pack is the only source of facts; code groundedness check with retry and fallback; rates summarised per match | Done |
| Responsible AI | Tell users the commentary is AI-generated (the note under the feed; `ai_generated` in every stored file) | Done |
| Responsible AI | Content Safety on every line; Foundry's groundedness evaluator as a second opinion | Next step |
| Prompt design | System messages structured as role and task, grounding rules, safety rules, style, output format; the moment marked as data, not instructions | Done |
| Prompt design | Prompts versioned in code; the version stored with every line, so a change triggers regeneration | Done |
| Cost | `max_tokens` near the real output size (220); at most 3 calls in flight; stored commentary reused unless its inputs change | Done |
| Code quality | Structured output (a Pydantic model) instead of parsing free text; middleware for cross-cutting concerns; the model behind an interface (`Writer`) so providers and tests can swap in | Done |
| Orchestration | Deterministic code for a predictable flow (route, check, retry, fall back), not an agent deciding the order | Done |

Sources: [transient fault handling](https://learn.microsoft.com/en-us/azure/architecture/best-practices/transient-faults), [Azure OpenAI quotas and limits](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/quota), [keyless connections](https://learn.microsoft.com/en-us/azure/developer/ai/keyless-connections), [Agent Framework observability](https://learn.microsoft.com/en-us/agent-framework/agents/observability), [monitoring and diagnostics](https://learn.microsoft.com/en-us/azure/architecture/best-practices/monitoring), [system messages](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/concepts/system-message), [safety system messages](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/concepts/safety-system-message-templates), [transparency note](https://learn.microsoft.com/en-us/azure/ai-foundry/responsible-ai/openai/transparency-note), [RAG evaluators](https://learn.microsoft.com/en-us/azure/ai-foundry/concepts/evaluation-evaluators/rag-evaluators), [structured outputs](https://learn.microsoft.com/en-us/agent-framework/agents/structured-outputs), [middleware](https://learn.microsoft.com/en-us/agent-framework/agents/middleware/), [Well-Architected AI application design](https://learn.microsoft.com/en-us/azure/well-architected/ai/application-design), [API design](https://learn.microsoft.com/en-us/azure/architecture/best-practices/api-design).

### Tracing

Agent Framework's OpenTelemetry traces go to Application Insights connected to the Foundry project, so each handoff, retry, fallback and check result can be shown in the demo and the README.

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
- Start with one half: match `117093`, first half (3.35 GB), plus its GSR and BAS annotations. Files live in the git-ignored `data/` folder.
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

- **Main:** RF-DETR (small), Apache-2.0, fine-tuned on SoccerTrack's player boxes. **Fallback:** YOLO (Ultralytics, AGPL-3.0). If time allows, fine-tune both on the same frames and compare.
- Classes: player, goalkeeper, referee, ball. The ball has no GSR ground truth, so its detection is a bonus, not a dependency.
- Panoramic view: players are small, so train and detect at 1280–1920 px, or on overlapping tiles.
- Before training, check current versions, licenses and GPU memory against the actual GPU.

### Training

- **Data:** a script turns SoccerTrack's image boxes into the detector's training format. Sample frames spaced out in time (not every frame), and split by time so test frames never sit next to training frames.
- **Where:** Austin's GPU machine. There is no Azure ML GPU quota.
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

The core pipeline stays on synthetic data (rule 4.7); SoccerTrack is licensed footage for the video path only. Mention it in the clarification question to the organisers.

## Later (not v1)

- v2 tracking frames by interpolating positions, with movement calibrated against SoccerTrack's real tracking. Synthetic speed and distance labelled as estimates; the video path gives measured ones.
- Offside.
- A Scenario Director agent that writes scripts from a prompt.
- Live simulation mode: the engine plays step by step and accepts changes mid-match (planned for day 4–5).
- Generator: make the high press create more high turnovers, so the pressing club's PPDA looks like a real pressing side's.
