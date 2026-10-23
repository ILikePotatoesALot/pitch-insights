"""The Overlay Director: the clutter rules, pre-emption, cooldowns, queueing, deterministic output, and the
cues built from moments. All on hand-made cues and moments except the last tests, which use the samples."""

from pathlib import Path

import pytest

from pitch_insights.director import CARD_TEMPLATES, CueBuilder, Director, Rules, ShowClock, visible_to
from pitch_insights.director.cues import cue, lower_third_seconds
from pitch_insights.director.sheet import cue_sheet
from pitch_insights.generator.io import read_match

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def make(template="lower_third", priority=70, duration=6.0, topic=None, **kw):
    return cue(template, kw.pop("time", 0.0), duration, priority, tier="headline", detail="casual", moment_id="M-1",
               data={}, team_id=kw.pop("team_id", "POT"), player_id=kw.pop("player_id", None)) | (
        {"topic": topic} if topic else {})


def started(messages):
    return [m["cue"] for m in messages if m["type"] == "cue"]


def ended(messages):
    return [(m["id"], m["reason"]) for m in messages if m["type"] == "cue_end"]


# ---------------------------------------------------------------- clutter rules

def test_a_free_screen_shows_a_cue_at_once():
    d = Director()
    msgs = d.offer([make()], now=10.0)
    assert [c["id"] for c in started(msgs)] == ["C-1"] and started(msgs)[0]["delay"] == 0.0
    assert [c["id"] for c in d.on_screen] == ["C-1"]


def test_a_cue_ends_when_its_duration_is_up():
    d = Director()
    d.offer([make(duration=6.0)], now=10.0)
    assert d.advance(15.9) == []
    assert ended(d.advance(16.0)) == [("C-1", "expired")] and d.on_screen == []


def test_only_one_lower_third_at_a_time():
    d = Director()
    d.offer([make(priority=60)], now=0.0)
    msgs = d.offer([make(priority=62)], now=1.0)  # not high enough to pre-empt
    assert started(msgs) == [] and [c["id"] for c in d.on_screen] == ["C-1"] and d.waiting == 1


def test_the_queued_lower_third_starts_when_the_first_ends():
    d = Director()
    d.offer([make(priority=60)], now=0.0)
    d.offer([make(priority=62)], now=1.0)
    msgs = d.advance(6.0)
    assert ended(msgs) == [("C-1", "expired")] and [c["id"] for c in started(msgs)] == ["C-2"]
    assert started(msgs)[0]["delay"] == 5.0


def test_at_most_max_cards_cards_on_screen():
    d = Director(Rules(max_cards=2))
    d.offer([make("stat_card", 50), make("player_tag", 50), make("rating_alert", 50)], now=0.0)
    assert {c["template"] for c in d.on_screen} == {"stat_card", "player_tag"} and d.waiting == 1
    assert sum(c["template"] in CARD_TEMPLATES for c in d.on_screen) <= 2


def test_lower_third_does_not_count_as_a_card_but_the_total_is_capped():
    d = Director(Rules(max_cards=2, max_total=3))
    d.offer([make("lower_third", 50), make("stat_card", 50), make("player_tag", 50), make("rating_alert", 50)], now=0.0)
    assert len(d.on_screen) == 3 and d.waiting == 1
    d2 = Director(Rules(max_cards=5, max_total=2))  # the total cap alone
    d2.offer([make("lower_third", 50), make("stat_card", 50), make("player_tag", 50)], now=0.0)
    assert len(d2.on_screen) == 2


def test_the_screen_never_breaks_the_limits_under_a_flood():
    d = Director()
    rules, t = d.rules, 0.0
    screen: set[str] = set()
    templates = ["lower_third", "stat_card", "player_tag", "rating_alert", "speed_popup"]
    for i in range(300):
        t += 0.7
        batch = [make(templates[(i + k) % 5], priority=(i * 37 + k * 11) % 100) for k in range(1 + i % 3)]
        for m in d.offer(batch, t):
            screen.add(m["cue"]["id"]) if m["type"] == "cue" else screen.discard(m["id"])
        on = d.on_screen
        assert {c["id"] for c in on} == screen
        assert len({c["template"] for c in on}) == len(on)
        assert sum(c["template"] in CARD_TEMPLATES for c in on) <= rules.max_cards and len(on) <= rules.max_total
        assert d.waiting <= rules.max_pending


# ---------------------------------------------------------------- pre-emption

