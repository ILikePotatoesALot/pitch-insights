"""AI commentary for the video clip: its moments (evidence packs), the video narrator and its routing, the
groundedness check on clip moments, the desk with a fake writer, and the stored commentary and translations
reaching the app over the WebSocket. Uses the real clip in samples/video/ and its stored files; no model, no
network (the writer is a fake, and the stored files are read from disk).
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pitch_insights import server
from pitch_insights.agents import grounding
from pitch_insights.agents.desk import AgentWriter, CommentaryDesk, Lines, agent_for, fallback_lines
from pitch_insights.agents.prompts import (
    PROMPT_VERSION, VIDEO_NARRATOR_INSTRUCTIONS, VIDEO_PROMPT_VERSION, input_hash, moment_input,
)
from pitch_insights.agents.store import commentary_path, load_commentary, with_commentary
from pitch_insights.agents.translate import (
    LANGUAGES, _names_pattern, check, load_translations, moment_texts, names_for, protect, unprotect,
)
from pitch_insights.server import SAMPLES, app
from pitch_insights.video.moments import GAP_S, TOP_SPEED_MS, clip_moments, load_clip_moments
from pitch_insights.video.replay import APP_CLIPS, clip_meta, find_clip, stored_path

NAME = APP_CLIPS[0]
client = TestClient(app)


@pytest.fixture(scope="module")
def clip():
    return find_clip(SAMPLES, NAME)


@pytest.fixture(scope="module")
def meta(clip):
    return clip_meta(clip)


@pytest.fixture(scope="module")
def moments(clip):
    return clip_moments(clip)


class FakeWriter:
    provider, model = "fake", "fake-model"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls: list[tuple[str, str]] = []

    async def write(self, role, prompt):
        self.calls.append((role, prompt))
        return self.replies.pop(0)


def run(coro):
    return asyncio.run(coro)


def by_id(moments, mid):
    return next(m for m in moments if m["id"] == mid)


# ------------------------------------------------------------------ the moments

def test_the_clip_has_a_handful_of_well_formed_moments(clip, moments, meta):
    assert 4 <= len(moments) <= 6
    assert [m["id"] for m in moments] == [f"C-{i}" for i in range(1, len(moments) + 1)]
    assert [m["t"] for m in moments] == sorted(m["t"] for m in moments)
    keys = {"id", "seq", "t", "match_time", "clock", "minute", "period", "type", "team_id", "player_id", "player_name",
            "importance", "rank", "tier", "headline", "facts", "signals", "score", "source"}
    for m in moments:
        assert set(m) == keys
        assert m["source"] == "video" and m["period"] == 1 and m["tier"] == "notable"
        assert m["type"] in ("passage", "turnover") and m["team_id"] in ("L", "R")
        assert m["score"] == {} and m["signals"] == []  # the real score isn't known: never made up
        assert 0.35 <= m["importance"] < 0.6 and m["rank"] == m["importance"]
        assert re.fullmatch(r"\d{2}:\d\d", m["clock"]) and m["minute"] in (39, 40)
        assert m["player_id"].startswith(m["team_id"]) and re.fullmatch(r"(Left|Right) #\d+", m["player_name"])
        assert m["headline"]
        assert m["facts"] and all(f["text"] for f in m["facts"])
    last_events = {max(e["t"] for e in clip.events if e["t"] <= m["t"]) for m in moments}
    assert last_events == {m["t"] for m in moments}  # each moment is stamped with its last event


def test_the_moments_are_deterministic_and_all_of_the_events_are_in_one(clip, moments):
    assert clip_moments(clip) == moments
    seqs = [m["seq"] for m in moments]
    assert seqs == sorted(seqs) and seqs[-1] == max(e["seq"] for e in clip.events)
    n_events = sum(f["value"].get("events", 0) for m in moments for f in m["facts"] if f["kind"] == "detected")
    assert n_events == len(clip.events)


def test_a_gap_over_six_seconds_splits_a_passage_and_a_lost_pass_then_an_interception_is_a_turnover(clip):
    def ev(seq, t, team, kind, **kw):
        base = {"seq": seq, "t": t, "minute": 39, "team_id": team, "player_id": f"{team}-t{seq}", "x": 50.0, "y": 30.0,
                "confidence": 0.8, "type": kind}
        return base | kw

    carry = lambda seq, t: ev(seq, t, "L", "carry", end_x=52.0, end_y=30.0)  # noqa: E731
    exactly, over = GAP_S, GAP_S + 0.1
    events = [carry(1, 2300.0), carry(2, 2300.0 + exactly), carry(3, 2300.0 + exactly + over)]
    same = clip_moments(dataclasses.replace(clip, events=events))
    assert len(same) == 2  # a gap of exactly 6 s keeps the passage together, 6.1 s splits it
    assert same[0]["facts"][0]["value"]["events"] == 2 and same[1]["facts"][0]["value"]["events"] == 1
    lost = ev(4, 2400.0, "L", "pass", outcome="incomplete", end_x=60.0, end_y=30.0, length=10.0)
    won = ev(5, 2401.0, "R", "interception", outcome="won")
    other = ev(6, 2450.0, "R", "interception", outcome="won")
    turned = clip_moments(dataclasses.replace(clip, events=[lost, won]))
    assert [m["type"] for m in turned] == ["turnover"] and turned[0]["team_id"] == "R" and turned[0]["player_id"] == "R-t5"
    assert "Right wins the ball after Left's pass goes astray" == turned[0]["headline"]
    not_a_turnover = clip_moments(dataclasses.replace(clip, events=[lost, ev(7, 2402.0, "L", "interception", outcome="won")]))
    assert not_a_turnover[0]["type"] == "passage"  # the same side getting it back is not a turnover
    after_a_gap = clip_moments(dataclasses.replace(clip, events=[lost, other]))
    assert [m["type"] for m in after_a_gap] == ["passage", "passage"]  # an interception 50 s later is no turnover


def test_the_real_clip_has_turnovers_and_passages(moments):
    assert {m["type"] for m in moments} == {"passage", "turnover"}
    c4 = by_id(moments, "C-4")
    assert c4["type"] == "turnover" and c4["team_id"] == "R" and c4["player_name"] == "Right #4"
    assert c4["headline"] == "Right wins the ball after Left's pass goes astray"


NUM = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")


def _backed_by_values(fact: dict) -> set[float]:
    """The numbers a fact's value carries (a number, or a dict of them)."""
    v = fact["value"]
    return {float(x) for x in (v.values() if isinstance(v, dict) else [v])}


