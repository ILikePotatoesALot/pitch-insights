"""Replay server: streams a match to the browser on the match clock.

    uvicorn pitch_insights.server:app --port 8000

GET  /api/matches                list of demo matches in samples/
GET  /api/matches/{name}         that match's match_meta
WS   /ws/replay/{name}?speed=20&from=0

The WebSocket sends, in order:
  {"type": "meta", "meta": ..., "commentary": {...}}     commentary: who wrote the stored commentary
                                                        (model, prompt version, groundedness summary)
  {"type": "catchup", "moments": [...], "state": ..., "recent_events": [...]}
                                                        only when starting after kick-off; recent_events
                                                        (the last 3 minutes) let the pitch redraw at once
  then, as the match clock reaches them:
  {"type": "event", "event": ...}
  {"type": "moment", "moment": ...}                     with "commentary" when the agents wrote some
  {"type": "state", "state": ...}                       about once a second
  {"type": "end"}
The browser can send {"cmd": "speed", "value": 5}, {"cmd": "pause"} or {"cmd": "resume"}.
To seek, it reconnects with a different `from` minute.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from pitch_insights.agents.memory import memory_for
from pitch_insights.agents.prompts import input_hash
from pitch_insights.agents.store import load_commentary
from pitch_insights.explain.moments import MatchBrain
from pitch_insights.generator.io import read_match
from pitch_insights.generator.stream import Replay, match_seconds, start_seconds

SAMPLES = Path(os.getenv("PITCH_SAMPLES", Path(__file__).resolve().parents[2] / "samples"))
STATE_EVERY_S = 1.0  # wall-clock seconds between state messages
MIN_SPEED, MAX_SPEED = 0.1, 600.0


def clamp_speed(speed: float) -> float:
    return max(MIN_SPEED, min(MAX_SPEED, speed))

app = FastAPI(title="Pitch Insights replay server")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


def _match_path(name: str) -> Path:
    path = (SAMPLES / f"{name}.jsonl").resolve()
    if path.parent != SAMPLES.resolve() or not path.exists():
        raise HTTPException(404, f"no match called {name!r}")
    return path


@app.get("/api/matches")
def list_matches() -> list[dict]:
    out = []
    for path in sorted(SAMPLES.glob("*.jsonl")):
        with path.open(encoding="utf-8") as f:
            meta = json.loads(f.readline())
        out.append({"name": path.stem, "match_id": meta["match"]["id"],
                    "home": {k: meta["home"][k] for k in ("id", "name", "short_name", "colours")},
                    "away": {k: meta["away"][k] for k in ("id", "name", "short_name", "colours")}})
    return out


@app.get("/api/matches/{name}")
def get_match(name: str) -> dict:
    meta, _ = read_match(_match_path(name))
    return meta


def with_commentary(moment: dict, stored: dict, meta: dict) -> dict:
    """The moment plus its stored commentary, if the agents wrote some from these same facts.
    Commentary written for different facts (the file is older than the code) is left out."""
    rec = stored["moments"].get(moment["id"])
    if not rec or rec.get("input_hash") != input_hash(moment, meta):
        return moment
    return moment | {"commentary": rec}


def commentary_info(stored: dict) -> dict | None:
    """Who wrote the stored commentary, for the app's AI-generated label."""
    if not stored["moments"]:
        return None
    return {k: stored.get(k) for k in ("ai_generated", "provider", "model", "prompt_version", "summary")}


def state_message(brain: MatchBrain) -> dict:
    """The live state the app needs, kept small enough to send every second."""
    snap = brain.interp.snapshot(top_moments=3)
    players = []
    for pid, p in snap["players"].items():
        players.append({k: p[k] for k in ("player_id", "team_id", "name", "number", "position", "minutes",
                                           "on_pitch", "rating", "goals", "assists", "shots", "xg", "passes",
                                           "passes_complete", "key_passes", "tackles_won", "interceptions",
                                           "dribbles_won", "saves", "xt_added", "by_category", "key_moments")})
    return {k: snap[k] for k in ("clock", "period", "match_minute", "finished", "score", "win_probability",
                                  "teams", "patterns", "momentum_series")} | {"players": players}


@app.websocket("/ws/replay/{name}")
async def replay(ws: WebSocket, name: str, speed: float = 20.0):
    await ws.accept()
    try:
        path = _match_path(name)
        meta, events = read_match(path)
    except HTTPException as e:
        await ws.send_json({"type": "error", "message": e.detail})
        await ws.close()
        return
    try:  # "from" is a Python keyword, so read it directly
        from_minute = max(0.0, float(ws.query_params.get("from", 0)))
    except ValueError:
        from_minute = 0.0
    brain = MatchBrain(meta, memory=memory_for(path, meta))  # stored vectors: no network
    stored = load_commentary(path)
    await ws.send_json({"type": "meta", "meta": meta, "commentary": commentary_info(stored)})

    start = start_seconds(events, from_minute) if from_minute > 0 else 0.0
    times = match_seconds(events)
    first = next((i for i, t in enumerate(times) if t >= start), len(events))
    for ev in events[:first]:
        brain.update(ev)
    if first:
        recent = [ev for ev, t in zip(events[:first], times[:first])
                  if t >= times[first - 1] - 180 or (ev["type"] == "match_state" and ev["state"] == "half_time")]
        await ws.send_json({"type": "catchup", "moments": [with_commentary(m, stored, meta) for m in brain.moments],
                            "state": state_message(brain), "recent_events": recent})

    rep = Replay(events, speed=clamp_speed(speed), start_at=times[first] if first < len(events) else start, poll=0.05)

    async def listen():
        """Apply the browser's commands. Ends (with WebSocketDisconnect) when the browser goes away."""
        while True:
            try:
                msg = await ws.receive_json()
            except ValueError:
                continue  # not JSON: ignore it rather than stop listening
            if not isinstance(msg, dict):
                continue
            cmd = msg.get("cmd")
            if cmd == "speed":
                try:
                    rep.set_speed(clamp_speed(float(msg["value"])))
                except (KeyError, TypeError, ValueError):
                    continue
            elif cmd == "pause":
                rep.pause()
            elif cmd == "resume":
                rep.resume()

    async def play():
        loop = asyncio.get_running_loop()
        last_state = 0.0
        async for ev in rep:
            out = brain.update(ev)
            await ws.send_json({"type": "event", "event": ev})
            for m in out["moments"]:
                await ws.send_json({"type": "moment", "moment": with_commentary(m, stored, meta)})
            if loop.time() - last_state >= STATE_EVERY_S or ev["type"] in ("shot", "match_state") or out["moments"]:
                await ws.send_json({"type": "state", "state": state_message(brain)})
                last_state = loop.time()
        await ws.send_json({"type": "state", "state": state_message(brain)})
        await ws.send_json({"type": "end"})

    # Run both together: whichever finishes first (the match ends, or the browser disconnects,
    # even while paused) stops the other, so nothing is left running for a closed tab.
    tasks = {asyncio.create_task(play()), asyncio.create_task(listen())}
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    for task in done:
        exc = task.exception()
        if exc and not isinstance(exc, (WebSocketDisconnect, RuntimeError)):
            raise exc