def test_a_much_higher_priority_cue_pre_empts_after_the_minimum_hold():
    d = Director()
    d.offer([make(priority=60)], now=0.0)
    msgs = d.offer([make(priority=80)], now=5.0)
    assert ended(msgs) == [("C-1", "preempted")] and [c["id"] for c in started(msgs)] == ["C-2"]


def test_a_cue_that_just_appeared_is_not_pre_empted_until_the_minimum_hold():
    d = Director()
    d.offer([make(priority=60)], now=0.0)
    assert d.offer([make(priority=95)], now=0.5) == []  # waits, doesn't flash the first one away
    assert d.advance(3.9) == []  # a lower-third is held for 4 seconds
    msgs = d.advance(4.0)
    assert ended(msgs) == [("C-1", "preempted")] and started(msgs)[0]["delay"] == 3.5


def test_pre_emption_needs_the_margin():
    d = Director()
    d.offer([make(priority=60)], now=0.0)
    assert d.offer([make(priority=69)], now=5.0) == []
    assert ended(d.offer([make(priority=70)], now=5.0)) == [("C-1", "preempted")]  # equals the margin of 10


def test_pre_emption_takes_the_lowest_priority_card_when_the_card_limit_is_full():
    d = Director(Rules(max_cards=2))
    d.offer([make("stat_card", 40), make("player_tag", 55)], now=0.0)
    msgs = d.offer([make("rating_alert", 80)], now=3.0)
    assert ended(msgs) == [("C-1", "preempted")]
    assert {c["template"] for c in d.on_screen} == {"player_tag", "rating_alert"}


def test_pre_emption_can_push_off_more_than_one_cue():
    d = Director(Rules(max_cards=5, max_total=2))
    d.offer([make("stat_card", 20), make("player_tag", 25)], now=0.0)
    msgs = d.offer([make("lower_third", 90), make("rating_alert", 90)], now=3.0)
    assert len(d.on_screen) == 2 and {r for _, r in ended(msgs)} == {"preempted"}
    assert {c["template"] for c in d.on_screen} == {"lower_third", "rating_alert"}


def test_urgent_cues_replace_each_other_newest_first_after_the_hold():
    d = Director()
    d.offer([make(priority=98)], now=0.0)
    assert d.offer([make(priority=92)], now=1.0) == []  # two seconds later than the first: it must be held
    msgs = d.advance(4.0)
    assert ended(msgs) == [("C-1", "preempted")] and [c["id"] for c in started(msgs)] == ["C-2"]
    # an urgent cue never replaces something merely important, unless it outranks it by the margin
    d2 = Director()
    d2.offer([make(priority=95)], now=0.0)
    assert d2.offer([make(priority=89)], now=5.0) == []


def test_a_lower_priority_cue_never_displaces_a_higher_one():
    d = Director()
    d.offer([make("stat_card", 90)], now=0.0)
    d.offer([make("stat_card", 20)], now=5.0)
    assert [c["priority"] for c in d.on_screen] == [90]


# ---------------------------------------------------------------- cooldowns

def test_cooldown_between_cards_of_one_template():
    d = Director(Rules(cooldown={"stat_card": 20.0}))
    d.offer([make("stat_card", 50, duration=8.0)], now=0.0)
    assert d.advance(8.0) and d.on_screen == []
    assert d.offer([make("stat_card", 50)], now=10.0) == []  # 2 s after the last one ended: waiting
    assert started(d.advance(28.0)) == [] and d.waiting == 0  # ... and stale by then (max_delay 12)


def test_a_cooled_down_cue_starts_once_the_cooldown_is_over():
    d = Director(Rules(cooldown={"stat_card": 5.0}))
    d.offer([make("stat_card", 50, duration=8.0)], now=0.0)
    d.advance(8.0)
    d.offer([make("stat_card", 50)], now=9.0)
    assert started(d.advance(12.9)) == [] and [c["id"] for c in started(d.advance(13.0))] == ["C-2"]


def test_cooldown_does_not_apply_to_lower_thirds():
    d = Director()
    d.offer([make("lower_third", 50, duration=6.0)], now=0.0)
    d.advance(6.0)
    assert started(d.offer([make("lower_third", 50)], now=6.0))


