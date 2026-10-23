"""Stream a tracked video clip to the app on the replay clock (the video counterpart of the match replay).

    ws /ws/replay/117093-38min_ft?speed=1&at=30&lang=de&mode=casual

The messages, in order (the frame format is DESIGN.md's Video path; the rest follow the match replay's):

  {"type": "meta", "kind": "video", "meta": ..., "clip": {...}, "commentary": null, "languages": {...},
                  "lang": "de", "profile": {...}}       `clip` is the credibility panel's content (`credibility`)
  {"type": "catchup", "events": [{"event": ..., "text": ...}]}   only when starting after the clip's first second
  then, as the replay clock reaches them:
  {"type": "frame", ...}                  positions of everyone at one moment (schema 1.1), 5 a second at 1x; a
                                          frame that is already out of date (a fast replay) is skipped, not queued
  {"type": "event", "event": ..., "text": ...}     a detected pass, carry or interception; `text` in the viewer's language
  {"type": "cue", "cue": ...} / {"type": "cue_end", ...}   lower-thirds for events, from the Overlay Director
  {"type": "end"}

Times are seconds into the clip: `at=30` starts 30 s in (38:30 on the match clock), and `from` is the same in minutes.
Frames keep their own `t` (seconds since the half started), so the app can show the match clock. The browser can send
{"cmd": "speed", "value": 2}, {"cmd": "pause"}, {"cmd": "resume"} and {"cmd": "detail", "value": "casual"}.

No AI commentary and no model call: the words come from `describe`, the cues from deterministic code.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable

from fastapi import WebSocket, WebSocketDisconnect

from pitch_insights.agents.translate import LANGUAGES
from pitch_insights.director import Director, ShowClock, parse_profile, visible_to
from pitch_insights.generator.stream import Replay
from pitch_insights.video.replay import PHRASES, Clip, clip_meta, credibility, cue_for_event, describe

CUE_TICK_S = 0.25  # how often the Director looks for cues that are over or can now start
STALE_FRAMES = 1.5  # a frame older than this many frame intervals (of screen time) is skipped, not sent


def frame_is_stale(age: float, frame_dt: float, speed: float) -> bool:
    """Whether a frame due `age` clip seconds ago is too late to show: a fast replay that fell behind skips it."""
    return age > STALE_FRAMES * frame_dt * speed


async def replay_clip(ws: WebSocket, clip: Clip, speed: float, clamp_speed: Callable[[float], float]) -> None:
    """Run one viewer's replay of `clip` until it ends or the browser goes away. The socket is already accepted."""
    params = ws.query_params
    meta = clip_meta(clip)
    languages = {"en": "English"} | {code: name for code, name in LANGUAGES.items() if code in PHRASES}
    lang = params.get("lang", "en")
    lang = lang if lang in languages else "en"
    profile = parse_profile(params, meta)  # no club or player in a clip, so only the mode applies
    try:
        await ws.send_json({"type": "meta", "kind": "video", "meta": meta, "clip": credibility(clip), "commentary": None,
                            "languages": languages, "lang": lang, "profile": profile.public()})
    except (WebSocketDisconnect, RuntimeError):
        return  # the browser went away before the first message: nothing to stop

    try:  # seconds into the clip; `from` (minutes) is the coarser way to say the same
        at = float(params["at"]) if "at" in params else 60 * max(0.0, float(params.get("from", 0)))
    except ValueError:
        at = 0.0
    start = min(max(0.0, at), clip.duration) if math.isfinite(at) else 0.0

    # One timeline of frames and events, in clip seconds. A frame comes before an event at the same moment.
    timeline = ([{"t": f["t"] - clip.start, "period": 1, "frame": f} for f in clip.frames]
                + [{"t": e["t"] - clip.start, "period": 1, "event": e} for e in clip.events])
    timeline.sort(key=lambda item: (item["t"], "event" in item))

    def told(ev: dict) -> dict:
        return {"event": ev, "text": describe(ev, lang)[0]}

    before = [ev for ev in clip.events if ev["t"] - clip.start < start]
    if start > 0:
        try:
            await ws.send_json({"type": "catchup", "events": [told(ev) for ev in before]})
        except (WebSocketDisconnect, RuntimeError):
            return

    rep = Replay(timeline, speed=clamp_speed(speed), start_at=start, poll=0.05)
    director, clock = Director(), ShowClock()
    viewer = {"detail": profile.mode, "applied": profile.mode}

    def show_now() -> float:
        return clock.at(rep.now, rep.speed)

    async def listen():
        while True:
            try:
                msg = await ws.receive_json()
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            cmd = msg.get("cmd")
            if cmd == "speed":
                try:
                    value = clamp_speed(float(msg["value"]))
                except (KeyError, TypeError, ValueError):
                    continue
                show_now()
                rep.set_speed(value)
            elif cmd == "pause":
                show_now()
                rep.pause()
            elif cmd == "resume":
                rep.resume()
            elif cmd == "detail" and msg.get("value") in ("casual", "analyst"):
                viewer["detail"] = msg["value"]

    async def send_all(messages: list[dict]):
        for msg in messages:
            await ws.send_json(msg)

    async def tick():
        if viewer["applied"] != viewer["detail"]:
            viewer["applied"] = viewer["detail"]
            await send_all(director.withdraw(lambda c: not visible_to(c, viewer["applied"]), show_now()))
        await send_all(director.advance(show_now()))

    async def play():
        while True:
            try:
                item = await asyncio.wait_for(rep.__anext__(), CUE_TICK_S)
            except asyncio.TimeoutError:
                await tick()
                continue
            except StopAsyncIteration:
                break
            if "frame" in item:
                if not frame_is_stale(rep.now - item["t"], clip.frame_dt, rep.speed):
                    await ws.send_json(item["frame"])
                await tick()
                continue
            ev = item["event"]
            await ws.send_json({"type": "event", **told(ev)})
            cue = cue_for_event(ev, lang)
            if visible_to(cue, viewer["detail"]):
                await tick()  # mode changes and expiries first, so the new cue meets the screen as it is
                await send_all(director.offer([cue], show_now()))
            else:
                await tick()
        await ws.send_json({"type": "end"})
        while director.waiting or director.on_screen:  # the last cues get their turn and are taken down
            await asyncio.sleep(CUE_TICK_S)
            await tick()
        await ws.close()

    # Whichever finishes first (the clip ends, or the browser disconnects, even while paused) stops the other.
    tasks = {asyncio.create_task(play()), asyncio.create_task(listen())}
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    for task in done:
        exc = task.exception()
        if exc and not isinstance(exc, (WebSocketDisconnect, RuntimeError)):
            raise exc
