"""The cue sheet of a whole match, worked out offline at a fixed replay speed.

The server runs the Director against the wall clock as the replay plays. This runs the same Director
against the match clock alone, with the ticks the server makes, so one match at one speed always gives the
same sheet: for tests, for calibration, and for anyone who wants to read what a viewer would see.

    sheet = cue_sheet(meta, events, pace=20)   # [{"show": 12.5, "message": {"type": "cue", ...}}, ...]
"""

from __future__ import annotations

from collections.abc import Callable

from pitch_insights.director.cues import CueBuilder, visible_to
from pitch_insights.director.personalise import Personaliser, Profile
from pitch_insights.director.scheduler import Director, Rules, DEFAULT_RULES
from pitch_insights.explain.moments import MatchBrain
from pitch_insights.generator.stream import match_seconds

TICK_S = 0.25  # the server's CUE_TICK_S


def cue_sheet(meta: dict, events: list[dict], pace: float = 20.0, rules: Rules = DEFAULT_RULES,
              moment_view: Callable[[dict], dict] = lambda m: m, detail: str = "analyst",
              profile: Profile | None = None) -> list[dict]:
    """Every message the Director would send for this match played at `pace` times real time.

    `moment_view` turns a moment into what a viewer sees (stored commentary, a language); by default the
    plain moment. `detail` is the viewer's mode: "casual" leaves out the cues made for analysts. `profile` is
    the viewer's favourites and focus metric (see `personalise`); without one the sheet is the neutral one."""
    from pitch_insights.server import state_message  # here, so the server can import the director

    brain, builder, director = MatchBrain(meta), CueBuilder(meta), Director(rules)
    detail = profile.mode if profile else detail  # one source for the viewer's mode
    personaliser = Personaliser(profile or Profile(mode=detail), meta, director_rules=rules)
    sheet: list[dict] = []

    def log(show: float, messages: list[dict]):
        sheet.extend({"show": round(show, 2), "message": m} for m in messages)

    last_tick = 0.0
    for ev, t in zip(events, match_seconds(events)):
        show = t / pace
        while last_tick + TICK_S <= show:  # what the server's ticks would have done between events
            last_tick += TICK_S
            log(last_tick, director.advance(last_tick))
        out = brain.update(ev)
        moments = [moment_view(m) for m in out["moments"]]
        state = state_message(brain) if moments else None
        cues = [c for c in personaliser.cues(builder, ev, moments, state, lambda: state_message(brain), t)
                if visible_to(c, detail)]
        if cues:
            log(show, director.offer(cues, show))
        else:
            log(show, director.advance(show))
    while director.waiting or director.on_screen:  # the final whistle: the last cues get their turn and go
        last_tick += TICK_S
        log(last_tick, director.advance(last_tick))
    return sheet