def test_the_same_subject_has_a_longer_cooldown():
    d = Director(Rules(cooldown={}, topic_cooldown=45.0))
    d.offer([make("rating_alert", 50, duration=5.0, topic="rating_alert:POT-9")], now=0.0)
    d.advance(5.0)
    assert d.offer([make("rating_alert", 50, topic="rating_alert:POT-9")], now=10.0) == []
    assert started(d.offer([make("rating_alert", 50, topic="rating_alert:POT-4")], now=10.0))  # someone else: fine


def test_urgent_cues_skip_cooldowns_but_not_the_limits():
    d = Director(Rules(cooldown={"stat_card": 20.0}))
    d.offer([make("stat_card", 50, duration=8.0)], now=0.0)
    d.advance(8.0)
    assert started(d.offer([make("stat_card", 90)], now=9.0))
    d.offer([make("stat_card", 95)], now=9.5)  # one stat card on screen, equal-ish priority: still waits
    assert d.waiting == 1


def test_replacing_a_card_of_the_same_template_ignores_its_cooldown():
    d = Director(Rules(cooldown={"stat_card": 20.0}))
    d.offer([make("stat_card", 40)], now=0.0)
    msgs = d.offer([make("stat_card", 60)], now=3.0)
    assert ended(msgs) == [("C-1", "preempted")] and started(msgs)


# ---------------------------------------------------------------- the queue

def test_the_queue_is_served_highest_priority_first_then_oldest():
    d = Director(Rules(max_delay={"lower_third": 60.0}))
    d.offer([make(priority=90)], now=0.0)
    d.offer([make(priority=50)], now=1.0)
    d.offer([make(priority=60)], now=2.0)
    d.offer([make(priority=60)], now=3.0)
    order = []
    for t in (6.0, 12.0, 18.0, 24.0):
        order += [c["id"] for c in started(d.advance(t))]
    assert order == ["C-3", "C-4", "C-2"]


def test_a_waiting_cue_is_dropped_when_stale_not_shown_late():
    d = Director()
    d.offer([make(priority=90, duration=20.0)], now=0.0)
    d.offer([make(priority=50)], now=1.0)
    d.advance(9.5)
    assert d.waiting == 0 and d.dropped[-1]["reason"] == "stale"
    assert started(d.advance(20.0)) == []  # and it isn't shown late once the screen is free


def test_a_full_queue_drops_the_lowest_priority_cue():
    d = Director(Rules(max_pending=2))
    d.offer([make(priority=95, duration=20.0)], now=0.0)
    d.offer([make(priority=40), make(priority=45), make(priority=30)], now=1.0)
    assert d.waiting == 2
    assert d.dropped[-1]["reason"] == "queue_full" and d.dropped[-1]["priority"] == 30


def test_unknown_templates_are_refused():
    with pytest.raises(ValueError):
        Director().offer([make(template="confetti")], now=0.0)


def test_time_never_runs_backwards():
    d = Director()
    d.offer([make(duration=6.0)], now=10.0)
    assert d.advance(5.0) == []  # an older time changes nothing
    assert ended(d.advance(16.0)) == [("C-1", "expired")]


# ---------------------------------------------------------------- the screen clock

def test_show_clock_divides_match_time_by_the_speed():
    c = ShowClock()
    assert c.at(100.0, 20) == 0.0
    assert c.at(160.0, 20) == 3.0
    assert c.at(160.0, 20) == 3.0  # paused: the match clock didn't move
    assert c.at(220.0, 60) == 4.0  # a speed change applies to time that hasn't passed yet
    assert c.at(10.0, 60) == 4.0   # never backwards


# ---------------------------------------------------------------- determinism

def run(offers, now_step=0.7):
    d, log, t = Director(), [], 0.0
    for i, batch in enumerate(offers):
        t += now_step
        log += d.offer(batch, t)
        log += d.advance(t + 0.3)
    return log


def test_same_cues_at_the_same_times_give_the_same_messages():
    templates = ["lower_third", "stat_card", "player_tag", "rating_alert"]
    offers = [[make(templates[(i + k) % 4], priority=(i * 17 + k * 29) % 100, topic=f"{i % 3}") for k in range(i % 3 + 1)]
              for i in range(80)]
    assert run(offers) == run(offers) and len(run(offers)) > 40


def test_a_match_gives_the_same_cue_sheet_every_time():
    meta, events = read_match(SAMPLES / "red-card-CAU-POT.jsonl")
    first = cue_sheet(meta, events, pace=20)
    assert first == cue_sheet(meta, events, pace=20) and first


# ---------------------------------------------------------------- cues from moments

