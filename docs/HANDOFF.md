# Handoff

Written 21 Oct 2026. The single place to pick this project up: where things stand, how to run it, the rules we agreed, what's waiting, and what to do next. For the full plan see [PLAN.md](PLAN.md); for how each part works see [DESIGN.md](DESIGN.md).

## The project in one paragraph

**Pitch Insights** is our entry to the Microsoft Premier League Hackathon. **Submission deadline: 27 Oct 2026, 11:59 pm Pacific Time** (about 2:59 pm, 28 Oct, Singapore time). It turns football match events into explainable, personalised insight: a synthetic match generator (plus, later, real video) feeds an Interpreter (stats, patterns, win probability, live player ratings), a Moment Scorer picks the moments that matter with the evidence behind them, and a web app shows it all on a live 3D pitch, differently for casual fans and analysts. Agents on Microsoft Foundry will turn the evidence into commentary.

- **Team:** Austin and Claude. Claude writes most of the code; Austin decides, sets up Azure, tests and records the demo. Friends are only listed if they contribute (prize verification, rule 8.2).
- **Repo:** [github.com/ILikePotatoesALot/pitch-insights](https://github.com/ILikePotatoesALot/pitch-insights), **private** until submission (it must be public before 27 Oct, rule 4.4). Local copy: `C:\Users\austin\pitch-insights`.

## Where the code is

| Branch | State | Contents |
|---|---|---|
| `main` | On GitHub, at `4326538` | Event format, generator, terminal viewer, Interpret stage (merged via ILikePotatoesALot/pitch-insights#1), plan and video-path design |
| `pitch-frontend` | **Local only, 3 commits ahead of `main`, not pushed** (`29cf3bb`, `9285862`, `7fab052`) | Moment Scorer, replay server, the app, and the fixes from its code review |
| `interpret-stage` | On GitHub, merged | Can be deleted |
| `moment-scorer` | Local only, at `29cf3bb` | Already inside `pitch-frontend`; can be deleted |

**Next git step:** push `pitch-frontend` and open a pull request into `main` (Austin's OK needed).

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
| Agents on Foundry (Explainer, Narrator, Personalizer, Overlay Director, Scenario Director) | Not started | |
| Live simulation mode | Not started (designed) | |
| Video path (SoccerTrack v2 + RF-DETR) | Designed only | [DESIGN.md, Video path](DESIGN.md#video-path-planned) |
| Azure deployment | Not started | |

**Tests:** 49 passing (`cd backend && .venv\Scripts\python -m pytest`).

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

1. **Push `pitch-frontend` and open the pull request** (just say so).
2. **GPU details** for the training machine: model, VRAM, OS.
3. **A Foundry GPT model**, with its endpoint and key in `.env` (copy `.env.example`; never paste keys in chat). Needed for the agents.
4. **OK to download** SoccerTrack match 117093's first half (3.35 GB) and its annotations into `data/`.
5. **Confirm hackathon registration** went through (it closed 20 Oct).
6. **Clarification question to the organisers** (rule 11.6, in writing, before the deadline): is licensed real footage (SoccerTrack v2) fine for the video path when the core uses synthetic data?
7. Whether to add teammates as GitHub collaborators.

## Next steps, in order

| # | Step | Needs | Size |
|---|---|---|---|
| 1 | Push `pitch-frontend`, open and merge the pull request | Austin's OK | Minutes |
| 2 | **Code review of the original code** (event format, generator, stream, command-line tools, scripts) by file path; fixes on a new branch | Nothing | ~1–2 h |
| 3 | **Explainer and Narrator agents** on Foundry with Microsoft Agent Framework: turn each moment's evidence pack into commentary (casual and analyst voices, several languages); only facts from the pack | Foundry model in `.env` | ~half a day |
| 4 | **Personalise**: favourite club and player (player-focus spotlight on the pitch, pinned card, alerts), language choice, focus metric | Step 3 for languages | ~half a day |
| 5 | **Overlay Director**: timed, machine-readable overlay cues (time, duration, priority, template, data) so the screen never clutters | Nothing | ~2 h |
| 6 | **Live simulation mode** and the **Scenario Director** agent that steers a live match (logged so it replays exactly) | Step 3 | ~half a day |
| 7 | **SoccerTrack preparation**: loader (mind the format traps), conversion to our events and frames, training kit for the GPU machine | Download OK | ~half a day |
| 8 | **Train the detector** (RF-DETR, YOLO fallback), video-to-frames and events, accuracy benchmark against SoccerTrack. Keep-or-cut decision on 23 Oct | GPU machine | 1–2 days |
| 9 | **Deploy to Azure**: backend and detection on Container Apps, app on Static Web Apps | Azure subscription | ~half a day |
| 10 | **Demo video** (under 2 minutes; hero shot: same match, different viewers side by side), README polish, make the repo public, submit | Everything above | 27 Oct at the latest |

**If time runs short, cut in this order:** speech audio, Event Hubs, live simulation mode, then 3D polish. Never cut the five pipeline stages or the demo video.

## Submission checklist (27 Oct)

- [ ] Repo public, README explains setup, architecture and Microsoft technologies used
- [ ] Demo video under 2 minutes, public link, no copyrighted music or third-party logos
- [ ] Project description: what it does, which Microsoft and Azure technologies, what problem it solves
- [ ] A link judges can use to try it (Azure deployment), free until 10 Nov
- [ ] Credits: Roboflow (if used), SoccerTrack v2 (if used)
- [ ] License file matches the final choice (AGPL-3.0, or MIT/Apache-2.0 if Ultralytics is dropped)
- [ ] Clarification answer from the organisers on real footage, if received
