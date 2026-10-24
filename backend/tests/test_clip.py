"""The video clip in the replay server: loading the stored frames and events, the words and cues for events,
and the WebSocket stream. Uses the real files in samples/video/ (small, and the same ones the app plays)
plus hand-made snippets for the failure cases. No video, model or network.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pitch_insights.events.schema import Frame
from pitch_insights.server import SAMPLES, app
from pitch_insights.video.replay import (
    APP_CLIPS, ClipError, cue_for_event, describe, event_length, find_clip, list_clips, player_label,
)

NAME = APP_CLIPS[0]
client = TestClient(app)


@pytest.fixture(scope="module")
def clip():
    found = find_clip(SAMPLES, NAME)
    assert found, "samples/video/117093-38min_ft.* must be in the repo"
    return found


def _copy(tmp_path: Path, **changes) -> Path:
    """A copy of the clip's files in a fresh samples folder, with `frames` / `events` / `benchmark` text replaced."""
    base = tmp_path / "video"
    base.mkdir(parents=True)
    for kind in ("frames.jsonl", "events.jsonl", "benchmark.json"):
        shutil.copy(SAMPLES / "video" / f"{NAME}.{kind}", base / f"{NAME}.{kind}")
    for key, text in changes.items():
        suffix = "benchmark.json" if key == "benchmark" else f"{key}.jsonl"
        (base / f"{NAME}.{suffix}").write_text(text, encoding="utf-8")
    return tmp_path


# ------------------------------------------------------------------ loading

def test_loads_the_frames_and_events(clip):
    assert len(clip.frames) == 500 and clip.events
    assert clip.start == 2280.0 and clip.duration == pytest.approx(99.8) and clip.frame_dt == 0.2
    assert all(Frame.model_validate(f) for f in clip.frames[:5])
    assert [e["t"] for e in clip.events] == sorted(e["t"] for e in clip.events)
    assert all(e["source"] == "video" and 0 < e["confidence"] < 1 for e in clip.events)