@pytest.fixture(scope="module")
def match():
    meta, events = read_match(SAMPLES / "comeback-POT-CAR.jsonl")
    return meta, events, cue_sheet(meta, events, pace=1)


def test_every_cue_has_the_documented_fields(match):
    _, _, sheet = match
    cues = [e["message"]["cue"] for e in sheet if e["message"]["type"] == "cue"]
    assert cues
    for c in cues:
        assert {"id", "time", "duration", "priority", "template", "tier", "detail", "about", "topic", "moment_id",
                "data"} <= set(c)
        assert 0 <= c["priority"] <= 100 and c["duration"] > 0 and c["detail"] in ("casual", "analyst")
        assert set(c["about"]) == {"team_id", "player_id"}


def test_goals_and_the_final_whistle_always_reach_the_screen(match):
    meta, events, sheet = match
    from pitch_insights.explain.moments import MatchBrain

    shown = {e["message"]["cue"]["moment_id"] for e in sheet
             if e["message"]["type"] == "cue" and e["message"]["cue"]["template"] == "lower_third"}
    brain = MatchBrain(meta)
    must = [m["id"] for ev in events for m in brain.update(ev)["moments"] if m["type"] in ("goal", "full_time")]
    assert len(must) >= 6 and set(must) <= shown


@pytest.mark.parametrize("name", ["comeback-POT-CAR", "thriller-CAR-BRO", "red-card-CAU-POT"])
@pytest.mark.parametrize("pace", [1, 20, 60])
def test_what_matters_reaches_the_screen_in_every_sample_at_every_speed(name, pace):
    from pitch_insights.explain.moments import MatchBrain

    meta, events = read_match(SAMPLES / f"{name}.jsonl")
    sheet = cue_sheet(meta, events, pace)
    shown = {(c["moment_id"], c["template"]) for c in (e["message"].get("cue") for e in sheet) if c}
    brain, must = MatchBrain(meta), []
    for ev in events:
        for m in brain.update(ev)["moments"]:
            if m["type"] in ("goal", "red_card", "full_time"):
                must.append((m["id"], "lower_third"))
            if m["type"] == "full_time":
                must.append((m["id"], "stat_card"))
    assert must and set(must) <= shown


def test_a_goal_gets_a_lower_third_and_a_player_tag(match):
    _, _, sheet = match
    cues = [e["message"]["cue"] for e in sheet if e["message"]["type"] == "cue"]
    goal = next(c for c in cues if c["template"] == "lower_third" and c["data"]["kind"] == "goal")
    tag = next(c for c in cues if c["template"] == "player_tag" and c["moment_id"] == goal["moment_id"])
    assert tag["about"]["player_id"] == goal["about"]["player_id"] and tag["data"]["name"] and tag["data"]["number"]
    assert goal["priority"] >= 80 and tag["priority"] < goal["priority"]


def test_full_time_gets_a_summary_stat_card(match):
    _, _, sheet = match
    cards = [e["message"]["cue"] for e in sheet if e["message"]["type"] == "cue" and e["message"]["cue"]["template"] == "stat_card"]
    summary = [c for c in cards if c["data"]["kind"] == "summary"]
    assert summary and {r["key"] for r in summary[0]["data"]["rows"]} >= {"possession_pct", "shots", "xg"}
    assert all(isinstance(r["home"], (int, float)) and isinstance(r["away"], (int, float)) for r in summary[0]["data"]["rows"])


def test_rating_alerts_are_for_analysts_and_low_priority(match):
    _, _, sheet = match
    alerts = [e["message"]["cue"] for e in sheet if e["message"]["type"] == "cue" and e["message"]["cue"]["template"] == "rating_alert"]
    assert alerts and all(a["detail"] == "analyst" and a["priority"] < 60 for a in alerts)
    assert all(a["data"]["direction"] in ("up", "down", "milestone") and a["data"]["rating"] for a in alerts)


def moment(**kw):
    base = {"id": "M-1", "type": "goal", "tier": "headline", "importance": 0.8, "match_time": 100.0, "clock": "2'",
            "team_id": "POT", "player_id": "POT-9", "player_name": "Dummy Name", "headline": "Dummy opens the scoring",
            "facts": [{"kind": "score", "text": "It's now POT 1-0 CAR."}, {"kind": "win_probability", "text": "Up to 60%."}]}
    return base | kw


META = {"home": {"id": "POT"}, "away": {"id": "CAR"}}


