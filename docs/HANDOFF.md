# Handoff

Written 21 Oct 2026, updated 22 Oct (video path). The single place to pick this project up: where things stand, how to run it, the rules we agreed, what's waiting, and what to do next. For the full plan see [PLAN.md](PLAN.md); for how each part works see [DESIGN.md](DESIGN.md).

## The project in one paragraph

**Pitch Insights** is our entry to the Microsoft Premier League Hackathon. **Submission deadline: 27 Oct 2026, 11:59 pm Pacific Time** (about 2:59 pm, 28 Oct, Singapore time). It turns football match events into explainable, personalised insight: a synthetic match generator (plus, later, real video) feeds an Interpreter (stats, patterns, win probability, live player ratings), a Moment Scorer picks the moments that matter with the evidence behind them, and a web app shows it all on a live 3D pitch, differently for casual fans and analysts. Agents built with Microsoft Agent Framework will turn the evidence into checked commentary, using Foundry for embeddings and tracing.

- **Team:** Austin and Claude. Claude writes most of the code; Austin decides, sets up Azure, tests and records the demo. Austin is registered (confirmed 21 Oct). Teammates have been added as GitHub collaborators but aren't registered participants, so they aren't listed as team members (prize verification, rule 8.2).
- **Repo:** [github.com/ILikePotatoesALot/pitch-insights](https://github.com/ILikePotatoesALot/pitch-insights), **private** until submission (it must be public before 27 Oct, rule 4.4). Local copy: `C:\Users\austin\pitch-insights`.

## Where the code is

| Branch | State | Contents |
|---|---|---|
| `main` | On GitHub | Everything built so far: event format, generator, terminal viewer, Interpret stage (ILikePotatoesALot/pitch-insights#1), Moment Scorer, replay server and the app (ILikePotatoesALot/pitch-insights#2), review fixes for the original code (ILikePotatoesALot/pitch-insights#3), agents core (ILikePotatoesALot/pitch-insights#4), Memory agent (ILikePotatoesALot/pitch-insights#6) |
| `ai-services` | Local only, not pushed | Content Safety, Translator (five languages), tracing to Application Insights, Foundry groundedness evaluator |
| `video-path` | Local only, not pushed; cut from `ai-services` | The video path on SoccerTrack v2: loader, tiled RF-DETR, pitch calibration, tracker, teams, events, benchmark (22 Oct) |

The merged branches are deleted. Every branch so far has had a `/code-review`, and the original code was reviewed by path on `generator-review`.

**Next git step:** `ai-services` and `video-path` are committed locally and reviewed, not pushed. Push them and open pull requests when Austin says (`video-path` builds on `ai-services`, so it goes second).

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
| Agents core (Explainer, Narrator, groundedness check with retry and fallback, stored commentary, commentary in the app) | Built, reviewed twice, fixed, merged (ILikePotatoesALot/pitch-insights#4) | `backend/pitch_insights/agents/`, [DESIGN.md, Agents](DESIGN.md#agents) |
| Memory agent (similar earlier moments as `memory` facts; Foundry embeddings stored next to each sample, so replays need no network) | Built, reviewed, merged (ILikePotatoesALot/pitch-insights#6) | `backend/pitch_insights/agents/memory.py`, [DESIGN.md, Memory agent](DESIGN.md#memory-agent) |
| Safety check (Azure AI Content Safety: every line screened, blocked at severity 2, fails closed) | Built on `ai-services` (22 Oct); 52 stored moments screened, none blocked | `backend/pitch_insights/agents/safety.py`, [DESIGN.md, Safety check](DESIGN.md#safety-check) |
| Translations (Azure AI Translator: Spanish, French, German, Dutch, Simplified Chinese; names and clocks protected; checked; stored) | Built on `ai-services` (22 Oct); 9 of 3,180 kept English | `backend/pitch_insights/agents/translate.py`, [DESIGN.md, Translations](DESIGN.md#translations) |
| Tracing (Agent Framework to Application Insights, no prompts or replies) and Foundry's groundedness evaluator (all 52 lines pass, lowest 4 of 5) | Built on `ai-services` (22 Oct) | `agents/tracing.py`, `scripts/evaluate_groundedness.py` |
| Other agents (Personalizer, Overlay Director, Scenario Director) | Designed, not started | [DESIGN.md, Agents](DESIGN.md#agents) |
| Live simulation mode | Not started (designed) | |
| Video path (SoccerTrack v2 + RF-DETR) | Built on `video-path` (22 Oct) on a 100 s clip, reviewed; keep-or-cut decision 24 Oct. 91% of players found at 85% precision, 0.78 m mean position error, 88% teams, 19 events (74% match SoccerTrack's within 5 s) | `video/`, `backend/pitch_insights/video/`, [DESIGN.md, Video path](DESIGN.md#video-path) |
| Azure deployment | Not started | |

**Tests:** 178 passing (38 of them for the video path, on hand-made snippets: no video, model or network) (`cd backend && .venv\Scripts\python -m pytest`). No key or network needed: the agent tests use a fake writer that raises errors the way Agent Framework does, the memory tests use fake embedders, and Content Safety and Translator are faked with httpx's MockTransport. `test_disconnect_while_paused_ends_the_replay` failed once in a full run on 21 Oct and passed on every rerun; it's timing-sensitive (a 0.3 s sleep).

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

Then open http://localhost:5173. In Claude Code, both servers are also set up in `C:\Users\austin\.claude\launch.json` as `pitch-replay-server` and `pitch-frontend`. If port 8000 is taken (for example by another session's server), the replay server moves to 8001; use `pitch-frontend-8001` (port 5174), which points the app at 8001 through `PITCH_API`. The replay server doesn't reload, so restart it after backend changes.

**Memory embeddings** (needs the Foundry values in `.env`; embeds only descriptions not already stored, so re-running costs nothing when nothing changed). Run it before the stored commentary whenever the moments or their descriptions change:

```
cd backend
.venv\Scripts\python scripts/embed_moments.py
```

**Stored commentary** (needs the Foundry values in `.env`; redoes only moments whose facts, model or prompt changed, and screens older lines with Content Safety without calling the model; traces to Application Insights when its connection string is set):

```
cd backend
.venv\Scripts\python scripts/generate_commentary.py
```

**Translations and the groundedness evaluator** (run after the stored commentary; each sends only what changed). The Translator's free tier is paced to 30,000 characters a minute, so a full run takes about 10 minutes:

```
cd backend
.venv\Scripts\python scripts/translate_moments.py
.venv\Scripts\python scripts/evaluate_groundedness.py
```

Order after changing moments: `embed_moments.py`, then `generate_commentary.py`, then `translate_moments.py` and `evaluate_groundedness.py`.

**Video path** (needs the SoccerTrack files under `data/soccertrack/117093/` and the separate environment `video\.venv`: Python 3.12, torch CPU, rfdetr 1.11.2, opencv, supervision, truststore; RF-DETR small's weights are in `C:\Users\austin\.roboflow\models\`). From the repo root:

```
backend\.venv\Scripts\python video\extract_gsr.py      # 25 s: the clip's ground truth and calibration pairs
video\.venv\Scripts\python video\detect.py calib       # 11 min: 76 frames before the clip
video\.venv\Scripts\python video\calibrate.py          # seconds: the image-to-pitch mapping
video\.venv\Scripts\python video\detect.py clip        # about 65 min: 500 frames; resumable, run it in the background
video\.venv\Scripts\python video\process.py            # 2 s: tracking, teams, ball, frames, events, benchmark
video\.venv\Scripts\python video\preview.py            # 1 min: data\video\117093\preview.mp4 to check by eye
```

The clip is set in `video/clip.py`. Outputs go to `samples/video/` (not `samples/` itself: the server and the commentary scripts read every `samples/*.jsonl` as a match). `video/log_mlflow.py` logs the benchmark run to the Azure ML workspace through MLflow; each run needs Austin to sign in in a browser window.

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
- Detector plan: the **pre-trained RF-DETR (small)** as released, on a short clip, no training and no GPU (decided 21 Oct). **The video path stays** (decided 22 Oct); fine-tuning is planned later in Azure ML (workspace `ML-pitch-insights`) once the account has GPU quota (Austin puts the earlier refusals down to the account being new); runs tracked and the model registered in Azure ML through MLflow; detection served on CPU in Azure Container Apps.
- License: **Apache-2.0** since 22 Oct (Austin's call), with a `NOTICE` file for RF-DETR, SoccerTrack v2 and the ByteTrack idea. It was AGPL-3.0 only because YOLO (Ultralytics) was planned; nothing uses Ultralytics.
- Everything downstream reads events one at a time and never looks ahead, so a live feed and a replay behave the same. Keep it that way; there are tests for it.
- **Azure:** Austin's **personal Pay-As-You-Go subscription** (upgraded free trial; free credit spent first; US$20 monthly budget alert). Resource group `rg-pitch-insights`, everything in **East US 2**. The school's Azure for Students subscription is no longer used (five Asian regions only, no chat-model quota, quota requests refused automatically).
- **Models:** `gpt-4o` (version 2024-11-20, retires April 2027) and `text-embedding-3-small`, both tested 21 Oct on the Foundry resource's v1 API (no API version). Quota for `gpt-6-luna` was requested and refused (21 Oct), so the agents stay on `gpt-4o`; keep calls few (stored commentary, `max_tokens` 220) and watch the US$20 budget alert. `LLM_PROVIDER` picks `foundry` (default), `github` (fallback) or `foundry_local`. See [DESIGN.md, Agents](DESIGN.md#agents).
- **Keys:** in `.env` only (ignored by git). `.env.example` holds placeholders; never put real values in it, because it's committed.
- **HTTPS on this machine:** the network inspects HTTPS, so Python's built-in certificate list fails with "self-signed certificate in certificate chain". Use the Windows certificate store (`ssl.create_default_context()`); never turn verification off. curl needs `--ssl-no-revoke` for a related reason.
- **No admin rights on this machine** (an organisation laptop): machine-wide installers such as Azure CLI can't be installed (tried 22 Oct; skipped). So Azure sign-ins from Python use a browser window each time, and the deployment (step 8) needs another route: the Azure portal, Azure Cloud Shell, or another machine.

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
- Video path: 5 frames a second (not 10); no shots (the ball is often missed in flight); the ball is found in under half the frames; team from shirt colour is about 88% right and track IDs switch (a player keeps one ID for 72% of frames); the spectator and spare-ball filters need the whole clip, so they're offline only; team, tracker and event settings were chosen on the benchmark clip itself.
- Machine translation can get idioms wrong while keeping every name and number ("turn up the pressure" came out as "turn up the news" in Chinese), and the check can't catch that. The app labels translations as machine-made.

## Data on this machine

- **SoccerTrack v2, match 117093, first half**, downloaded 21 Oct from Hugging Face (`atomscott/soccertrack-v2`, CC BY 4.0) into `data/soccertrack/117093/` (git-ignored): the video `117093_panorama_1st_half.mp4` (3.35 GB), tracking ground truth `117093_1st.json` (2.71 GB) and events `117093_12_class_events.json` (0.5 MB). Sizes checked against the dataset's file list.
- The dataset is gated: downloads need Austin's Hugging Face read token as `HF_TOKEN` in `.env` (the terms are accepted on Austin's account).
- **Video path working files** in `data/video/117093/` (git-ignored, about 135 MB): the clip's ground truth (`gsr_clip.jsonl`), calibration pairs, raw detections for the clip (4 MB) and the calibration frames, and `preview.mp4` (126 MB).
- **CV environment** `video\.venv` (Python 3.12, separate from the backend's) and RF-DETR small's weights (368 MB) in `C:\Users\austin\.roboflow\models\rf-detr-small.pth`.

## Waiting on Austin

1. Done 22 Oct: **the video path stays.** Fine-tuning comes later, in Azure ML.
2. Done 22 Oct: **MLflow logging to Azure ML.** `mlflow-skinny` 3.15.0 and `azureml-mlflow` 1.62.0.post6 are in `video\.venv`, `MLFLOW_TRACKING_URI` is in `.env` (placeholder in `.env.example`), and the benchmark is run `117093-38min-rfdetr-small-pretrained` in experiment `video-path-benchmark`. Every run of `video\log_mlflow.py` opens a browser window for Austin to sign in (no Azure CLI or token cache on this machine), so run it only with Austin there.
3. Done 22 Oct: **relicensed as Apache-2.0.**
4. **Later:** fine-tuning the detector in Azure ML, once GPU quota is granted (workspace `ML-pitch-insights`, family **NCASv3_T4**, East US 2, 4 cores; request it from Compute > Compute clusters > New, or Azure portal > Quotas > Machine Learning) or on Austin's GPU machine.

Settled 22 Oct: all four free-tier services (Content Safety, Translator, Application Insights, Speech) are in East US 2 and connect with the values in `.env`.

Settled 21 Oct: registration is confirmed; licensed footage (SoccerTrack v2) is fine for the video path, so no clarification question is needed; teammates are GitHub collaborators only; GPT-6 Luna quota was refused; the video path uses the pre-trained detector.

## Next steps, in order

| # | Step | Needs | Size |
|---|---|---|---|
| 1 | Done: **agents core**, merged in ILikePotatoesALot/pitch-insights#4 (21 Oct) | | |
| 2 | Done 22 Oct: **Foundry and AI services** (Memory agent merged; Content Safety, Translator, tracing and the groundedness evaluator on `ai-services`) | | |
| 3 | **Overlay Director**: timed, machine-readable overlay cues (time, duration, priority, template, data) so the screen never clutters | Nothing | ~2 h |
| 4 | **Personalise**: favourite club and player (player-focus spotlight on the pitch, pinned card, alerts), language choice, focus metric | Steps 1–2 | ~half a day |
| 5 | Decided 21 Oct: the video path uses **pre-trained detection on a short clip** (no GPU quota needed); fine-tuning maybe later. Cut it if it isn't working by 24 Oct | | |
| 6 | **Live simulation mode** and the **Scenario Director** agent that steers a live match (logged so it replays exactly) | Step 1 | ~half a day |
| 7 | Done 22 Oct on `video-path`: **SoccerTrack loader**, tiled detection on a 100 s clip, pitch positions, `frame` messages, events, benchmark. Next, if kept: a second clip to check the settings chosen on this one, better shirt colours for teams, a `match_meta` so the Interpreter can read video events, the clip in the app; fine-tuning if a GPU arrives | Austin's keep-or-cut call | ~half a day for the next steps |
| 8 | **Deploy to Azure**: backend on Container Apps, app on Static Web Apps, keys in Key Vault through a managed identity, Cosmos DB free tier for profiles and stored commentary | Steps 1–4 | ~half a day |
| 9 | **Demo video** (under 2 minutes; hero shot: same match, different viewers side by side), README polish, make the repo public, submit | Everything above | 27 Oct at the latest |

**If time runs short, cut in this order:** speech audio, Event Hubs, the video path, live simulation mode and the Scenario Director, then 3D polish. Never cut the five pipeline stages, the stored commentary or the demo video.

## Submission checklist (27 Oct)

- [ ] Repo public, README explains setup, architecture and Microsoft technologies used
- [ ] Demo video under 2 minutes, public link, no copyrighted music or third-party logos
- [ ] Project description: what it does, which Microsoft and Azure technologies, what problem it solves
- [ ] A link judges can use to try it (Azure deployment), free until 10 Nov
- [x] Credits: RF-DETR (Roboflow), SoccerTrack v2, the ByteTrack idea (README and NOTICE)
- [x] License file matches the final choice (Apache-2.0, 22 Oct)
