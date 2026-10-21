"""Replay server: streams a match to the browser on the match clock.

    uvicorn pitch_insights.server:app --port 8000

GET  /api/matches                list of demo matches in samples/
GET  /api/matches/{name}         that match's match_meta
WS   /ws/replay/{name}?speed=20&from=0

The WebSocket sends, in order:
  {"type": "meta", "meta": ...}
  {"type": "catchup", "moments": [...], "state": ..., "recent_events": [...]}
                                                        only when starting after kick-off; recent_events
                                                        (the last 3 minutes) let the pitch redraw at once
  then, as the match clock reaches them:
  {"type": "event", "event": ...}
  {"type": "moment", "moment": ...}
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

from pitch_insights.explain.moments import MatchBrain
from pitch_insights.generator.io import read_match
from pitch_insights.generator.stream import Replay, match_seconds, start_seconds

SAMPLES = Path(os.getenv("PITCH_SAMPLES", Path(__file__).resolve().parents[2] / "samples"))
STATE_EVERY_S = 1.0  # wall-clock seconds between state messages

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
        meta, events = read_match(_match_path(name))
    except HTTPException as e:
        await ws.send_json({"type": "error", "message": e.detail})
        await ws.close()
        return
    from_minute = float(ws.query_params.get("from", 0))  # "from" is a Python keyword, so read it directly
    brain = MatchBrain(meta)
    await ws.send_json({"type": "meta", "meta": meta})

    start = start_seconds(events, from_minute) if from_minute > 0 else 0.0
    times = match_seconds(events)
    first = next((i for i, t in enumerate(times) if t >= start), len(events))
    for ev in events[:first]:
        brain.update(ev)
    if first:
        recent = [ev for ev, t in zip(events[:first], times[:first])
                  if t >= times[first - 1] - 180 or (ev["type"] == "match_state" and ev["state"] == "half_time")]
        await ws.send_json({"type": "catchup", "moments": brain.moments, "state": state_message(brain),
                            "recent_events": recent})

    rep = Replay(events, speed=speed, start_at=times[first] if first < len(events) else start, poll=0.05)

    async def listen():
        while True:
            msg = await ws.receive_json()
            cmd = msg.get("cmd")
            if cmd == "speed":
                rep.set_speed(max(0.1, min(600.0, float(msg["value"]))))
            elif cmd == "pause":
                rep.pause()
            elif cmd == "resume":
                rep.resume()

    listener = asyncio.create_task(listen())
    loop = asyncio.get_running_loop()
    last_state = 0.0
    try:
        async for ev in rep:
            out = brain.update(ev)
            await ws.send_json({"type": "event", "event": ev})
            for m in out["moments"]:
                await ws.send_json({"type": "moment", "moment": m})
            if loop.time() - last_state >= STATE_EVERY_S or ev["type"] in ("shot", "match_state") or out["moments"]:
                await ws.send_json({"type": "state", "state": state_message(brain)})
                last_state = loop.time()
        await ws.send_json({"type": "state", "state": state_message(brain)})
        await ws.send_json({"type": "end"})
    except WebSocketDisconnect:
        pass
    finally:
        listener.cancel()