def test_a_clip_is_loaded_once_and_again_when_its_file_changes(tmp_path):
    samples = _copy(tmp_path)
    first = find_clip(samples, NAME)
    assert find_clip(samples, NAME) is first
    path = samples / "video" / f"{NAME}.events.jsonl"
    path.write_text(path.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
    import os
    os.utime(path, ns=(10**18, 10**18))
    assert len(find_clip(samples, NAME).events) == 1


def test_names_that_are_not_clips_find_nothing(tmp_path):
    assert find_clip(SAMPLES, "no-such-clip") is None
    assert find_clip(SAMPLES, "../comeback-POT-CAR") is None
    assert find_clip(SAMPLES, "..") is None
    assert find_clip(tmp_path, NAME) is None  # no video folder at all
    samples = _copy(tmp_path)
    (samples / "video" / f"{NAME}.benchmark.json").unlink()
    assert find_clip(samples, NAME) is None  # a clip needs all three files


def test_a_bad_frames_file_is_refused_with_a_reason(tmp_path):
    lines = (SAMPLES / "video" / f"{NAME}.frames.jsonl").read_text(encoding="utf-8").splitlines()
    swapped = [lines[1], lines[0], *lines[2:]]
    with pytest.raises(ClipError, match="must increase"):
        find_clip(_copy(tmp_path, frames="\n".join(swapped) + "\n"), NAME)
    broken = json.loads(lines[0]) | {"players": [{"id": "L-t1", "team_id": "L", "x": 500, "y": 3, "confidence": 0.5}]}
    with pytest.raises(ClipError, match="not a valid frame"):
        find_clip(_copy(tmp_path / "b", frames=json.dumps(broken) + "\n"), NAME)
    with pytest.raises(ClipError, match="no frames"):
        find_clip(_copy(tmp_path / "c", frames=""), NAME)


# ------------------------------------------------------------------ labels, words and cues

def test_players_are_labelled_by_side_and_number_never_by_name():
    assert player_label("L-t12") == "Left #12"
    assert player_label("R-t4") == "Right #4"
    assert player_label("X-t5") == "Track #5"
    assert player_label(None) == "Unknown" and player_label("POT-09") == "Unknown"


def test_event_words_follow_the_language_and_keep_the_labels(clip):
    ev = next(e for e in clip.events if e["type"] == "pass" and e["outcome"] == "complete")
    en, detail = describe(ev)
    assert en == "Left #11 passes to #6" and detail == "Detected from the video · 27 m · confidence 64%"
    de, de_detail = describe(ev, "de")
    assert de == "Left #11 passt zu #6" and "Im Video erkannt" in de_detail
    assert describe(ev, "xx") == describe(ev)  # an unknown language falls back to English
    for lang in ("es", "fr", "nl", "zh-Hans"):
        text = describe(ev, lang)[0]
        assert "Left #11" in text and "#6" in text and text != en


def test_every_event_has_words_in_every_language(clip):
    from pitch_insights.video.replay import PHRASES

    assert {e["type"] for e in clip.events} <= {"pass", "carry", "interception"}
    for lang in PHRASES:
        for ev in clip.events:
            headline, detail = describe(ev, lang)
            assert headline and detail and "{" not in headline + detail


def test_event_length_of_a_carry_is_measured_from_its_end_points():
    assert event_length({"type": "carry", "x": 10, "y": 10, "end_x": 13, "end_y": 14}) == 5.0
    assert event_length({"type": "interception", "x": 10, "y": 10}) is None


def test_cues_for_events_are_lower_thirds_with_a_tier_by_how_much_they_matter(clip):
    cues = {e["seq"]: cue_for_event(e) for e in clip.events}
    assert all(c["template"] == "lower_third" and c["duration"] >= 6 and 0 <= c["priority"] <= 100 for c in cues.values())
    by_type = lambda t: [cues[e["seq"]] for e in clip.events if e["type"] == t]  # noqa: E731
    assert all(c["detail"] == "casual" for c in by_type("interception"))
    assert all(c["detail"] == "analyst" for c in by_type("carry"))
    assert max(c["priority"] for c in cues.values()) < 90  # nothing here is urgent: goals aren't detected
    long_pass = next(e for e in clip.events if e["type"] == "pass" and e["outcome"] == "complete" and e["length"] >= 20)
    short_pass = next(e for e in clip.events if e["type"] == "pass" and e["outcome"] == "complete" and e["length"] < 5)
    assert cues[long_pass["seq"]]["detail"] == "casual" and cues[short_pass["seq"]]["detail"] == "analyst"
    assert cues[long_pass["seq"]]["data"]["clock"] == "38:01"


def test_the_credibility_figures_are_the_benchmark_files(clip):
    from pitch_insights.video.replay import credibility

    info = credibility(clip)
    bench = json.loads((SAMPLES / "video" / f"{NAME}.benchmark.json").read_text(encoding="utf-8"))
    f = info["figures"]
    assert f["precision"] == bench["tracked_players"]["precision"] == 0.9676
    assert f["recall"] == 0.9314 and f["position_error_mean_m"] == 0.7608 and f["team_accuracy"] == 0.9487
    assert f["ball_frames"] == 226 and f["frames"] == 500
    assert info["fine_tuned"] and "RF-DETR small fine-tuned" in info["model"]
    assert info["credit"] == "SoccerTrack v2 (CC BY 4.0)" and info["credit_url"].startswith("https://")
    assert any("not from tags" in line for line in info["limits"]) and any("tracker IDs" in line for line in info["limits"])


# ------------------------------------------------------------------ the API

def test_the_clip_is_listed_after_the_synthetic_matches():
    matches = client.get("/api/matches").json()
    assert [m["kind"] for m in matches][:1] == ["synthetic"] and matches[-1]["name"] == NAME
    clip_row = matches[-1]
    assert clip_row["kind"] == "video" and clip_row["home"]["name"] == "Left" and clip_row["away"]["name"] == "Right"
    assert {m["name"] for m in list_clips(SAMPLES)} == {NAME}
    assert "pretrained" not in json.dumps(matches)


def test_the_clip_has_a_match_meta_with_no_names_and_no_squads():
    meta = client.get(f"/api/matches/{NAME}").json()
    assert meta["type"] == "match_meta" and meta["source"] == "video"
    assert meta["home"]["players"] == meta["away"]["players"] == []
    assert meta["attacking_direction"]["1"] == {"L": "left_to_right", "R": "right_to_left"}
    assert client.get("/api/matches/..%2Fx").status_code == 404
    clubs = client.get("/api/clubs").json()
    assert all(c["id"] not in ("L", "R") for c in clubs)  # favourite clubs don't apply to the clip


# ------------------------------------------------------------------ the stream

def _stream(query: str) -> list[dict]:
    """Every message until the end. (Tests always read to the end: closing the test client while the server is
    still sending races the TestClient's own teardown. A seek to the last frame, `at=99.8`, makes a short stream.)"""
    out = []
    with client.websocket_connect(f"/ws/replay/{NAME}?{query}") as ws:
        while (msg := ws.receive_json())["type"] != "end":
            out.append(msg)
        out.append(msg)
    return out


def test_streams_every_frame_and_event_in_order_then_ends():
    msgs = _stream("speed=600")
    assert [m["type"] for m in msgs[:1]] == ["meta"] and msgs[-1]["type"] == "end"
    frames = [m for m in msgs if m["type"] == "frame"]
    assert len(frames) == 500 and [f["t"] for f in frames] == sorted(f["t"] for f in frames)
    assert all(Frame.model_validate(f) for f in frames[:3])
    events = [m for m in msgs if m["type"] == "event"]
    assert len(events) == len(find_clip(SAMPLES, NAME).events)
    assert events[0]["text"] == "Left #11 runs with the ball" and events[0]["event"]["source"] == "video"
    assert not any(m["type"] in ("moment", "state", "catchup") for m in msgs)  # no commentary, no synthetic state


def test_meta_carries_the_clip_info_the_panel_shows():
    meta = _stream("speed=600&at=99.8")[0]
    assert meta["kind"] == "video" and meta["commentary"] is None and meta["lang"] == "en"
    assert meta["clip"]["credit"] == "SoccerTrack v2 (CC BY 4.0)" and meta["clip"]["figures"]["recall"] == 0.9314
    assert meta["clip"]["clip"]["duration"] == pytest.approx(99.8)
    assert set(meta["languages"]) == {"en", "es", "fr", "de", "nl", "zh-Hans"}
    assert set(meta["profile"]) == {"mode", "team_id", "player_id", "focus"}


def test_seeking_starts_there_with_the_earlier_events():
    msgs = _stream("speed=600&at=60")
    catchup = next(m for m in msgs if m["type"] == "catchup")
    assert [e["event"]["seq"] for e in catchup["events"]] == list(range(1, 10))  # events before 38:00 + 60 s: 1-9
    frames = [m for m in msgs if m["type"] == "frame"]
    assert frames[0]["t"] == pytest.approx(2340.0, abs=0.01) and len(frames) == 200
    assert [m["event"]["seq"] for m in msgs if m["type"] == "event"] == [10, 11, 12, 13, 14]


def test_bad_start_values_are_handled():
    for query in ("at=abc", "at=nan", "at=-5", "from=zzz"):
        msgs = _stream(f"speed=600&{query}")
        assert next(m for m in msgs if m["type"] == "frame")["t"] == 2280.0 and "catchup" not in {m["type"] for m in msgs}
    msgs = _stream("speed=600&at=1e9")  # past the end: the last frame, then the end
    assert [m["type"] for m in msgs if m["type"] in ("frame", "end")][-1] == "end"


def test_language_changes_the_words_but_not_the_labels():
    msgs = _stream("speed=600&lang=fr")
    assert msgs[0]["lang"] == "fr"
    texts = [m["text"] for m in msgs if m["type"] == "event"]
    assert texts[1] == "Left #11 passe à #6"
    bad = _stream("speed=600&at=99.8&lang=klingon")
    assert bad[0]["lang"] == "en"


def test_cues_keep_the_screen_clean_and_casual_viewers_get_only_theirs():
    def cues(mode: str) -> list[dict]:
        msgs = _stream(f"speed=40&mode={mode}")
        return [m["cue"] for m in msgs if m["type"] == "cue"]

    analyst, casual = cues("analyst"), cues("casual")
    assert analyst and casual and len(casual) <= len(analyst)
    assert all(c["detail"] == "casual" for c in casual)
    assert all(c["template"] == "lower_third" and c["id"].startswith("C-") for c in analyst)
    assert all(re.fullmatch(r"\d+:\d\d", c["data"]["clock"]) for c in analyst)


def test_pausing_and_disconnecting_ends_the_replay():
    import time

    with client.websocket_connect(f"/ws/replay/{NAME}?speed=1") as ws:
        ws.receive_json()
        ws.send_json({"cmd": "pause"})
        ws.send_text("not json")
        ws.send_json({"cmd": "speed", "value": "fast"})
    time.sleep(0.3)  # the server side must have finished; TestClient would hang on exit otherwise


def test_a_frame_that_is_already_out_of_date_is_skipped_not_sent():
    from pitch_insights.video.serve import frame_is_stale

    assert not frame_is_stale(0.05, 0.2, 1)  # on time at 1x
    assert frame_is_stale(0.5, 0.2, 1)  # half a second late at 1x: the next one is already due
    assert not frame_is_stale(0.5, 0.2, 5)  # the same age is a tenth of a second on screen at 5x
    assert frame_is_stale(3.0, 0.2, 5)
    msgs = _stream("speed=1&at=98")
    assert [m["t"] for m in msgs if m["type"] == "frame"][0] == pytest.approx(2378.0, abs=0.01)


# ------------------------------------------------------------------ a damaged clip

def test_a_damaged_clip_is_a_clip_error_and_stays_out_of_the_match_list(tmp_path, monkeypatch, caplog):
    import pitch_insights.server as server

    truncated = (SAMPLES / "video" / f"{NAME}.frames.jsonl").read_text(encoding="utf-8")[:5000]  # cut mid-line
    samples = _copy(tmp_path, frames=truncated)
    with pytest.raises(ClipError, match="can't be read"):
        find_clip(samples, NAME)
    no_ball = json.loads((SAMPLES / "video" / f"{NAME}.benchmark.json").read_text(encoding="utf-8"))
    del no_ball["ball"]
    with pytest.raises(ClipError, match="KeyError"):
        find_clip(_copy(tmp_path / "b", benchmark=json.dumps(no_ball)), NAME)

    monkeypatch.setattr(server, "SAMPLES", samples)
    names = [m["name"] for m in client.get("/api/matches").json()]
    assert NAME not in names  # the list still works (here: no synthetic matches in the copy, and no clip)
    with client.websocket_connect(f"/ws/replay/{NAME}") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "error" and "can't be read" in msg["message"]


def test_damaged_benchmark_values_are_refused_not_just_missing_keys(tmp_path):
    good = json.loads((SAMPLES / "video" / f"{NAME}.benchmark.json").read_text(encoding="utf-8"))

    def damaged(path: list[str], value) -> str:
        b = json.loads(json.dumps(good))
        node = b
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
        return json.dumps(b)

    cases = [
        (["tracked_players", "position_error_mean_m"], None),  # a null that used to crash the panel's toFixed
        (["tracked_players", "precision"], "97%"),
        (["tracked_players", "recall"], 93),  # a percentage where a fraction belongs
        (["tracked_players", "team_accuracy"], float("nan")),
        (["tracked_players", "tracks"], True),
        (["tracked_players", "tracks"], 52.5),
        (["tracked_players", "position_error_p90_m"], -1),
        (["ball", "frames_with_ball"], 501),  # more frames with a ball than frames
        (["ball", "frames"], 0),
        (["events", "within_5s", "all", "precision"], None),
        (["detector", "model"], ""),
        (["clip", "from"], None),
        (["clip", "fps_processed"], 0),
    ]
    for n, (path, value) in enumerate(cases):
        text = damaged(path, value).replace("NaN", "NaN")
        with pytest.raises(ClipError, match="benchmark"):
            find_clip(_copy(tmp_path / f"c{n}", benchmark=text), NAME)


def test_damaged_events_are_refused(tmp_path):
    lines = (SAMPLES / "video" / f"{NAME}.events.jsonl").read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    for n, change in enumerate([{"confidence": None}, {"x": "65"}, {"type": "shot"}, {"team_id": "X"}, {"end_x": 500}, {"y": float("nan")}]):
        text = "\n".join([json.dumps(first | change), *lines[1:]]) + "\n"
        with pytest.raises(ClipError, match="event"):
            find_clip(_copy(tmp_path / f"e{n}", events=text), NAME)
