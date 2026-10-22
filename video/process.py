"""From stored detections to `frame` and `event` messages, then the benchmark.

Fast (seconds), so it can be re-run while tuning; the slow detection is in
detect.py. Reads data/video/117093/detections.jsonl and the calibration in
samples/, writes the frames, events and benchmark to samples/.

    video\\.venv\\Scripts\\python video\\process.py
"""

from __future__ import annotations

import json
import math
import time
from collections import Counter, defaultdict
from statistics import mean, median

import cv2
import numpy as np

import clip
from calibration import Calibration
from detector import BALL, PERSON
from pitch_insights.events.schema import Frame, display_clock
from pitch_insights.video.bench import DetectionScore, event_recall
from pitch_insights.video.events import Moment, PlayerAt, derive, to_messages
from pitch_insights.video.soccertrack import load_bas, to_our_frame
from pitch_insights.video.track import PitchTracker, smoothed_speed, spectator_tracks

MATCH_RADIUS_M = 3.0
TEAMS = {"left": "L", "right": "R"}
REF_TEAM = "L"  # the ball and teamless players use the left team's attacking frame (it attacks +x)
COLOUR_GROUPS = 4  # two teams, plus keepers and officials (3 left the referee in a team)
BALL_REACQUIRE_SCORE = 0.4
BALL_MAX_SPEED = 30.0  # m/s, for following the ball from frame to frame
BALL_LOST_AFTER_S = 2.0


def load_rows(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return sorted((json.loads(line) for line in f if line.strip()), key=lambda r: r["frame"])


def bottom_middle(box) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2, box[3])


def on_pitch(cal: Calibration, dets: list[dict]) -> list[dict]:
    if not dets:
        return []
    xy, keep = cal.on_pitch([bottom_middle(d["box"]) for d in dets])
    return [dict(d, xy=(float(p[0]), float(p[1]))) for d, p, k in zip(dets, xy, keep) if k]


def assign_teams(colours_by_track: dict[int, list[list[float]]], x_by_track: dict[int, list[float]]) -> dict[int, str | None]:
    """Shirt-colour clustering (k-means over every tracked detection's shirt colour).

    The two groups seen most are the teams; the rest (keepers, officials, odd
    crops) get no team. The team defending the left goal
    sits deeper on average, so the group with the lower mean x is Left. Only
    colour and position are used; SoccerTrack's team labels are for scoring.
    """
    samples, owners = [], []
    for tid, cols in colours_by_track.items():
        for c in cols:
            samples.append(c)
            owners.append(tid)
    data = np.array(samples, dtype=np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.1)
    cv2.setRNGSeed(7)
    _, labels, _ = cv2.kmeans(data, COLOUR_GROUPS, None, criteria, 5, cv2.KMEANS_PP_CENTERS)
    votes: dict[int, Counter] = defaultdict(Counter)
    for tid, lab in zip(owners, labels.ravel()):
        votes[tid][int(lab)] += 1
    track_label = {tid: v.most_common(1)[0][0] for tid, v in votes.items()}
    weight = Counter()
    for tid, lab in track_label.items():
        weight[lab] += len(colours_by_track[tid])
    teams = [lab for lab, _ in weight.most_common(2)]
    mean_x = {lab: mean(x for tid, l in track_label.items() if l == lab for x in x_by_track[tid]) for lab in teams}
    left = min(teams, key=lambda lab: mean_x[lab])
    side = {left: "L", next(lab for lab in teams if lab != left): "R"}
    return {tid: side.get(lab) for tid, lab in track_label.items()}


def follow_ball(per_frame: list[tuple[float, list[dict]]]) -> list[dict | None]:
    """One ball per frame: the candidate nearest where the ball was, else a confident new one."""
    out: list[dict | None] = []
    last, last_t = None, None
    for t, cands in per_frame:
        if last is not None and t - last_t > BALL_LOST_AFTER_S:
            last = None
        pick = None
        if last is not None:
            reach = 3.0 + BALL_MAX_SPEED * (t - last_t)
            near = [c for c in cands if math.dist(c["xy"], last) <= reach]
            if near:
                pick = max(near, key=lambda c: c["score"])
        if pick is None:
            strong = [c for c in cands if c["score"] >= BALL_REACQUIRE_SCORE]
            if strong:
                pick = max(strong, key=lambda c: c["score"])
        if pick is not None:
            last, last_t = pick["xy"], t
        out.append(pick)
    return out