def test_every_fact_has_numeric_values_and_every_number_in_its_text_is_backed(moments):
    for m in moments:
        for f in m["facts"]:
            v = f["value"]
            nums = list(v.values()) if isinstance(v, dict) else [v]
            assert nums and all(isinstance(x, int) and not isinstance(x, bool) for x in nums), f  # whole numbers
            text = re.sub(r"\d+:\d\d", "", f["text"])  # clocks are in the moment's clock and facts' own times
            text = re.sub(r"#\d+", "", text)  # tracker IDs are in the player names
            backed = _backed_by_values(f)
            if "confidence_pct" in f["value"] if isinstance(f["value"], dict) else False:
                assert f"{f['value']['confidence_pct']}%" in f["text"]  # as a percentage
            for n in NUM.findall(text):
                assert float(n) in backed, (m["id"], f["kind"], n, f["text"])


def test_events_carry_how_sure_the_model_was_and_low_confidence_says_so(clip, moments):
    ev_facts = [(m, f) for m in moments for f in m["facts"] if f["kind"] in ("pass", "pass_incomplete", "carry", "interception")]
    assert len(ev_facts) == len(clip.events)
    for _, f in ev_facts:
        low = f["value"]["confidence_pct"] < 60
        assert ("low confidence" in f["text"]) == low


def test_top_speeds_are_held_for_a_second_in_km_per_h_and_never_a_glitch(clip, moments):
    seen = 0
    for m in moments:
        for f in (f for f in m["facts"] if f["kind"] == "top_speed"):
            seen += 1
            assert 10 <= f["value"] <= round(TOP_SPEED_MS * 3.6) and "km/h or more for at least a second" in f["text"]
            who = re.match(r"((?:Left|Right) #(\d+)) was tracked", f["text"])
            pid = f"{'L' if who.group(1).startswith('Left') else 'R'}-t{who.group(2)}"
            speeds = [p["speed"] for fr in clip.frames for p in fr["players"] if p["id"] == pid and p["speed"] is not None]
            assert max(speeds) * 3.6 >= f["value"] - 0.5  # the player really was that fast somewhere in the clip
    assert seen >= len(moments)  # most moments have at least one
    assert max(f["value"] for m in moments for f in m["facts"] if f["kind"] == "top_speed") < 34  # the 11 m/s glitches are out


