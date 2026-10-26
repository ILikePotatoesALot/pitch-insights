"""Measured positional evidence for the short simulation. No model calls here."""

from __future__ import annotations

import functools
import math
import statistics

from pitch_insights.explain.moments import MatchBrain


def measure_frame(frame, meta):
    teams = {}
    ball = frame.get("ball")
    for block in (meta["home"], meta["away"]):
        roster = {p["id"]: p for p in block["players"]}
        players = [p for p in frame["players"] if p["team_id"] == block["id"] and roster[p["id"]]["position"] != "GK"]
        xs, ys = [p["x"] for p in players], [p["y"] for p in players]
        defenders = [p["x"] for p in players if roster[p["id"]]["position"] in ("CB", "FB")]
        bx, by = (ball["x"], ball["y"]) if ball else (None, None)
        if ball and block["id"] != frame["ref_team_id"]:
            bx, by = 105 - bx, 68 - by
        teams[block["id"]] = dict(width=round(max(ys) - min(ys)), depth=round(max(xs) - min(xs)),
            defensive_line=round(statistics.median(defenders)),
            near_ball=sum(math.hypot(p["x"] - bx, p["y"] - by) <= 5 for p in players) if ball else 0)
    return dict(teams=teams, phase=frame.get("phase", "open_play"), possession_team_id=frame.get("possession_team_id"))


def shape_facts(frame, meta):
    analysis = frame.get("analysis") or measure_frame(frame, meta)
    facts = []
    for team in (meta["home"], meta["away"]):
        data = analysis["teams"][team["id"]]
        facts.extend([
            dict(kind="team_shape", value=data, text=f"{team['short_name']}'s outfield players span {data['width']} m wide and {data['depth']} m deep."),
            dict(kind="defensive_line", value=data["defensive_line"], text=f"{team['short_name']}'s defenders have a median position {data['defensive_line']} m from their own goal line."),
            dict(kind="near_ball", value=data["near_ball"], text=f"{team['short_name']} has {data['near_ball']} outfield players within 5 m of the ball."),
        ])
    return facts


def build_moments(meta, events, frames):
    brain = MatchBrain(meta)
    for event in events:
        brain.update(event)
    moments = []
    for moment in brain.moments:
        if moment["type"].startswith("rating"):
            continue
        m = dict(moment)
        m["source"] = "simulation"
        m.pop("win_probability", None)
        m["facts"] = [f for f in moment["facts"] if f["kind"] != "win_probability"
                      and not f["kind"].startswith(("season_", "career_"))]
        t = moment["match_time"]
        frame = frames[min(len(frames) - 1, int(t * 5))]
        m["facts"] += shape_facts(frame, meta)
        m["clock"] = f"{int(t) // 60}:{int(t) % 60:02d}"
        m["headline"] = m["headline"].replace("Full-time:", "Exhibition ends:")
        moments.append(m)
    for frame in frames:
        t = frame["t"]
        if not t or t >= frames[-1]["t"] or t % 30 or frame.get("phase") != "open_play":
            continue
        team_id = frame["possession_team_id"]
        team = meta["home"] if meta["home"]["id"] == team_id else meta["away"]
        facts = shape_facts(frame, meta)
        headline = f"{team['short_name']}'s team shape"
        player = None
        earlier = frames[max(0, int(t * 5) - 20)]
        old = {p["id"]: p for p in earlier["players"]}
        candidates = [p for p in frame["players"] if p["team_id"] == team_id
                      and p["x"] - old[p["id"]]["x"] >= 8
                      and all(f.get("carrier_id") != p["id"] for f in frames[int(earlier["t"] * 5):int(t * 5) + 1])]
        if candidates:
            run = max(candidates, key=lambda p: p["x"] - old[p["id"]]["x"])
            player = next(p for p in team["players"] if p["id"] == run["id"])
            advance = round(run["x"] - old[run["id"]]["x"])
            facts.insert(0, dict(kind="off_ball_run", player_id=run["id"], value=advance,
                text=f"{player['name']} advances {advance} m towards the opposing goal over 4 seconds without possessing the ball."))
            headline = f"{player['name']} moves forward off the ball"
        moments.append(dict(id=f"S-{int(t)}", seq=0, clock=f"{int(t) // 60}:{int(t) % 60:02d}", minute=int(t // 60), period=1,
            match_time=t, type="off_ball_run" if player else "team_shape", team_id=team_id,
            player_id=player["id"] if player else None, player_name=player["name"] if player else None,
            importance=0.4, rank=0.4, tier="notable", headline=headline, facts=facts, signals=[], score={}, source="simulation"))
    return sorted(moments, key=lambda m: m["match_time"])


@functools.lru_cache(maxsize=1)
def prototype_moments():
    from pitch_insights.generator.continuous import prototype
    return build_moments(*prototype())
