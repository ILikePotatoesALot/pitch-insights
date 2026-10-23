# Handoff

Written 21 Oct 2026, updated 22 Oct (video path; fine-tuning run on Austin's GPU machine) and 23 Oct (Overlay Director; deploy prep; Personalise). The single place to pick this project up: where things stand, how to run it, the rules we agreed, what's waiting, and what to do next. For the full plan see [PLAN.md](PLAN.md); for how each part works see [DESIGN.md](DESIGN.md).

## The project in one paragraph

**Pitch Insights** is our entry to the Microsoft Premier League Hackathon. **Submission deadline: 27 Oct 2026, 11:59 pm Pacific Time** (about 2:59 pm, 28 Oct, Singapore time). It turns football match events into explainable, personalised insight: a synthetic match generator (plus, later, real video) feeds an Interpreter (stats, patterns, win probability, live player ratings), a Moment Scorer picks the moments that matter with the evidence behind them, and a web app shows it all on a live 3D pitch, differently for casual fans and analysts. Agents built with Microsoft Agent Framework will turn the evidence into checked commentary, using Foundry for embeddings and tracing.

- **Team:** Austin and Claude. Claude writes most of the code; Austin decides, sets up Azure, tests and records the demo. Austin is registered (confirmed 21 Oct). Teammates have been added as GitHub collaborators but aren't registered participants, so they aren't listed as team members (prize verification, rule 8.2).
- **Repo:** [github.com/ILikePotatoesALot/pitch-insights](https://github.com/ILikePotatoesALot/pitch-insights), **private** until submission (it must be public before 27 Oct, rule 4.4). Local copy: `C:\Users\austin\pitch-insights`.

## Where the code is

| Branch | State | Contents |
|---|---|---|
| `main` | On GitHub | Everything built so far: event format, generator, terminal viewer, Interpret stage (ILikePotatoesALot/pitch-insights#1), Moment Scorer, replay server and the app (ILikePotatoesALot/pitch-insights#2), review fixes for the original code (ILikePotatoesALot/pitch-insights#3), agents core (ILikePotatoesALot/pitch-insights#4), Memory agent (ILikePotatoesALot/pitch-insights#6), Content Safety, Translator, tracing and the groundedness evaluator (ILikePotatoesALot/pitch-insights#8, 22 Oct), the video path (ILikePotatoesALot/pitch-insights#9), the fine-tuning results from the GPU machine (ILikePotatoesALot/pitch-insights#10) and the AMD guide with doc fixes (ILikePotatoesALot/pitch-insights#11, 22 Oct), the Overlay Director and the 23 Oct handoff notes (ILikePotatoesALot/pitch-insights#12, 23 Oct) |
| `claude/personalise-95bc8a` | **On GitHub as `personalise`, pull request into `main` open (23 Oct)**; cut from the Overlay Director's branch, which is now in `main` | Personalise (23 Oct): `backend/pitch_insights/director/personalise.py` (profile parsing, favourite boost, alerts, relevance, focus metric), the profile on the WebSocket connection and `GET /api/clubs`, the app's profile picker, spotlight, pinned card, focus strip and side-by-side view, 70 new tests, DESIGN.md (Personalise, practices table) and this file. `/code-review` (high, 23 Oct) found 13 things, 11 fixed: a second yellow raised both a booking and a sending-off alert, a spotlight keeping the old match's colour, the boost cap ignoring the Director's own urgent line, a layout read every frame, `/api/clubs` reading every sample on each request, the mode kept in two places, a double-counted minute, a convoluted club-change rule, a fragile CSS selector, an unused property and this row's own claim. Not done: `Personaliser.cues` still has a six-parameter signature, and `profile.ts` has no tests (the app has no frontend test runner) |

No other branches besides Personalise's: `video-path` and `video-finetune-results` are merged and deleted, locally and on GitHub (22 Oct), and so is the Overlay Director's (23 Oct). Pull requests #9 and #10 were opened and merged from the GPU machine's side; #11 was merged by Austin. Every branch so far has had a `/code-review` except the results branch (no code changes) and the AMD-guide pull request (docs, a two-line `train.py` change and a comment in `requirements.txt`); the original code was reviewed by path on `generator-review`.

**Next git step:** merge Personalise's pull request into `main` (merge commit) when Austin says, then delete its branch. New work goes on a branch from `main`, then a pull request merged with a merge commit.

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
| Safety check (Azure AI Content Safety: every line screened, blocked at severity 2, fails closed) | Built 22 Oct, merged in ILikePotatoesALot/pitch-insights#8; 52 stored moments screened, none blocked | `backend/pitch_insights/agents/safety.py`, [DESIGN.md, Safety check](DESIGN.md#safety-check) |
| Translations (Azure AI Translator: Spanish, French, German, Dutch, Simplified Chinese; names and clocks protected; checked; stored) | Built 22 Oct, merged in ILikePotatoesALot/pitch-insights#8; 9 of 3,180 kept English | `backend/pitch_insights/agents/translate.py`, [DESIGN.md, Translations](DESIGN.md#translations) |
| Tracing (Agent Framework to Application Insights, no prompts or replies) and Foundry's groundedness evaluator (all 52 lines pass, lowest 4 of 5) | Built 22 Oct, merged in ILikePotatoesALot/pitch-insights#8 | `agents/tracing.py`, `scripts/evaluate_groundedness.py` |
| Overlay Director (timed overlay cues with clutter rules: one lower-third, at most 2 cards, cooldowns, pre-emption by priority, delay then drop; deterministic code, no model call; overlays and Broadcast/Fan layouts in the app) | Built 23 Oct, merged in ILikePotatoesALot/pitch-insights#12; checked in the browser at 60x in Broadcast and Fan, casual and analyst: no overlap, cues clear on time, pause freezes them | `backend/pitch_insights/director/`, `frontend/src/components/Overlays.tsx`, [DESIGN.md, Overlay Director](DESIGN.md#overlay-director) |
| Personalise (profile: favourite club and player, mode, language, focus metric; sent with the connection; the Director boosts the favourite's cues, adds alerts for the favourite player, keeps the other side's rating alerts and speed popups off a fan's screen; spotlight on the pitch, pinned card, focus strip; first-visit picker; two viewers side by side at `/?compare=1`; deterministic code, no model call) | Built 23 Oct on `claude/personalise-95bc8a`; checked in the browser: two profiles look clearly different, the spotlight follows the player, alerts fire, no overlap at 390 px | `backend/pitch_insights/director/personalise.py`, `frontend/src/profile.ts`, [DESIGN.md, Personalise](DESIGN.md#personalise) |
| Other agents (Scenario Director) | Designed, not started | [DESIGN.md, Agents](DESIGN.md#agents) |
| Live simulation mode | Not started (designed) | |
| Video path (SoccerTrack v2 + RF-DETR) | Built (22 Oct) on a 100 s clip, reviewed, merged into `main`; kept (22 Oct). Detector fine-tuned on Austin's GPU machine (22 Oct): 93% of players found at 97% precision (pre-trained: 90% at 85%), 0.76 m mean position error, 95% teams, 14 events (79% match SoccerTrack's within 5 s) | `video/`, `backend/pitch_insights/video/`, [DESIGN.md, Video path](DESIGN.md#video-path) |
| Azure deployment | Not started | |

**Tests:** 333 passing (51 of them for the video path, on hand-made snippets: no video, model or network; 58 for the Overlay Director and its cues in the server stream; 70 for Personalise: profile parsing, boost, alerts, relevance, focus rows, determinism and its server messages) (`cd backend && .venv\Scripts\python -m pytest`). No key or network needed: the agent tests use a fake writer that raises errors the way Agent Framework does, the memory tests use fake embedders, and Content Safety and Translator are faked with httpx's MockTransport. `test_disconnect_while_paused_ends_the_replay` failed once in a full run on 21 Oct and passed on every rerun; it's timing-sensitive (a 0.3 s sleep).

**Calibration checks** (all passing; re-run after changing the generator, ratings or moments):

| Script | Checks | Latest result |
|---|---|---|
| `scripts/validate_realism.py` | Generated matches look like real football | All pass; 2.7–2.8 goals, 13.5 shots a team, home/draw/away about 45/24/31% |
| `scripts/calibrate_ratings.py` | Live ratings look like public rating systems | Average 6.8, spread 0.76, best in match about 8.5, every position 6.8–6.9 |
| `scripts/calibrate_moments.py` | How many moments the scorer picks | About 4 headlines and 10 shown moments a match |
| `scripts/build_xt.py` | Rebuilds the expected-threat grid | Only needed if the generator changes a lot |
| `scripts/calibrate_director.py` | How busy the screen is per sample match at 1x, 20x and 60x, and the clutter rules hold | Never more than 3 cues or 2 cards on screen; 23-57 cues a match at 1x |

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

The app needs two terminals (a first visit opens the profile picker; `/?team=POT&player=POT-11&mode=casual&lang=de&focus=xg` skips it and sets a profile for that tab only):

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

**Memory embeddings** (needs the Foundry values in `.env`; embeds only descriptions not already stored, so re-running costs nothing when nothing changed). The files record the deployment the vectors came from, and a changed `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` embeds everything again even if the cache is complete. A file from before the deployment was recorded is verified once instead of assumed: one text is embedded with the current deployment and compared with the stored vector, and only a match stamps the file. The three sample files were verified and stamped on 22 Oct (`text-embedding-3-small`, no vectors changed). Run it before the stored commentary whenever the moments or their descriptions change:

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

The times above are on the laptop's CPU. On Austin's GPU machine (AMD RX 9070 XT) detection takes 0.26 s a frame (2 min for the clip; 0.47 s with the fine-tuned model, which runs two models), and the steps are in [video/finetune/README.md](../video/finetune/README.md). For the fine-tuned detector, set `VIDEO_TAG=_ft` and pass `--weights path\to\checkpoint_best_total.pth` to both `detect.py` runs; its files go next to the baseline's as `117093-38min_ft.*`.

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
- Detector plan: RF-DETR (small) on a short clip (decided 21 Oct). **The video path stays** (decided 22 Oct). **Fine-tuned on Austin's own GPU machine on 22 Oct** (the Azure ML GPU quota request failed on a permissions error), and the fine-tuned model is the recommended one for people (the ball still comes from the COCO model); the run is still to be logged to Azure ML through MLflow; detection served on CPU in Azure Container Apps.
- **Austin's GPU machine** (`C:\Users\Austi\pitch-insights`): AMD Radeon RX 9070 XT (16 GB), Windows, so PyTorch is AMD's ROCm build (2.9.1+rocm7.2.1 from repo.radeon.com, Python 3.12.10 installed with winget), not CUDA. A process that runs the detector on frames decoded from the video hangs at exit after writing its output (`detect.py`, `eval_boxes.py`; not training), and the process can't be killed for a while; wait for the last line of output, then stop it. See [DESIGN.md, Fine-tuning](DESIGN.md#fine-tuning-run-22-oct-on-austins-gpu-machine).
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
- Video path: 5 frames a second (not 10); no shots (the ball is often missed in flight); the ball is found in under half the frames; team from shirt colour is about 93–95% right and track IDs switch (a player keeps one ID for 69% of frames); only about two-thirds of matched players get a team; the spectator and spare-ball filters need the whole clip, so they're offline only; team, tracker and event settings were chosen on the benchmark clip itself, before the tile-merge fix. The fine-tuned model has seen only this match and camera. The stored benchmarks were refreshed on the GPU after the tile-merge fix (22 Oct), but `log_mlflow.py` hasn't been re-run for them.
- Machine translation can get idioms wrong while keeping every name and number ("turn up the pressure" came out as "turn up the news" in Chinese), and the check can't catch that. The app labels translations as machine-made.

## Data on this machine

- **SoccerTrack v2, match 117093, first half**, downloaded 21 Oct from Hugging Face (`atomscott/soccertrack-v2`, CC BY 4.0) into `data/soccertrack/117093/` (git-ignored): the video `117093_panorama_1st_half.mp4` (3.35 GB), tracking ground truth `117093_1st.json` (2.71 GB) and events `117093_12_class_events.json` (0.5 MB). Sizes checked against the dataset's file list.
- The dataset is gated: downloads need Austin's Hugging Face read token as `HF_TOKEN` in `.env` (the terms are accepted on Austin's account).
- **Video path working files** in `data/video/117093/` (git-ignored, about 135 MB): the clip's ground truth (`gsr_clip.jsonl`), calibration pairs, raw detections for the clip (4 MB) and the calibration frames, and `preview.mp4` (126 MB).
- **CV environment** `video\.venv` (Python 3.12, separate from the backend's) and RF-DETR small's weights (368 MB) in `C:\Users\austin\.roboflow\models\rf-detr-small.pth`.
- **Fine-tuned detector weights** copied to this laptop on 22 Oct (git-ignored): `data/finetune/rfdetr-small-default/` with `checkpoint_best_total.pth` (the one to use, 121.6 MiB), `checkpoint_best_ema.pth`, `last_ema.pth` and the run's JSON files (a `.zip` of the run is beside it).
- **On Austin's GPU machine** (`C:\Users\Austi\pitch-insights`, all git-ignored): the same SoccerTrack files plus the small ones in `hf/` (MOT boxes, ball, `raw/`); the fine-tuning dataset `data/finetune/117093/` and the smoke one; the training runs in `data/finetune/runs/`: `rfdetr-small-default/` (the one to use: `checkpoint_best_total.pth`, 127 MB, and `train_summary.json`), `rfdetr-small-lr5e-5/` and `smoke/`; the step logs in `data/logs/`; and `video\.venv` with ROCm PyTorch.

## Waiting on Austin

1. Done 22 Oct: **the video path stays.** Fine-tuning ran on Austin's GPU machine instead of Azure ML (item 4).
2. Done 22 Oct: **MLflow logging to Azure ML.** `mlflow-skinny` 3.15.0 and `azureml-mlflow` 1.62.0.post6 are in `video\.venv`, `MLFLOW_TRACKING_URI` is in `.env` (placeholder in `.env.example`), and the benchmark is run `117093-38min-rfdetr-small-pretrained` in experiment `video-path-benchmark`. Every run of `video\log_mlflow.py` opens a browser window for Austin to sign in (no Azure CLI or token cache on this machine), so run it only with Austin there.
3. Done 22 Oct: **relicensed as Apache-2.0.**
4. Done 22 Oct: **fine-tuning on Austin's GPU machine** (AMD RX 9070 XT with ROCm PyTorch, not CUDA; Claude Code following [video/finetune/LLM_BRIEF.md](../video/finetune/LLM_BRIEF.md)). Smoke run passed; two training configurations (the defaults, then lr 5e-5), the defaults chosen on `valid`; box check on the test frames: precision at IoU 0.5 45% → 98% with recall 97% → 98%; on the clip, tracked-player precision 85% → 97% and recall 90% → 93%. Results and the refreshed baseline are in `main` (ILikePotatoesALot/pitch-insights#10; checked 22 Oct: the benchmark files match the figures in DESIGN.md). DESIGN.md's benchmark and fine-tuning sections are updated. The weights are copied to this laptop (22 Oct): `data\finetune\rfdetr-small-default\checkpoint_best_total.pth` (121.6 MiB) beside `checkpoint_best_ema.pth`, `last_ema.pth` and the run's JSON files; they aren't in git and haven't been loaded here yet (use `--weights` with that path). Still to do:
   - **Copy the weights to the Azure container** when deployment needs detection there (it can run on stored frames instead; the app only needs `117093-38min_ft.frames.jsonl`).
   - Done 23 Oct: **both runs logged to Azure ML** with `video\log_mlflow.py` (the baseline, then `VIDEO_TAG=_ft`), run by Austin on this laptop.
   - Decided 23 Oct: **the app's clip uses the fine-tuned frames** (`117093-38min_ft.frames.jsonl`).
5. **Optional, Azure ML GPU quota** (no longer needed: fine-tuning ran on Austin's GPU machine): the quota page (workspace `ML-pitch-insights`, East US 2, family NCASv3_T4, 0 cores) refused the request with "Forbidden". Austin confirmed Owner on the subscription on 23 Oct, so a retry may go through.

Settled 23 Oct, deploy prep: Austin is **Owner** on the subscription, and the resource providers `Microsoft.App`, `Microsoft.OperationalInsights`, `Microsoft.ContainerRegistry`, `Microsoft.DocumentDB`, `Microsoft.KeyVault` and `Microsoft.Web` are registered. No deploy resources are created yet (Cosmos DB's free tier is one account per subscription, so create it once, in the deploy step).

Settled 22 Oct: all four free-tier services (Content Safety, Translator, Application Insights, Speech) are in East US 2 and connect with the values in `.env`.

Settled 21 Oct: registration is confirmed; licensed footage (SoccerTrack v2) is fine for the video path, so no clarification question is needed; teammates are GitHub collaborators only; GPT-6 Luna quota was refused; the video path uses the pre-trained detector.

## Next steps, in order

| # | Step | Needs | Size |
|---|---|---|---|
| 1 | Done: **agents core**, merged in ILikePotatoesALot/pitch-insights#4 (21 Oct) | | |
| 2 | Done 22 Oct: **Foundry and AI services** (Memory agent and Content Safety, Translator, tracing and the groundedness evaluator, all merged; the latter in ILikePotatoesALot/pitch-insights#8) | | |
| 3 | Done 23 Oct, merged in ILikePotatoesALot/pitch-insights#12: **Overlay Director**, timed overlay cues (time, duration, priority, template, data) with clutter rules, in the app as Broadcast and Fan layouts | | |
| 4 | Done 23 Oct on `claude/personalise-95bc8a` (pull request open): **Personalise**, favourite club and player (spotlight on the pitch, pinned card, alerts), language, focus metric; the profile goes with the connection and the Director boosts, filters and adds alerts from it (deterministic code). Open: a Personalizer model call (a per-viewer full-time recap) is proposed in DESIGN.md, not built. The `speed_popup` template is still waiting for speeds from the video path | Steps 1–3 | |
| 5 | Decided 21 Oct: the video path uses **detection on a short clip**; kept (decided 22 Oct); fine-tuned on Austin's GPU machine (done 22 Oct, the fine-tuned model recommended) | | |
| 6 | **Live simulation mode** and the **Scenario Director** agent that steers a live match (logged so it replays exactly) | Step 1 | ~half a day |
| 7 | Done 22 Oct (in `main`): **SoccerTrack loader**, tiled detection on a 100 s clip, pitch positions, `frame` messages, events, benchmark. Next, if kept: a second clip to check the settings chosen on this one, better shirt colours for teams, a `match_meta` so the Interpreter can read video events, the clip in the app (with the fine-tuned frames, decided 23 Oct); check the fine-tuned model on a second clip; try SoccerTrack's own calibration (homography and intrinsics in `raw/`) against our polynomial; score the ball at event frames against SoccerTrack's reconstructed ball file | Austin's keep-or-cut call | ~half a day for the next steps |
| 8 | **Deploy to Azure**: backend on Container Apps, app on Static Web Apps, keys in Key Vault through a managed identity, Cosmos DB free tier for profiles and stored commentary. For profiles: write a `RemoteProfileStore` with the same three methods as `ProfileStore` (`frontend/src/profile.ts`: `load`, `save`, `clear`), keep it to the five profile choices, one document per anonymous viewer id (no name or email), partition key that id; the server needs nothing, it only ever sees the choices as query parameters | Steps 1–4 | ~half a day |
| 9 | **Demo video** (under 2 minutes; hero shot: same match, different viewers side by side: open `/?compare=1`, which shows a Potato fan watching casually in German beside a Carrot analyst in English; `a=` and `b=` take any profile link, e.g. `/?compare=1&match=thriller-CAR-BRO&speed=5`), README polish, make the repo public, submit | Everything above | 27 Oct at the latest |

**If time runs short, cut in this order:** speech audio, Event Hubs, the video path, live simulation mode and the Scenario Director, then 3D polish. Never cut the five pipeline stages, the stored commentary or the demo video.

## Submission checklist (27 Oct)

- [ ] Repo public, README explains setup, architecture and Microsoft technologies used
- [ ] Demo video under 2 minutes, public link, no copyrighted music or third-party logos
- [ ] Project description: what it does, which Microsoft and Azure technologies, what problem it solves
- [ ] A link judges can use to try it (Azure deployment), free until 10 Nov
- [x] Credits: RF-DETR (Roboflow), SoccerTrack v2, the ByteTrack idea (README and NOTICE)
- [x] License file matches the final choice (Apache-2.0, 22 Oct)