def test_team_shape_comes_from_the_frame_nearest_the_moment(clip, moments):
    m = by_id(moments, "C-4")
    shape = {f["text"].split()[2]: f for f in m["facts"] if f["kind"] == "shape"}
    frame = min(clip.frames, key=lambda f: abs(f["t"] - m["t"]))
    for side, name in (("L", "Left"), ("R", "Right")):
        xs = [p["x"] for p in frame["players"] if p["team_id"] == side]
        v = shape[name]["value"]
        assert v["tracked"] == len(xs) and v["attacking_third"] == sum(x >= 70 for x in xs)
        assert v["own_third"] == sum(x < 35 for x in xs) and v["depth_m"] == round(max(xs) - min(xs))


def test_nobody_has_a_name_only_a_side_and_a_tracker_number(moments):
    text = " ".join(f["text"] for m in moments for f in m["facts"]) + " ".join(m["headline"] for m in moments)
    assert not re.search(r"\b(?:shirt|jersey)\b", text, re.I)
    assert set(re.findall(r"\b([A-Z][a-z]+) #\d+", text)) <= {"Left", "Right"}


# ------------------------------------------------------------------ the video narrator

def test_video_moments_go_to_the_video_narrator_and_synthetic_ones_do_not(moments):
    assert {agent_for(m) for m in moments} == {"video_narrator"}
    assert agent_for({"type": "goal"}) == "explainer" and agent_for({"type": "momentum_swing"}) == "narrator"
    assert agent_for({"type": "passage", "source": "video"}) == "video_narrator"
    assert agent_for({"type": "goal", "source": "synthetic"}) == "explainer"


def test_the_video_narrators_instructions_carry_the_clip_rules():
    text = VIDEO_NARRATOR_INSTRUCTIONS
    assert "## Grounding rules" in text and "## Safety rules" in text and "## Style" in text and "## Output" in text
    for rule in ("computer-vision model", "under 60%", "tracker's number for a player, not a shirt number", "goals, shots, fouls, cards",
                 "real amateur players", "no judgments"):
        assert rule in text, rule


def test_the_writer_builds_three_agents():
    class Client:  # Agent Framework only stores the client until a run
        pass

    from agent_framework import Agent

    try:
        writer = AgentWriter(Client(), "fake", "m")
    except Exception as e:  # pragma: no cover - a client type Agent Framework refuses
        pytest.skip(f"Agent needs a real chat client here: {e}")
    assert set(writer.agents) == {"explainer", "narrator", "video_narrator"}
    assert all(isinstance(a, Agent) for a in writer.agents.values())


def test_synthetic_commentary_stays_valid_and_the_clip_has_its_own_prompt_version():
    assert PROMPT_VERSION == "2026-10-21.2" and VIDEO_PROMPT_VERSION != PROMPT_VERSION
    from pitch_insights.agents.memory import memory_for
    from pitch_insights.explain.moments import MatchBrain
    from pitch_insights.generator.io import read_match

    for name in ("comeback-POT-CAR", "thriller-CAR-BRO"):
        path = SAMPLES / f"{name}.jsonl"
        smeta, events = read_match(path)
        brain = MatchBrain(smeta, memory=memory_for(path, smeta))
        for ev in events:
            brain.update(ev)
        stored = load_commentary(path)
        assert stored["prompt_version"] == PROMPT_VERSION
        shown = [with_commentary(m, stored, smeta) for m in brain.moments if m["id"] in stored["moments"]]
        assert shown and all("commentary" in m for m in shown)  # every stored line still matches its moment's input
        assert not any("Source:" in moment_input(m, smeta) for m in shown)


def test_a_video_moments_input_says_it_was_detected_from_video(moments, meta):
    text = moment_input(moments[0], meta)
    assert "Match: Left v Right" in text and "Source: detected from video" in text and "Player: Left #11" in text
    assert text.splitlines()[-1] == "- " + moments[0]["facts"][-1]["text"]


# ------------------------------------------------------------------ groundedness on clip moments

def test_clip_moments_ground_without_false_unsupported(moments, meta):
    c4 = by_id(moments, "C-4")
    ok = ("At 38:48, Left #11's 25 m pass goes astray and Right #4 wins the ball; the model was 62% sure of both. "
          "Right had 6 of its 8 tracked players in its own third, spread 48 m across the pitch.")
    g = grounding.check(ok, c4, meta)
    assert g.passed and g.claims >= 8, g.unsupported
    bad = grounding.check("Right #5 wins it after a 31 m pass.", c4, meta)
    assert set(bad.unsupported) == {"5", "31"}
    assert grounding.check("Carrot FC win the ball back.", c4, meta).unsupported == ["Carrot FC"]  # league clubs aren't here