def test_commentary_text_comes_through_as_the_moment_carries_it():
    c = {"status": "ok", "casual": "Ein Tor!", "analyst": "Ein Tor mit xG 0.4."}
    lt = CueBuilder(META).for_moment(moment(commentary=c, headline="Dummy eröffnet das Spiel"), None)[0]
    assert lt["template"] == "lower_third"
    assert lt["data"]["headline"] == "Dummy eröffnet das Spiel" and lt["data"]["casual"] == "Ein Tor!"
    fallback = CueBuilder(META).for_moment(moment(commentary={"status": "fallback", "casual": "x", "analyst": "y"}), None)[0]
    assert fallback["data"]["casual"] is None and fallback["data"]["fact"] == "Up to 60%."


def test_minor_moments_get_no_lower_third_and_story_cues_cannot_outrank_a_goal():
    b = CueBuilder(META)
    assert b.for_moment(moment(type="momentum_swing", tier="minor", importance=0.2), None) == []
    story = b.for_moment(moment(type="milestone", tier="headline", importance=0.9, player_id=None), None)[0]
    goal = b.for_moment(moment(importance=0.9), None)[0]
    assert story["priority"] <= 70 < goal["priority"]


def test_longer_commentary_stays_up_longer_but_not_forever():
    b = CueBuilder(META)
    short = b.for_moment(moment(commentary={"status": "ok", "casual": "A goal.", "analyst": "A goal."}), None)[0]
    long_text = " ".join(["word"] * 60)
    long = b.for_moment(moment(commentary={"status": "ok", "casual": "A goal.", "analyst": long_text}), None)[0]
    assert short["duration"] == 6.0 and long["duration"] == 10.0


def test_speed_popup_cue():
    c = CueBuilder.speed_popup(120.0, "POT-7", "Some Player", 33.456, "POT")
    assert c["template"] == "speed_popup" and c["data"] == {"name": "Some Player", "speed_kmh": 33.5} and c["detail"] == "analyst"
    assert started(Director().offer([c], 0.0))


def test_cues_carry_what_a_per_viewer_filter_needs():
    c = CueBuilder(META).for_moment(moment(), None)
    assert all(x["about"] == {"team_id": "POT", "player_id": "POT-9"} and x["tier"] == "headline" for x in c)


def test_chinese_text_is_timed_by_its_characters_not_its_spaces():
    zh = "这是一个很长的句子，" * 8  # 72 characters, no spaces
    assert lower_third_seconds(zh, zh, None) > lower_third_seconds("Goal.", "Goal.", None) == 6.0
    assert lower_third_seconds(zh, None, None) >= 8.0


def test_ties_go_by_the_order_cues_were_offered_not_by_id_text():
    d = Director(Rules(max_cards=2, cooldown={}))
    for _ in range(8):  # use up C-1 to C-8, so the next two are C-9 and C-10
        d.offer([make("speed_popup", 10, duration=1.0)], now=d._now)
        d.advance(d._now + 1.0)
    d.offer([make("stat_card", 50), make("player_tag", 50)], now=d._now)
    ids = {c["template"]: c["id"] for c in d.on_screen}
    assert ids == {"stat_card": "C-9", "player_tag": "C-10"}
    msgs = d.offer([make("rating_alert", 90)], now=d._now + 3.0)
    assert ended(msgs) == [("C-9", "preempted")]  # the older of two equals, though "C-10" < "C-9" as text


def test_rules_that_leave_a_template_out_still_work():
    d = Director(Rules(max_delay={}, max_pending=2))
    d.offer([make(priority=90, duration=30.0)], now=0.0)
    d.offer([make(priority=50)], now=1.0)
    d.advance(20.0)
    assert d.waiting == 0 and d.dropped[-1]["reason"] == "stale"


def test_casual_viewers_do_not_get_analyst_cues_and_so_lose_no_slots():
    meta, events = read_match(SAMPLES / "comeback-POT-CAR.jsonl")
    casual = [e["message"]["cue"] for e in cue_sheet(meta, events, 60, detail="casual") if e["message"]["type"] == "cue"]
    analyst = [e["message"]["cue"] for e in cue_sheet(meta, events, 60) if e["message"]["type"] == "cue"]
    assert casual and all(c["detail"] == "casual" for c in casual) and any(c["detail"] == "analyst" for c in analyst)
    assert all(visible_to(c, "analyst") for c in analyst) and not all(visible_to(c, "casual") for c in analyst)
    assert any(c["template"] == "stat_card" and c["data"]["kind"] == "summary" for c in casual)
