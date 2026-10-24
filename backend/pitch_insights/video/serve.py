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

from fastapi import WebSocket, WebSocketDisconnect

from pitch_insights.agents.translate import LANGUAGES
from pitch_insights.director import parse_profile, visible_to
from pitch_insights.director.session import CUE_TICK_S, ViewerSession, clamp_speed, run_until_first_done
from pitch_insights.generator.stream import Replay
from pitch_insights.video.replay import PHRASES, Clip, clip_meta, credibility, cue_for_event, describe

STALE_FRAMES = 1.5  # a frame older than this many frame intervals (of screen time) is skipped, not sent


def frame_is_stale(age: float, frame_dt: float, speed: float) -> bool:
    """Whether a frame due `age` clip seconds ago is too late to show: a fast replay that fell behind skips it."""
    return age > STALE_FRAMES * frame_dt * speed


async def replay_clip(ws: WebSocket, clip: Clip, speed: float) -> None:
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
    session = ViewerSession(ws, rep, profile.mode)

    async def play():
        while True:
            try:
                item = await asyncio.wait_for(rep.__anext__(), CUE_TICK_S)
            except asyncio.TimeoutError:
                await session.tick()
                continue
            except StopAsyncIteration:
                break
            if "frame" in item:
                if not frame_is_stale(rep.now - item["t"], clip.frame_dt, rep.speed):
                    await ws.send_json(item["frame"])
                await session.tick()
                continue
            ev = item["event"]
            await ws.send_json({"type": "event", **told(ev)})
            cue = cue_for_event(ev, lang)
            await session.tick()  # mode changes and expiries first, so the new cue meets the screen as it is
            if visible_to(cue, session.viewer["detail"]):
                await session.send_all(session.director.offer([cue], session.show_now()))
        await ws.send_json({"type": "end"})
        await session.finish()

    await run_until_first_done(play(), session.listen())