def test_things_video_cannot_see_are_unsupported_for_clip_moments_only(moments, meta):
    c4 = by_id(moments, "C-4")
    for word in ("goal", "Shot", "fouls", "yellow card", "penalty", "offside", "corner", "saved", "scored", "forward",
                 "pressing", "counter-attack", "dominating", "shirt", "number 11"):
        g = grounding.check(f"Left #11's pass, then a {word}.", c4, meta)
        assert g.unsupported and not g.passed, word
    synthetic = {k: v for k, v in c4.items() if k != "source"}
    assert grounding.check("A goal and a shot.", synthetic, meta).passed  # not a clip moment: unchanged


def test_a_low_confidence_event_must_be_hedged_in_each_version(moments):
    c2 = by_id(moments, "C-2")  # one pass, 46% sure
    c4 = by_id(moments, "C-4")  # 62% and 62%
    assert grounding.hedging("Left #16 passes to Left #26.", "It was a 12 m pass.", c2) == [
        "casual: no hedge on events the model was under 60% sure of", "analyst: no hedge on events the model was under 60% sure of"]
    assert grounding.hedging("Left #16 appears to pass.", "The model was only 46% sure.", c2) == []
    assert grounding.hedging("The model wasn't sure.", "It looks like a pass.", c2) == []
    assert grounding.hedging("Left #11's pass goes astray.", "Right #4 wins it.", c4) == []  # nothing under 60%
    assert grounding.hedging("flat", "flat", {"source": "synthetic", "facts": c2["facts"]}) == []


# ------------------------------------------------------------------ the desk, with a fake writer

def test_the_desk_keeps_a_grounded_hedged_line_and_names_the_video_narrator(moments, meta):
    c4 = by_id(moments, "C-4")
    good = Lines(casual="Right #4 wins the ball after Left #11's pass goes astray.",
                 analyst="At 38:48, Left #11's 25 m pass goes astray and Right #4 wins it; the model was 62% sure.")
    writer = FakeWriter(good)
    rec = run(CommentaryDesk(writer, meta).comment(c4))
    assert rec["status"] == "ok" and rec["agent"] == "video_narrator" and rec["attempts"] == 1
    assert rec["grounding"]["score"] == 1.0 and writer.calls[0][0] == "video_narrator"
    assert "Source: detected from video" in writer.calls[0][1]


def test_the_desk_retries_an_ungrounded_line_then_falls_back_to_the_headline(moments, meta):
    c4 = by_id(moments, "C-4")
    bad = Lines(casual="Right #4 wins it with a 40 m tackle.", analyst="A foul on Left #9, 3 times.")
    good = Lines(casual="Right #4 wins the ball.", analyst="Right #4 wins it at 38:48, the model 62% sure.")
    writer = FakeWriter(bad, good)
    rec = run(CommentaryDesk(writer, meta).comment(c4))
    assert rec["status"] == "ok" and rec["attempts"] == 2 and {"40", "foul", "9", "3"} <= set(rec["corrected"])
    assert "40" in writer.calls[1][1]  # the retry names what was wrong
    rec = run(CommentaryDesk(FakeWriter(bad, bad), meta).comment(c4))
    assert rec["status"] == "fallback" and rec["reason"].startswith("not grounded")
    assert rec["casual"] == c4["headline"] + "." and rec["analyst"].startswith(c4["headline"])
    assert rec["analyst"] == fallback_lines(c4).analyst


def test_the_desk_sends_back_an_unhedged_low_confidence_line(moments, meta):
    c2 = by_id(moments, "C-2")
    flat = Lines(casual="Left #16 passes to Left #26.", analyst="Left #16 passes 12 m to Left #26.")
    hedged = Lines(casual="Left #16 appears to pass to Left #26.", analyst="The model was only 46% sure of a 12 m pass.")
    writer = FakeWriter(flat, hedged)
    rec = run(CommentaryDesk(writer, meta).comment(c2))
    assert rec["status"] == "ok" and rec["attempts"] == 2
    assert any("no hedge" in c for c in rec["corrected"])
    assert "no hedge" in writer.calls[1][1]


# ------------------------------------------------------------------ the stored files and the stream

