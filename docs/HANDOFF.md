# Handoff

Written 21 Oct 2026. The single place to pick this project up: where things stand, how to run it, the rules we agreed, what's waiting, and what to do next. For the full plan see [PLAN.md](PLAN.md); for how each part works see [DESIGN.md](DESIGN.md).

## The project in one paragraph

**Pitch Insights** is our entry to the Microsoft Premier League Hackathon. **Submission deadline: 27 Oct 2026, 11:59 pm Pacific Time** (about 2:59 pm, 28 Oct, Singapore time). It turns football match events into explainable, personalised insight: a synthetic match generator (plus, later, real video) feeds an Interpreter (stats, patterns, win probability, live player ratings), a Moment Scorer picks the moments that matter with the evidence behind them, and a web app shows it all on a live 3D pitch, differently for casual fans and analysts. Agents built with Microsoft Agent Framework will turn the evidence into checked commentary, using Foundry for embeddings and tracing.

- **Team:** Austin and Claude. Claude writes most of the code; Austin decides, sets up Azure, tests and records the demo. Friends are only listed if they contribute (prize verification, rule 8.2).
- **Repo:** [github.com/ILikePotatoesALot/pitch-insights](https://github.com/ILikePotatoesALot/pitch-insights), **private** until submission (it must be public before 27 Oct, rule 4.4). Local copy: `C:\Users\austin\pitch-insights`.

## Where the code is

| Branch | State | Contents |
|---|---|---|
| `main` | On GitHub | Everything built so far: event format, generator, terminal viewer, Interpret stage (ILikePotatoesALot/pitch-insights#1), Moment Scorer, replay server and the app (ILikePotatoesALot/pitch-insights#2), review fixes for the original code (ILikePotatoesALot/pitch-insights#3) |

`main` is the only branch; the merged ones are deleted. Every branch so far has had a `/code-review`, and the original code was reviewed by path on `generator-review`.

**Next git step:** the agents go on a new branch (for example `agents`), with a `/code-review` before the pull request.

## What's built

| Stage | Status | Where |
|---|---|---|
| Event format v1 (12 event types, `match_meta`, JSON Schemas) | Built | `backend/pitch_insights/events/`, `docs/schema/` |
| Synthetic generator v1 (4 clubs, 80 players, scripts, seed search) | Built; realism check passes over 900 matches | `backend/pitch_insights/generator/` |
| Terminal viewer | Built | `backend/pitch_insights/watch.py` |
| Interpret stage (stats, xT, patterns, win probability, ratings, signals) | Built, reviewed, fixed | `backend/pitch_insights/interpret/` |
| Moment Scorer (moments, tiers, evidence packs, fallback headlines) | Built, reviewed, fixed | `backend/pitch_insights/explain/moments.py` |
| Replay server (FastAPI WebSocket) | Built, reviewed, fixed | `backend/pitch_insights/server.py` |
| App (Vite + React + Three.js: 3D pitch, moments feed, ratings, stats, casual/analyst modes) | Built, reviewed, fixed, checked in the browser | `frontend/` |
| Agents (Memory, Explainer, Narrator, Personalizer, Overlay Director, Scenario Director; groundedness and safety checks; stored commentary) | Designed, not started | [DESIGN.md, Agents](DESIGN.md#agents-planned) |
| Live simulation mode | Not started (designed) | |
| Video path (SoccerTrack v2 + RF-DETR) | Designed only | [DESIGN.md, Video path](DESIGN.md#video-path-planned) |
| Azure deployment | Not started | |

**Tests:** 59 passing (`cd backend && .venv\Scripts\python -m pytest`).

**Calibration checks** (all passing; re-run after changing the generator, ratings or moments):

| Script | Checks | Latest result |
|---|---|---|
| `scripts/validate_realism.py` | Generated matches look like real football | All pass; 2.7–2.8 goals, 13.5 shots a team, home/draw/away about 45/24/31% |
| `scripts/calibrate_ratings.py` | Live ratings look like public rating systems | Average 6.8, spread 0.76, best in match about 8.5, every position 6.8–6.9 |
| `scripts/calibrate_moments.py` | How many moments the scorer picks | About 4 headlines and 10 shown moments a match |
| `scripts/build_xt.py` | Rebuilds the expected-threat grid | Only needed if the generator changes a lot |

## How to run it

```
cd backend
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest
python -m pitch_insights.generate --seed 42 --home POT --away CAR --out ../data
python -m pitch_insights.watch ../samples/comeback-POT-CAR.jsonl --speed 60 --from 80
python -m pitch_insights.interpret ../samples/comeback-POT-CAR.jsonl --at 70 --player Madekuta
```

The app needs two terminals:

```
cd backend
.venv\Scripts\python -m uvicorn pitch_insights.server:app --port 8000
```

```
cd frontend
npm install
npm run dev
```

Then open http://localhost:5173. In Claude Code, both servers are also set up in `C:\Users\austin\.claude\launch.json` as `pitch-replay-server` and `pitch-frontend`.

**Demo matches** (in `samples/`): `comeback-POT-CAR` (seed 52: Potato lead 2–1, Carrot win 3–2 with an 88' equaliser and a 96th-minute winner; the hero match), `thriller-CAR-BRO` (seed 4: Broccoli win 4–3 away), `red-card-CAU-POT` (seed 24: Potato down to ten at 20', Cauliflower win 2–0).

## Rules and decisions to keep

**Hackathon rules**
- New project only (rule 4.3). The old `Football_Computer_Vision_Match_Analysis` repo (April 2026, a school assignment) is **reference only; never copy code from it.**
- The core pipeline must use **synthetic data** (rule 4.7). Real footage only for the video path.
- No third-party trademarks or copyrighted material (rule 4.4): fictional clubs and players, no Premier League names or logos, no copyrighted music in the video.
- Demo video **under 2 minutes**, on a public link; repo **public**; English; judges must be able to try it free until 10 Nov (rules 4.4, 4.8).
- Judging: five criteria at 20% each (technical implementation, agentic design, real-world impact, UX and presentation, category fit). We aim for the **Multi-Agent** category prize, with Foundry as a backup.

**Data and footage**
- Clubs: **Potato FC** (POT, possession), **Carrot FC** (CAR, high press), **Broccoli FC** (BRO, direct), **Cauliflower FC** (CAU, counter). Player names blend surnames with invented first names; no real full name or whole real surname.
- **Never use the Roboflow/Bundesliga sample footage.** Those clips come from Kaggle's DFL competition, which is competition-use only. The Roboflow *model* (CC BY 4.0) is fine with credit.
- Video source: **SoccerTrack v2** (CC BY 4.0, consented amateur players, no names). Credit it. In the demo label its players by side and number ("Left #7"), never with our fictional names. Its shipped files differ from its own spec; see DESIGN.md before writing the loader.

**Technical**
- Python 3.12 (3.14 is the machine default, but CV packages lag). Node 24.
- Detector plan: **RF-DETR (small)** first, **YOLO** as fallback. Training on Austin's GPU machine (no Azure ML GPU quota); runs tracked and the model registered in Azure ML through MLflow; detection served on CPU in Azure Container Apps.
- License: AGPL-3.0 for now (because of Ultralytics). If we use RF-DETR and drop Ultralytics, relicense as MIT or Apache-2.0, which suits the Enterprise category better.
- Everything downstream reads events one at a time and never looks ahead, so a live feed and a replay behave the same. Keep it that way; there are tests for it.
- **Azure:** Austin's **personal Pay-As-You-Go subscription** (upgraded free trial; free credit spent first; US$20 monthly budget alert). Resource group `rg-pitch-insights`, everything in **East US 2**. The school's Azure for Students subscription is no longer used (five Asian regions only, no chat-model quota, quota requests refused automatically).
- **Models:** `gpt-4o` (version 2024-11-20, retires April 2027) and `text-embedding-3-small`, both tested 21 Oct on the Foundry resource's v1 API (no API version). Quota for `gpt-6-luna` requested; much cheaper, switch to it by changing the deployment name in `.env` if approved. `LLM_PROVIDER` picks `foundry` (default), `github` (fallback) or `foundry_local`. See [DESIGN.md, Agents](DESIGN.md#agents-planned).
- **Keys:** in `.env` only (ignored by git). `.env.example` holds placeholders; never put real values in it, because it's committed.
- **HTTPS on this machine:** the network inspects HTTPS, so Python's built-in certificate list fails with "self-signed certificate in certificate chain". Use the Windows certificate store (`ssl.create_default_context()`); never turn verification off. curl needs `--ssl-no-revoke` for a related reason.

**Ways of working**
- Commit locally as often as needed; **push only when Austin says so.**
- New work goes on a branch, then a pull request into `main` (merged with a merge commit so the history stays).
- Run `/code-review` on a branch before it goes into `main`. Fix findings on the branch.

## Known limits (accepted for now)

- Draws are slightly rare (about 22–25%) and weaker clubs score under one goal a match.
- Cauliflower's striker scores about two-thirds of its goals.
- The high press creates many pressures but not many extra high turnovers, so Carrot's PPDA isn't as low as a real pressing side's (the pressure index shows the pressing correctly).
- Synthetic speed and distance don't exist yet; they come with the v2 tracking frames (estimates) and the video path (measured).
- The app's JavaScript bundle is large (Three.js); fine for now.

## Waiting on Austin

1. **Free-tier resources** in `rg-pitch-insights`, East US 2: Content Safety (F0), Translator (F0, region Global), Speech (F0, optional), and Application Insights connected from the Foundry project's Tracing page. Endpoints and keys in `.env`. Needed for next step 2.
2. **The GPT-6 Luna quota decision** from Microsoft (requested 21 Oct). Nothing to do unless it's approved.
3. **Video path inputs**, by 23 Oct, or it's cut: either a small T4 GPU quota in Azure ML or the GPU machine's details (model, VRAM, OS), plus the **OK to download** SoccerTrack match 117093's first half (3.35 GB) and its annotations into `data/`.
4. **Confirm hackathon registration** went through (it closed 20 Oct).
5. **Clarification question to the organisers** (rule 11.6, in writing, before the deadline): is licensed real footage (SoccerTrack v2) fine for the video path when the core uses synthetic data? Only needed if the video path stays.
6. Whether to add teammates as GitHub collaborators.

## Next steps, in order

| # | Step | Needs | Size |
|---|---|---|---|
| 1 | **Agents core** on a new branch: provider switch, Explainer (casual and analyst), groundedness check with retry and fallback, Narrator, stored commentary for the samples, commentary shown in the app | Nothing (Foundry is ready) | ~1 day |
| 2 | **Foundry and AI services:** Memory agent (embeddings), Foundry groundedness evaluation, Content Safety, Translator, tracing to Application Insights | Free-tier resources | ~half a day |
| 3 | **Overlay Director**: timed, machine-readable overlay cues (time, duration, priority, template, data) so the screen never clutters | Nothing | ~2 h |
| 4 | **Personalise**: favourite club and player (player-focus spotlight on the pitch, pinned card, alerts), language choice, focus metric | Steps 1–2 | ~half a day |
| 5 | **Video path keep-or-cut, 23 Oct.** Keep only if a GPU (Azure ML quota or the GPU machine) and the download OK are in by then; otherwise cut it and say so in the README | GPU, download OK | Decision |
| 6 | **Live simulation mode** and the **Scenario Director** agent that steers a live match (logged so it replays exactly) | Step 1 | ~half a day |
| 7 | If kept: **SoccerTrack preparation and detector training** (loader, conversion, RF-DETR with YOLO fallback, accuracy benchmark) | GPU machine | 1–2 days |
| 8 | **Deploy to Azure**: backend on Container Apps, app on Static Web Apps, keys in Key Vault through a managed identity, Cosmos DB free tier for profiles and stored commentary | Steps 1–4 | ~half a day |
| 9 | **Demo video** (under 2 minutes; hero shot: same match, different viewers side by side), README polish, make the repo public, submit | Everything above | 27 Oct at the latest |

**If time runs short, cut in this order:** speech audio, Event Hubs, the video path, live simulation mode and the Scenario Director, then 3D polish. Never cut the five pipeline stages, the stored commentary or the demo video.

## Submission checklist (27 Oct)

- [ ] Repo public, README explains setup, architecture and Microsoft technologies used
- [ ] Demo video under 2 minutes, public link, no copyrighted music or third-party logos
- [ ] Project description: what it does, which Microsoft and Azure technologies, what problem it solves
- [ ] A link judges can use to try it (Azure deployment), free until 10 Nov
- [ ] Credits: Roboflow (if used), SoccerTrack v2 (if used)
- [ ] License file matches the final choice (AGPL-3.0, or MIT/Apache-2.0 if Ultralytics is dropped)
- [ ] Clarification answer from the organisers on real footage, if received
