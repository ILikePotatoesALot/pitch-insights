# Plan

Agreed 20 Oct 2026. Submission deadline: 27 Oct 2026, 11:59 pm Pacific Time.

## Concept

A live "match brain": specialist agents turn football events into scored, evidence-backed moments, render them on a Three.js 3D pitch with broadcast-style overlays, and personalise them per viewer.

- Demo hero: **same match, different viewers**, side by side.
- Category prize to aim for: Multi-Agent, with Foundry as a backup.

## Ground rules

- New project, started 20 Oct. The old CV project is reference only; no code copied.
- Fictional clubs and players. No Premier League names, logos or other trademarks.
- Only footage we have rights to (Pexels or Pixabay clips, or self-filmed).
- Credit Roboflow (CC BY 4.0). Repo licensed AGPL-3.0 because of Ultralytics YOLO.

## 1. Ingest (two sources, one event format)

- **Synthetic generator** (main feed): possession chains, player profiles, pass difficulty, xG for shots, scripted storylines, a fake season history for milestones, and seeds so matches replay exactly. A check script compares output with real match averages.
- **Video path** (core; keep-or-cut decision on day 4): Roboflow pre-trained football model, ByteTrack, team colours, homography, then a Video Ingest agent writing the same event format. Clips are processed ahead of time and replayed at match speed. Supplies real speed and distance.
- Stream over WebSocket or Server-Sent Events; Azure Event Hubs optional.
- Two ways to run a match: **replay** (default: generated up front, released on the match clock, with seek) and **live simulation** (generated step by step, with mid-match interventions from a Scenario Director agent; interventions are logged so the match can be replayed exactly).

## 2. Interpret (code first)

- Stats: passes, accuracy, xG, possession, speed, distance.
- Patterns: momentum, pressure index, chaos score, tempo.
- Live player ratings: start at 6.0, event-weighted, weighted by position, damped for playing time, with a breakdown for every change.
- Individual player stats: on the ball, attacking, defending, physical.
- The LLM only names and describes patterns.

## 3. Explain

- Code scores each moment by win-probability shift, deviation from normal and pattern breaks.
- Key moments get an evidence pack; the LLM explains only what is in it.
- A "Why?" button shows the evidence behind any moment or rating.

## 4. Render (Vite + React + Three.js)

- Backend outputs timed overlay cues as JSON (time, duration, priority, template, data).
- Three.js pitch surface shaped by live momentum, with spikes for shots. Own design.
- React overlays: lower-thirds, stat cards, player tags, speed popups, rating alerts.
- An Overlay Director agent prevents clutter.

## 5. Personalise (same renderer; the viewer profile decides)

- Profile: analyst or casual, club, favourite player, language, focus metric.
- Filters cues, rewrites tone and language, player-focus mode with a spotlight, favourite-player card with live rating and sparkline.
- Broadcast mode: overlays only. Fan mode: adds a side panel.

## Microsoft stack

- Foundry: GPT models and agents.
- Agent Framework agents: Ingest, Video Ingest, Stats/Pattern, Moment Scorer, Explainer, Narrator, Personalizer, Overlay Director.
- Azure Container Apps (backend, CV service), Static Web Apps (frontend).
- Optional: Event Hubs, AI Speech.

## Timeline

| Day | Date | Austin | Claude |
|---|---|---|---|
| 1 | 20 Oct | Register, Azure account, Foundry model | Repo skeleton, event format, generator v1 |
| 2 | 21 Oct | Pick footage clips | Stats, patterns, ratings; run detector on clips |
| 3 | 22 Oct | Check generated matches feel real | Tracking, homography, video-to-events |
| 4 | 23 Oct | Decide on the video path | Agents: scorer, explainer, narrator; live simulation mode |
| 5 | 24 Oct | Personas, test explanations | Vite app and Three.js pitch; Scenario Director agent steering live matches |
| 6 | 25 Oct | Test the UI | Overlays, personalizer, multi-language |
| 7 | 26 Oct | Demo script | Deploy to Azure, README |
| 8 | 27 Oct | Record video, submit | Final fixes, check repo is public |

## Cut first if behind

Speech audio, then Event Hubs, then live simulation mode (replay still covers the demo), then 3D polish. Never cut the five stages or the demo video.