def test_the_stored_commentary_is_the_video_narrators_and_matches_the_current_facts(moments, meta):
    stored = load_commentary(stored_path(SAMPLES, NAME))
    assert stored["ai_generated"] and stored["prompt_version"] == VIDEO_PROMPT_VERSION
    assert commentary_path(stored_path(SAMPLES, NAME)).name == f"{NAME}.commentary.json"
    assert set(stored["moments"]) == {m["id"] for m in moments}
    for m in moments:
        rec = stored["moments"][m["id"]]
        assert rec["input_hash"] == input_hash(m, meta), "stored commentary is out of date: rerun generate_commentary.py"
        assert rec["agent"] == "video_narrator" and rec["status"] in ("ok", "fallback")
        assert rec["safety"] and rec["safety"]["passed"] and rec["grounding"]["unsupported"] == []
        assert with_commentary(m, stored, meta)["commentary"]["casual"] == rec["casual"]
        for line in (rec["casual"], rec["analyst"]):  # a fallback is the headline, so the checks hold for those too
            assert not grounding.check(line, m, meta).unsupported
        assert not grounding.hedging(rec["casual"], rec["analyst"], m)


def test_the_stored_translations_keep_the_labels_and_match_the_english(moments, meta):
    saved = load_translations(stored_path(SAMPLES, NAME))
    stored = load_commentary(stored_path(SAMPLES, NAME))
    assert set(saved["languages"]) == set(LANGUAGES) and set(saved["moments"]) == {m["id"] for m in moments}
    pattern = _names_pattern(names_for(meta), trackers=True)
    for m in moments:
        shown = with_commentary(m, stored, meta)
        entry = saved["moments"][m["id"]]
        for lang in LANGUAGES:
            for key, source in moment_texts(shown).items():
                if key in entry[lang]:  # one that failed its check stays English and isn't stored
                    assert not check(source, entry[lang][key], pattern), (m["id"], lang, key)
                    for label in re.findall(r"(?:Left|Right) #\d+", source):
                        assert label in entry[lang][key]


def test_translating_protects_the_clips_labels():
    pattern = _names_pattern(names_for(clip_meta(find_clip(SAMPLES, NAME))), trackers=True)
    protected = protect("Left #11 passes to Left #6; Right wins it at 38:48 (#4).", pattern)
    assert protected.count('<span class="notranslate">') == 4  # Left #11, Left #6, Right and #4
    assert unprotect(protected) == "Left #11 passes to Left #6; Right wins it at 38:48 (#4)."
    synthetic = _names_pattern(["Potato FC"])
    assert protect("Left #11", synthetic) == "Left #11"  # the labels are only protected for the clip


def _tmp_samples(tmp_path: Path, commentary: bool = True, translations: bool = True) -> Path:
    base = tmp_path / "video"
    base.mkdir(parents=True)
    for kind in ("frames.jsonl", "events.jsonl", "benchmark.json") + (("commentary.json",) if commentary else ()) + (
            ("translations.json",) if translations else ()):
        shutil.copy(SAMPLES / "video" / f"{NAME}.{kind}", base / f"{NAME}.{kind}")
    return tmp_path


def _stream(query: str) -> list[dict]:
    out = []
    with client.websocket_connect(f"/ws/replay/{NAME}?{query}") as ws:
        while (msg := ws.receive_json())["type"] != "end":
            out.append(msg)
        out.append(msg)
    return out


def test_the_stream_sends_each_moment_after_its_last_event_with_its_commentary(moments, clip):
    msgs = _stream("speed=600")
    meta_msg = msgs[0]
    assert meta_msg["commentary"]["ai_generated"] and meta_msg["commentary"]["model"] and meta_msg["commentary"]["summary"]["moments"] == len(moments)
    sent = [m for m in msgs if m["type"] == "moment"]
    assert [m["moment"]["id"] for m in sent] == [m["id"] for m in moments]
    for msg, m in zip(sent, moments):
        shown = msg["moment"]
        assert shown["commentary"]["agent"] == "video_narrator" and shown["commentary"]["status"] == "ok"
        assert shown["source"] == "video" and shown["score"] == {} and shown["headline"] == m["headline"]
        last = max(i for i, x in enumerate(msgs) if x["type"] == "event" and x["event"]["t"] <= m["t"])
        assert msgs.index(msg) > last  # after its last event
        assert all(x["event"]["t"] <= m["t"] for x in msgs[:msgs.index(msg)] if x["type"] == "event")
    assert not any(m["type"] in ("state", "catchup") for m in msgs)
    assert len([m for m in msgs if m["type"] == "event"]) == len(clip.events)


