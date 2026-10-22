"""Video path: loader, coordinates, tile merging, tracking, events, benchmark, frame message.

No video, model or network: the GSR and BAS inputs are tiny hand-made snippets.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from pitch_insights.events.schema import Frame, display_clock, dump
from pitch_insights.video.bench import DetectionScore, event_recall, match_points
from pitch_insights.video.events import Moment, PlayerAt, derive, to_messages
from pitch_insights.video.soccertrack import (
    from_our_frame, iter_gsr, iter_top_level, parse_bas, to_our_frame,
)
from pitch_insights.video.tiles import Detection, make_tiles, merge, shift
from pitch_insights.video.track import PitchTracker, smoothed_speeds, spectator_tracks


def _person(image_id, track, side, jersey, x, y, role="player"):
    return {
        "id": f"{image_id}{track:02d}", "image_id": image_id, "track_id": track,
        "supercategory": "object", "category_id": 1 if role == "player" else 2,
        "attributes": {"role": role, "jersey": jersey, "team": side, "player_id": 1000 + track},
        "bbox_image": {"x": 100, "y": 200, "x_center": 110.0, "y_center": 221.5, "w": 20, "h": 43},
        "bbox_pitch": {"x_bottom_middle": x, "y_bottom_middle": y},
    }


def _gsr(frames=3, out_of_order=False):
    images = [{"image_id": f"39030000{n:02d}", "file_name": f"{n:06d}.jpg", "height": 1080, "width": 4096}
              for n in range(1, frames + 1)]
    anns = []
    for n in range(1, frames + 1):
        iid = f"39030000{n:02d}"
        anns.append({"id": f"{iid}P", "image_id": iid, "supercategory": "pitch", "category_id": 5, "lines": {}})
        anns.append(_person(iid, 1, "left", "7", -10.5 + n, 3.4))
        anns.append(_person(iid, 2, "right", "51", 47.25, -1.36, role="goalkeeper"))
    if out_of_order:
        anns[0], anns[-1] = anns[-1], anns[0]
    return {"info": {"version": "1.3", "frame_rate": 25, "seq_length": frames}, "images": images,
            "annotations": anns, "categories": [{"id": 1, "name": "player"}]}


def _write(tmp_path, data, indent=4):
    p = tmp_path / "gsr.json"
    p.write_text(json.dumps(data, indent=indent), encoding="utf-8")
    return p


# ------------------------------------------------------------- streaming


@pytest.mark.parametrize("chunk", [5, 64, 1 << 20])
def test_iter_top_level_streams_array_items_whatever_the_chunk_size(tmp_path, chunk):
    data = {"a": 12345, "b": [1, {"x": [2, 3]}, "s"], "c": {"d": None}, "e": []}
    p = tmp_path / "t.json"
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    got = list(iter_top_level(p, chunk_size=chunk))
    assert got == [("a", 12345), ("b", 1), ("b", {"x": [2, 3]}), ("b", "s"), ("c", {"d": None})]


def test_iter_top_level_fails_fast_on_a_malformed_item(tmp_path):
    p = tmp_path / "t.json"
    p.write_text('{"a": [{"b": 1}, {"b": 2 x}, ' + ", ".join(['{"c": 1}'] * 5000) + "]}", encoding="utf-8")
    it = iter_top_level(p, chunk_size=16, max_value_chars=64)
    assert next(it) == ("a", {"b": 1})
    with pytest.raises(ValueError):
        next(it)


def test_iter_top_level_rejects_a_truncated_file(tmp_path):
    p = tmp_path / "t.json"
    p.write_text('{"a": [1, 2, {"b": ', encoding="utf-8")
    with pytest.raises(ValueError):
        list(iter_top_level(p, chunk_size=4))


def test_iter_gsr_reads_people_with_frames_from_file_names(tmp_path):
    objs = list(iter_gsr(_write(tmp_path, _gsr())))
    assert len(objs) == 6  # the pitch annotations are skipped
    first = objs[0]
    assert (first.frame, first.track_id, first.role, first.side, first.jersey) == (1, 1, "player", "left", "7")
    assert (first.x_st, first.y_st) == (-9.5, 3.4)
    assert first.box == (100.0, 200.0, 20.0, 43.0)
    assert first.label == "Left #7"
    assert objs[1].role == "goalkeeper" and objs[1].label == "Right #51"


def test_iter_gsr_range_and_stride(tmp_path):
    p = _write(tmp_path, _gsr(frames=6), indent=0)
    assert sorted({o.frame for o in iter_gsr(p, first_frame=2, last_frame=5, stride=2)}) == [2, 4]


def test_iter_gsr_refuses_frames_out_of_order(tmp_path):
    with pytest.raises(ValueError, match="isn't in order"):
        list(iter_gsr(_write(tmp_path, _gsr(out_of_order=True))))


def test_iter_gsr_needs_images_before_annotations(tmp_path):
    data = _gsr()
    data = {"annotations": data["annotations"], "images": data["images"]}
    with pytest.raises(ValueError, match="images must come first"):
        list(iter_gsr(_write(tmp_path, data)))


# ----------------------------------------------------------- coordinates


def test_left_team_attacks_plus_x_and_right_team_is_flipped():
    assert to_our_frame(0, 0, True) == (52.5, 34.0)
    assert to_our_frame(52.5, 34, True) == (105.0, 68.0)  # the goal they attack, far corner
    assert to_our_frame(52.5, 34, False) == (0.0, 0.0)
    assert to_our_frame(-52.5, 0, False) == (105.0, 34.0)  # right team attacks the left goal


@pytest.mark.parametrize("plus", [True, False])
def test_coordinate_round_trip(plus):
    x, y = to_our_frame(-17.3, 21.1, plus)
    assert from_our_frame(x, y, plus) == pytest.approx((-17.3, 21.1))


# ------------------------------------------------------------------- BAS


def test_parse_bas_maps_classes_and_times():
    data = {"actions": [
        {"gameTime": "1 - 38:49", "label": "SHOT", "position": "2329480", "frame": 58238, "team": "left"},
        {"gameTime": "1 - 39:35", "label": "GOAL", "position": "2375080", "frame": 59378, "team": "left"},
        {"gameTime": "2 - 0:46", "label": "CROSS", "position": "46000", "frame": 1151, "team": "right"},
    ]}
    shot, goal, cross = parse_bas(data)
    assert (shot.t, shot.our_type, shot.side) == (2329.48, "shot", "left")
    assert goal.our_type == "shot"
    assert (cross.period, cross.t, cross.our_type) == (2, 46.0, "pass")


def test_parse_bas_corrects_second_half_match_time():
    data = {"actions": [{"gameTime": "2 - 0:46", "label": "PASS", "position": str((2705 + 46) * 1000)}]}
    with pytest.raises(ValueError, match="first_half_s"):
        parse_bas(data)
    (e,) = parse_bas(data, first_half_s=2705)
    assert e.t == pytest.approx(46.0)


def test_parse_bas_rejects_unknown_classes():
    with pytest.raises(ValueError, match="unknown BAS class"):
        parse_bas({"actions": [{"gameTime": "1 - 0:01", "label": "PENALTY", "position": "1000"}]})


# ----------------------------------------------------------------- tiles


def test_tiles_cover_the_band_with_overlap():
    tiles = make_tiles(4096, 1080, 5, 2, 96, top=90, bottom=790)
    assert len(tiles) == 10
    assert min(t[0] for t in tiles) == 0 and max(t[2] for t in tiles) == 4096
    assert min(t[1] for t in tiles) == 90 and max(t[3] for t in tiles) == 790
    row = sorted(t for t in tiles if t[1] == 90)
    for a, b in zip(row, row[1:]):
        assert a[2] - b[0] >= 96  # neighbours overlap


def test_merge_joins_duplicates_and_cut_off_boxes_but_keeps_neighbours():
    whole = Detection((100, 100, 120, 150), 0.6, 1)
    duplicate = Detection((101, 101, 121, 151), 0.8, 1)  # same player from the next tile
    cut = Detection((100, 100, 120, 125), 0.9, 1)  # top half only, at a tile's edge
    neighbour = Detection((130, 100, 150, 150), 0.7, 1)
    ball = Detection((105, 140, 110, 145), 0.5, 37)  # inside the player's box but another class
    merged = merge([whole, duplicate, cut, neighbour, ball])
    people = [d for d in merged if d.class_id == 1]
    assert len(people) == 2
    kept = max(people, key=lambda d: d.score)
    assert kept.score == 0.9 and kept.box[3] >= 150  # the cut-off box grew to the whole player
    assert any(d.class_id == 37 for d in merged)


def test_shift_moves_boxes_into_frame_coordinates():
    (d,) = shift([Detection((1, 2, 3, 4), 0.5, 1)], 100, 90)
    assert d.box == (101, 92, 103, 94)


# -------------------------------------------------------------- tracking


def test_tracker_keeps_ids_for_two_runners():
    tr = PitchTracker()
    a, b = (0.0, 0.0), (5.0, 0.0)
    ids0 = tr.update(0.0, [a, b], [0.9, 0.9])
    for k in range(1, 6):
        t = k * 0.2
        ids = tr.update(t, [(5.0, 1.2 * k), (1.2 * k, 0.0)], [0.9, 0.9])  # listed in the other order
        assert ids == [ids0[1], ids0[0]]


def test_tracker_low_confidence_detection_only_continues_a_track():
    tr = PitchTracker()
    (tid,) = tr.update(0.0, [(0.0, 0.0)], [0.9])
    assert tr.update(0.2, [(0.5, 0.0), (20.0, 20.0)], [0.35, 0.35]) == [tid, None]


def test_tracker_drops_tracks_after_max_missed():
    tr = PitchTracker(max_missed=2)
    (tid,) = tr.update(0.0, [(0.0, 0.0)], [0.9])
    for k in range(1, 4):
        tr.update(0.2 * k, [], [])
    (new,) = tr.update(0.8, [(0.0, 0.0)], [0.9])
    assert new != tid


def test_smoothed_speeds():
    hist = [(0.0, (0.0, 0.0)), (0.2, (1.0, 0.0)), (0.4, (2.0, 0.0)), (2.0, (9.0, 0.0))]
    sp = smoothed_speeds(hist)
    assert sp[0.0] == pytest.approx(5.0)  # one-sided at the start
    assert sp[0.2] == pytest.approx(5.0)  # both neighbours
    assert sp[2.0] is None  # nothing within 0.25 s
    assert smoothed_speeds([(0.0, (0.0, 0.0))]) == {0.0: None}


def test_spectator_tracks_are_still_people_by_the_far_touchline():
    still = [(k * 0.2, (10.0 + 0.1 * (k % 3), -33.0)) for k in range(20)]
    runner = [(k * 0.2, (10.0 + k, -32.0)) for k in range(20)]
    keeper = [(k * 0.2, (-47.0, 0.5 * (k % 2))) for k in range(20)]  # still, but not by the far touchline
    brief = still[:3]
    assert spectator_tracks({1: still, 2: runner, 3: keeper, 4: brief}) == {1}


# ---------------------------------------------------------------- events


def _moments():
    """L-1 runs with the ball, passes to L-2, R-9 intercepts, L-2 wins it back next to him."""
    l1, l2, r9 = "L-t1", "L-t2", "R-t9"
    seq = []
    for k in range(4):  # L-1 carries 4 m
        seq.append(((0.0 + k * 1.3, 0.0), l1, (0.0 + k * 1.3, 0.0)))
    seq.append(((8.0, 0.0), None, None))  # ball in flight
    for k in range(2):
        seq.append(((12.0, 0.0), l2, (12.0, 0.0)))
    seq.append(((16.0, 0.0), None, None))
    for k in range(2):
        seq.append(((20.0, 0.0), r9, (20.0, 0.0)))
    for k in range(2):
        seq.append(((20.5, 0.0), l2, (20.5, 0.0)))
    out = []
    for n, (ball, holder, pos) in enumerate(seq):
        players = [PlayerAt(l1, "L", (0.0 + min(n, 3) * 1.3, 0.0)), PlayerAt(l2, "L", (12.0 if n < 9 else 20.5, 0.0))]
        players.append(PlayerAt(r9, "R", (20.0 if 8 <= n < 11 else 40.0, 0.0)))
        if holder:
            players = [p if p.id != holder else PlayerAt(holder, p.team, pos) for p in players]
        out.append(Moment(n * 0.2, ball, 0.8, tuple(players)))
    return out


def test_derive_finds_carry_pass_interception_and_tackle():
    events = derive(_moments())
    kinds = [(e.type, e.player, e.outcome) for e in events]
    assert ("carry", "L-t1", None) in kinds
    assert ("pass", "L-t1", "complete") in kinds
    assert ("pass", "L-t2", "incomplete") in kinds
    assert ("interception", "R-t9", "won") in kinds
    assert ("tackle", "L-t2", "won") in kinds
    assert [e.t for e in events] == sorted(e.t for e in events)


def test_to_messages_validates_and_uses_each_teams_frame():
    events = derive(_moments())
    msgs = to_messages(events, "ST-117093", 1, {"L": True, "R": False})
    assert [m["seq"] for m in msgs] == list(range(1, len(msgs) + 1))
    assert all(m["source"] == "video" and 0 < m["confidence"] < 1 for m in msgs)
    inter = next(m for m in msgs if m["type"] == "interception")
    assert (inter["x"], inter["y"]) == (52.5 - 20.0, 34.0)  # R attacks -x, so x flips (ball at 20 m)
    carry = next(m for m in msgs if m["type"] == "carry")
    assert carry["x"] == 52.5 and carry["end_x"] > carry["x"]


# ------------------------------------------------------------- benchmark


def test_match_points_pairs_closest_first_within_radius():
    found = [(0.0, 0.0), (10.0, 0.0), (50.0, 50.0)]
    truth = [(0.5, 0.0), (1.0, 0.0), (11.0, 0.0)]
    assert match_points(found, truth, 3.0) == [(0, 0, 0.5), (1, 2, 1.0)]


def test_detection_score_summary():
    s = DetectionScore(3.0)
    s.add_frame([(0.0, 0.0), (30.0, 0.0)], [(1.0, 0.0), (10.0, 0.0)])
    out = s.summary()
    assert (out["recall"], out["precision"], out["position_error_mean_m"]) == (0.5, 0.5, 1.0)


def test_event_recall_by_window_and_type():
    truth = [(10.0, "pass"), (20.0, "pass"), (30.0, "shot")]
    predicted = [(10.5, "pass"), (24.0, "pass"), (30.2, "carry")]
    one = event_recall(predicted, truth, 1.0)
    five = event_recall(predicted, truth, 5.0)
    assert one["pass"]["found"] == 1 and five["pass"]["found"] == 2
    assert one["shot"]["found"] == 0
    assert five["all"]["recall"] == pytest.approx(2 / 3)
    assert five["all"]["precision"] == pytest.approx(2 / 3)


# ------------------------------------------------------------ frame message


def test_frame_message_matches_the_design_example():
    msg = {"type": "frame", "schema": "1.1", "match_id": "ST-117093", "source": "video", "period": 1,
           "t": 12.48, "clock": "1'", "ref_team_id": "L",
           "players": [{"id": "L-07", "team_id": "L", "x": 61.2, "y": 30.4, "speed": 5.8, "confidence": 0.91},
                       {"id": "X-t3", "team_id": None, "x": 50.0, "y": 10.0, "speed": None, "confidence": 0.4}],
           "ball": None}
    frame = Frame.model_validate(msg)
    assert frame.model_dump(mode="json", by_alias=True) == msg


def test_frame_message_survives_the_wire_helper_that_drops_nulls():
    frame = Frame.model_validate({"match_id": "m", "source": "video", "period": 1, "t": 0, "clock": "1'",
                                  "ref_team_id": "L", "ball": None,
                                  "players": [{"id": "X-t3", "team_id": None, "x": 1, "y": 2, "confidence": 0.5}]})
    assert Frame.model_validate(dump(frame)) == frame


def test_frame_message_rejects_positions_off_the_pitch():
    with pytest.raises(ValidationError):
        Frame.model_validate({"match_id": "m", "source": "video", "period": 1, "t": 0, "clock": "1'",
                              "ref_team_id": "L", "ball": None,
                              "players": [{"id": "a", "team_id": "L", "x": 106, "y": 0, "confidence": 1}]})


@pytest.mark.parametrize("period,t,expected", [(1, 0, ("1'", 1)), (1, 2399.9, ("40'", 40)),
                                               (1, 2705, ("45+1'", 45)), (2, 60, ("47'", 47))])
def test_display_clock(period, t, expected):
    assert display_clock(period, t) == expected