def rounded(v):
    """Floats to 4 decimals throughout, for a readable benchmark file."""
    if isinstance(v, float):
        return round(v, 4)
    if isinstance(v, dict):
        return {k: rounded(x) for k, x in v.items()}
    if isinstance(v, list):
        return [rounded(x) for x in v]
    return v


def clamp(x: float, y: float) -> tuple[float, float]:
    return min(max(x, 0.0), 105.0), min(max(y, 0.0), 68.0)


def main() -> None:
    started = time.perf_counter()
    cal = Calibration.load(clip.CALIBRATION)
    rows = load_rows(clip.DETECTIONS)
    gt = {r["frame"]: r["objects"] for r in load_rows(clip.GSR_CLIP)}
    rows = [r for r in rows if r["frame"] in gt]
    print(f"{len(rows)} frames with detections")

    tracker = PitchTracker()
    per_frame = []  # (frame, t, people, balls)
    raw_score = DetectionScore(MATCH_RADIUS_M)
    for r in rows:
        t = clip.frame_t(r["frame"])
        people = on_pitch(cal, [d for d in r["detections"] if d["class_id"] == PERSON and d["score"] >= clip.PERSON_MIN_SCORE])
        balls = on_pitch(cal, [d for d in r["detections"] if d["class_id"] == BALL and d["score"] >= clip.BALL_MIN_SCORE])
        raw_score.add_frame([p["xy"] for p in people], [(o["x_st"], o["y_st"]) for o in gt[r["frame"]]])
        ids = tracker.update(t, [p["xy"] for p in people], [p["score"] for p in people])
        for p, tid in zip(people, ids):
            p["track"] = tid
        per_frame.append((r["frame"], t, [p for p in people if p["track"] is not None], balls))

    history = defaultdict(list)
    for _, t, people, _ in per_frame:
        for p in people:
            history[p["track"]].append((t, p["xy"]))
    spectators = spectator_tracks(history)
    per_frame = [(fr, t, [p for p in people if p["track"] not in spectators], balls)
                 for fr, t, people, balls in per_frame]
    history = {tid: h for tid, h in history.items() if tid not in spectators}

    colours, xs = defaultdict(list), defaultdict(list)
    for _, t, people, _ in per_frame:
        for p in people:
            if p["colour"]:
                colours[p["track"]].append(p["colour"])
            xs[p["track"]].append(p["xy"][0])
    team_of = assign_teams(colours, xs)
    plus = {"L": True, "R": False}
    ball_of = follow_ball([(t, balls) for _, t, _, balls in per_frame])

    frames_out, moments = [], []
    out_score = DetectionScore(MATCH_RADIUS_M)
    teamed_score = DetectionScore(MATCH_RADIUS_M)  # only people given a team: referees mostly drop out
    team_right = team_total = 0
    gt_ids: dict[int, set[int]] = defaultdict(set)
    for (frame, t, people, _), ball in zip(per_frame, ball_of):
        players, at = [], []
        for p in people:
            team = team_of.get(p["track"])
            x, y = clamp(*to_our_frame(*p["xy"], plus[team or REF_TEAM]))
            sp = smoothed_speed(history[p["track"]], t)
            players.append({
                "id": f"{team or 'X'}-t{p['track']}", "team_id": team, "x": round(x, 1), "y": round(y, 1),
                "speed": round(sp, 1) if sp is not None and sp <= 12 else None, "confidence": round(p["score"], 2),
            })
            if team:
                at.append(PlayerAt(f"{team}-t{p['track']}", team, p["xy"]))
        ball_msg = None
        if ball:
            bx, by = clamp(*to_our_frame(*ball["xy"], True))
            ball_msg = {"x": round(bx, 1), "y": round(by, 1), "confidence": round(ball["score"], 2)}
        clock, _ = display_clock(1, t)
        # Every field kept, nulls included: `team_id` and `ball` are null by design.
        frames_out.append(Frame.model_validate({
            "match_id": clip.MATCH_ID, "source": "video", "period": 1, "t": round(t, 2), "clock": clock,
            "ref_team_id": REF_TEAM, "players": players, "ball": ball_msg,
        }).model_dump(mode="json", by_alias=True))
        moments.append(Moment(t, ball["xy"] if ball else None, ball["score"] if ball else 0.0, tuple(at)))

        truth = gt[frame]
        truth_xy = [(o["x_st"], o["y_st"]) for o in truth]
        pairs = out_score.add_frame([p["xy"] for p in people], truth_xy)
        teamed_score.add_frame([p["xy"] for p in people if team_of.get(p["track"])], truth_xy)
        for i, j, _ in pairs:
            gt_ids[truth[j]["track_id"]].add(people[i]["track"])
            team = team_of.get(people[i]["track"])
            if team:
                team_total += 1
                team_right += team == TEAMS[truth[j]["side"]]

    raw_events = derive(moments)
    events = to_messages(raw_events, clip.MATCH_ID, 1, plus)

    t0, t1 = clip.frame_t(clip.FIRST_FRAME), clip.frame_t(clip.LAST_FRAME)
    bas = [b for b in load_bas(clip.BAS) if b.period == 1 and t0 <= b.t <= t1 and b.label != "OUT"]
    truth_events = [(b.t, b.our_type) for b in bas]
    predicted = [(e["t"], e["type"]) for e in events]

    secs = [r["seconds"] for r in rows]
    bench = {
        "clip": {"match": clip.MATCH, "half": 1, "from": "38:00.0", "to": "39:40.0", "frames": len(rows),
                 "fps_processed": clip.FPS / clip.STRIDE},
        "detector": {"model": "RF-DETR small (rfdetr 1.11.2), COCO weights as released, no fine-tuning",
                     "tiles": "5 x 2 over rows 90-790, 96 px overlap", "person_min_score": clip.PERSON_MIN_SCORE,
                     "device": "CPU"},
        "calibration": json.loads(clip.CALIBRATION.read_text(encoding="utf-8"))["held_out_by_degree"],
        "detections_on_pitch": raw_score.summary(),
        "tracked_players": out_score.summary() | {
            "team_accuracy": team_right / team_total if team_total else None,
            "tracks": len(history),
            "spectator_tracks_dropped": len(spectators),
            "ground_truth_players": len(gt_ids),
            "tracks_per_ground_truth_player_mean": mean(len(v) for v in gt_ids.values()) if gt_ids else None,
        },
        "players_with_a_team": {k: v for k, v in teamed_score.summary().items()
                                if k in ("recall", "precision", "detections", "matched")},
        "ball": {"frames_with_ball": sum(b is not None for b in ball_of), "frames": len(ball_of),
                 "note": "SoccerTrack has no ball ground truth; not scored"},
        "events": {
            "predicted": dict(Counter(e["type"] for e in events)),
            "bas_in_clip": dict(Counter(b.label for b in bas)),
            "within_1s": event_recall(predicted, truth_events, 1.0),
            "within_5s": event_recall(predicted, truth_events, 5.0),
        },
        "timing": {"detect_seconds_per_frame_mean": round(mean(secs), 2),
                   "detect_seconds_per_frame_median": round(median(secs), 2),
                   "detect_minutes_total": round(sum(secs) / 60, 1),
                   "process_seconds": None},
    }
    with open(clip.FRAMES_OUT, "w", encoding="utf-8", newline="\n") as f:
        for fr in frames_out:
            f.write(json.dumps(fr, separators=(",", ":")) + "\n")
    with open(clip.EVENTS_OUT, "w", encoding="utf-8", newline="\n") as f:
        for e in events:
            f.write(json.dumps(e, separators=(",", ":")) + "\n")
    bench["timing"]["process_seconds"] = round(time.perf_counter() - started, 1)
    bench = rounded(bench)
    with open(clip.BENCHMARK, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(bench, indent=1) + "\n")
    print(json.dumps(bench, indent=1))


if __name__ == "__main__":
    main()
