"""What one viewer's replay connection has in common, whatever it replays (a synthetic match or a video clip).

    session = ViewerSession(ws, rep, mode)
    ...                                     # play(): send messages; `await session.tick()` between them,
    await session.send_all(session.director.offer(cues, session.show_now()))
    await session.finish()                  # the cues still on screen run their course, then the socket closes
    await run_until_first_done(play(), session.listen())

The Overlay Director works in screen seconds (a cue lasts as long on the screen at 60x as at 1x), one per
connection: a seek or a language change reconnects, so cues start afresh. `listen` only records what the browser
asks for; `tick` and `play` do the sending, so two tasks never write to the socket at once.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable

from fastapi import WebSocket, WebSocketDisconnect

from pitch_insights.director.cues import visible_to
from pitch_insights.director.scheduler import Director, ShowClock
from pitch_insights.generator.stream import Replay

CUE_TICK_S = 0.25  # how often the Director looks for cues that are over or can now start
MIN_SPEED, MAX_SPEED = 0.1, 600.0


def clamp_speed(speed: float) -> float:
    return max(MIN_SPEED, min(MAX_SPEED, speed))


class ViewerSession:
    def __init__(self, ws: WebSocket, rep: Replay, mode: str):
        self.ws, self.rep = ws, rep
        self.director, self.clock = Director(), ShowClock()
        # Whose screen the Director is keeping clean: what the browser last asked for, and what the Director has
        # been reconciled to.
        self.viewer = {"detail": mode, "applied": mode}

    def show_now(self) -> float:
        return self.clock.at(self.rep.now, self.rep.speed)

    async def listen(self):
        """Apply the browser's commands. Ends (with WebSocketDisconnect) when the browser goes away."""
        while True:
            try:
                msg = await self.ws.receive_json()
            except ValueError:
                continue  # not JSON: ignore it rather than stop listening
            if not isinstance(msg, dict):
                continue
            cmd = msg.get("cmd")
            if cmd == "speed":
                try:
                    value = clamp_speed(float(msg["value"]))
                except (KeyError, TypeError, ValueError):
                    continue
                self.show_now()  # the time so far passed at the old speed
                self.rep.set_speed(value)
            elif cmd == "pause":
                self.show_now()
                self.rep.pause()
            elif cmd == "resume":
                self.rep.resume()
            elif cmd == "detail" and msg.get("value") in ("casual", "analyst"):
                self.viewer["detail"] = msg["value"]

    async def send_all(self, messages: list[dict]):
        for msg in messages:
            await self.ws.send_json(msg)

    async def tick(self):
        """The Director's turn between events: a changed viewer mode first (cues that viewer would never see
        come down at once, and don't sit in the queue holding slots), then the passing of time."""
        v = self.viewer
        if v["applied"] != v["detail"]:
            v["applied"] = v["detail"]
            await self.send_all(self.director.withdraw(lambda c: not visible_to(c, v["applied"]), self.show_now()))
        await self.send_all(self.director.advance(self.show_now()))

    async def finish(self):
        """After the final message: the last cues get their turn and are taken down, then the socket closes."""
        while self.director.waiting or self.director.on_screen:
            await asyncio.sleep(CUE_TICK_S)
            await self.tick()
        await self.ws.close()


async def run_until_first_done(*coroutines: Awaitable) -> None:
    """Run them together: whichever finishes first (the replay ends, or the browser disconnects, even while
    paused) stops the others, so nothing is left running for a closed tab."""
    tasks = {asyncio.ensure_future(c) for c in coroutines}
    for task in tasks:  # a task can end after this one is cancelled; read its outcome so asyncio doesn't log it
        task.add_done_callback(lambda t: t.cancelled() or t.exception())
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        # Also when this handler is itself cancelled (the server shutting the connection down): no task may
        # outlive the connection, still sending to a closed socket.
        for task in tasks:
            task.cancel()
    if pending:
        # asyncio.wait, not gather: if this handler is cancelled while waiting, gather would raise the children's
        # CancelledError in place of the server's own, and anyio (Starlette's server side) then can't tell it's
        # its own cancellation and lets it escape the connection.
        await asyncio.wait(pending)
    for task in done:
        exc = task.exception()
        if exc and not isinstance(exc, (WebSocketDisconnect, RuntimeError)):
            raise exc
