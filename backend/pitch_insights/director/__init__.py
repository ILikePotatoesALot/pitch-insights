"""The Overlay Director: timed overlay cues for the app, with the clutter rules that keep the screen clean.

    builder = CueBuilder(meta)
    director = Director()
    messages = director.offer(builder.for_moment(moment, state), now)   # {"type": "cue" | "cue_end", ...}
    messages = director.advance(now)

Deterministic code, not a model call: see docs/DESIGN.md, Overlay Director.
"""

from pitch_insights.director.cues import CARD_TEMPLATES, TEMPLATES, CueBuilder
from pitch_insights.director.scheduler import DEFAULT_RULES, Director, Rules, ShowClock

__all__ = ["CARD_TEMPLATES", "TEMPLATES", "CueBuilder", "DEFAULT_RULES", "Director", "Rules", "ShowClock"]