def test_a_seek_sends_the_earlier_moments_in_the_catchup_with_the_events():
    msgs = _stream("speed=600&at=60")
    catchup = next(m for m in msgs if m["type"] == "catchup")
    assert [e["event"]["seq"] for e in catchup["events"]] == list(range(1, 10))
    assert [m["id"] for m in catchup["moments"]] == ["C-1", "C-2", "C-3", "C-4"]
    assert all(m["commentary"]["status"] == "ok" for m in catchup["moments"])
    assert [m["moment"]["id"] for m in msgs if m["type"] == "moment"] == ["C-5"]  # the rest follow as they happen
    late = _stream("speed=600&at=99.8")
    assert [m["id"] for m in next(m for m in late if m["type"] == "catchup")["moments"]] == [f"C-{i}" for i in range(1, 6)]
    assert not [m for m in late if m["type"] == "moment"]


def test_a_moment_comes_in_the_viewers_language_with_the_labels_unchanged(moments):
    en = next(m for m in _stream("speed=600&at=99.8") if m["type"] == "catchup")["moments"]
    de = next(m for m in _stream("speed=600&at=99.8&lang=de") if m["type"] == "catchup")["moments"]
    assert [m["id"] for m in de] == [m["id"] for m in en]
    assert all(m.get("lang") == "de" for m in de) and not any("lang" in m for m in en)
    assert de[3]["headline"] != en[3]["headline"] and de[3]["commentary"]["casual"] != en[3]["commentary"]["casual"]
    for e, d in zip(en, de):
        assert d["clock"] == e["clock"] and d["player_name"] == e["player_name"]
        for label in re.findall(r"(?:Left|Right) #\d+", e["commentary"]["casual"]):
            assert label in d["commentary"]["casual"]
    unknown = next(m for m in _stream("speed=600&at=99.8&lang=klingon") if m["type"] == "catchup")["moments"]
    assert unknown == en  # an unknown language is English


def test_without_stored_files_the_moments_still_come_but_without_commentary(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "SAMPLES", _tmp_samples(tmp_path, commentary=False, translations=False))
    msgs = _stream("speed=600&at=99.8")
    assert msgs[0]["commentary"] is None
    catchup = next(m for m in msgs if m["type"] == "catchup")
    assert len(catchup["moments"]) == 5 and not any("commentary" in m for m in catchup["moments"])


def test_commentary_written_from_other_facts_is_not_shown(tmp_path, monkeypatch):
    samples = _tmp_samples(tmp_path)
    path = samples / "video" / f"{NAME}.commentary.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["moments"]["C-2"]["input_hash"] = "0" * 16
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(server, "SAMPLES", samples)
    catchup = next(m for m in _stream("speed=600&at=99.8") if m["type"] == "catchup")["moments"]
    assert "commentary" not in catchup[1] and all("commentary" in m for i, m in enumerate(catchup) if i != 1)


def test_a_draft_that_waits_on_the_safety_check_never_leaves_the_server(tmp_path, monkeypatch):
    samples = _tmp_samples(tmp_path)
    path = samples / "video" / f"{NAME}.commentary.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["moments"]["C-1"]["pending"] = {"casual": "unchecked draft", "analyst": "unchecked draft"}
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(server, "SAMPLES", samples)
    catchup = next(m for m in _stream("speed=600&at=99.8") if m["type"] == "catchup")["moments"]
    assert "pending" not in catchup[0]["commentary"] and "unchecked" not in json.dumps(catchup)


def test_moments_add_no_cues_of_their_own_to_the_event_lower_thirds():
    """A moment's lower-third (priority 70 at most) never won a slot against the event lower-thirds (74 and up),
    so the stream doesn't make one: the cues are the events', as before."""
    msgs = _stream("speed=40&mode=analyst")
    cues = [m["cue"] for m in msgs if m["type"] == "cue"]
    assert cues and all(c["moment_id"] is None and c["data"]["kind"] in ("carry", "pass", "interception") for c in cues)


def test_the_scripts_read_the_same_moments_as_the_server(moments, meta):
    loaded = load_clip_moments(SAMPLES, NAME)
    assert loaded[1] == moments and loaded[0] == meta
    assert load_clip_moments(SAMPLES, "no-such-clip") is None
