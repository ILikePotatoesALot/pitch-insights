"""Azure AI services around the agents: Content Safety, Translator and tracing.
No network: the services are faked with httpx's MockTransport."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from pitch_insights.agents import clients, translate
from pitch_insights.agents.desk import CommentaryDesk, Lines
from pitch_insights.agents.safety import ContentSafety, SafetyResult
from pitch_insights.agents.settings import AgentSettings
from pitch_insights.agents.store import summarise
from pitch_insights.agents.tracing import setup_tracing
from pitch_insights.agents.translate import (
    LANGUAGES, Translator, _names_pattern, check, moment_texts, protect, source_hash, translated_moment, unprotect,
)
from pitch_insights.explain.moments import MatchBrain
from pitch_insights.generator.io import read_match

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "comeback-POT-CAR.jsonl"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="module")
def match():
    meta, events = read_match(SAMPLE)
    brain = MatchBrain(meta)
    for ev in events:
        brain.update(ev)
    return meta, brain.moments


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Retries and pacing wait for real; tests don't."""
    async def instant(_):
        return None
    monkeypatch.setattr(clients.asyncio, "sleep", instant)
    monkeypatch.setattr(translate.asyncio, "sleep", instant)


def mock(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def severities(**s):
    return {"categoriesAnalysis": [{"category": c, "severity": s.get(c, 0)}
                                   for c in ("Hate", "SelfHarm", "Sexual", "Violence")]}


# ---------------------------------------------------------------- Content Safety

def test_clean_text_passes_and_harmful_text_is_blocked():
    replies = [severities(), severities(Violence=2), severities(Hate=6)]
    cs = ContentSafety("https://cs.example/", "key", block_at=2,
                       client=mock(lambda req: httpx.Response(200, json=replies.pop(0))))
    assert run(cs.check("What a goal")).passed
    blocked = run(cs.check("..."))
    assert not blocked.passed and blocked.flagged == ["Violence"] and "Violence 2" in blocked.reason
    assert run(cs.check("...")).flagged == ["Hate"]


def test_blocking_level_is_respected():
    cs = ContentSafety("https://cs.example/", "key", block_at=4,
                       client=mock(lambda req: httpx.Response(200, json=severities(Violence=2))))
    assert run(cs.check("a crunching tackle")).passed


def test_safety_fails_closed_when_the_service_does():
    def boom(req):
        raise httpx.ConnectError("down")
    assert not run(ContentSafety("https://cs.example/", "k", client=mock(boom)).check("x")).passed
    res = run(ContentSafety("https://cs.example/", "k", client=mock(lambda r: httpx.Response(401))).check("x"))
    assert not res.passed and res.error == "HTTP 401" and "unavailable" in res.reason


def test_rate_limits_are_retried_then_succeed():
    calls = []

    def handler(req):
        calls.append(req)
        if len(calls) < 3:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json=severities())
    assert run(ContentSafety("https://cs.example/", "k", client=mock(handler)).check("x")).passed
    assert len(calls) == 3
    assert calls[0].headers["Ocp-Apim-Subscription-Key"] == "k"
    assert json.loads(calls[0].content)["outputType"] == "FourSeverityLevels"


class FakeWriter:
    provider, model = "fake", "fake-model"

    def __init__(self, lines):
        self.lines = lines

    async def write(self, role, prompt):
        return self.lines


class FakeSafety:
    def __init__(self, passed):
        self.passed, self.checked = passed, []

    async def check(self, text):
        self.checked.append(text)
        return SafetyResult(self.passed, {"Violence": 0 if self.passed else 4},
                            [] if self.passed else ["Violence"])


def test_grounded_lines_are_screened_and_blocked_ones_fall_back(match):
    meta, moments = match
    goal = [m for m in moments if m["type"] == "goal"][-1]
    lines = Lines(casual="Carrot FC win it late.", analyst="Carrot FC win it late.")
    ok = run(CommentaryDesk(FakeWriter(lines), meta, safety=FakeSafety(True)).comment(goal))
    assert ok["status"] == "ok" and ok["safety"]["passed"]
    safety = FakeSafety(False)
    blocked = run(CommentaryDesk(FakeWriter(lines), meta, safety=safety).comment(goal))
    assert blocked["status"] == "fallback" and blocked["casual"] == goal["headline"] + "."
    assert blocked["reason"] == "content safety: Violence 4" and safety.checked == ["Carrot FC win it late.\nCarrot FC win it late."]


def test_ungrounded_lines_are_not_sent_to_the_safety_check(match):
    meta, moments = match
    goal = [m for m in moments if m["type"] == "goal"][-1]
    safety = FakeSafety(True)
    rec = run(CommentaryDesk(FakeWriter(Lines(casual="He scores 7 goals.", analyst="x")), meta, safety=safety).comment(goal))
    assert rec["status"] == "fallback" and safety.checked == [] and rec["safety"] is None


def test_stored_records_are_screened_once_without_the_model(match):
    meta, moments = match
    goal = [m for m in moments if m["type"] == "goal"][-1]
    desk = CommentaryDesk(FakeWriter(None), meta, safety=FakeSafety(False))
    old = {"moment_id": goal["id"], "status": "ok", "casual": "a", "analyst": "b", "attempts": 1}
    screened = run(desk.screen(old, goal))
    assert screened["status"] == "fallback" and screened["safety"]["passed"] is False
    already = old | {"safety": {"passed": True}}
    assert run(desk.screen(already, goal)) is already


def test_summary_counts_safety():
    recs = [{"status": "ok", "attempts": 1, "grounding": {"score": 1.0}, "safety": {"passed": True}},
            {"status": "fallback", "attempts": 1, "grounding": None, "safety": {"passed": False}},
            {"status": "ok", "attempts": 1, "grounding": None}]
    s = summarise(recs)
    assert s["safety_checked"] == 2 and s["safety_blocked"] == 1


# ---------------------------------------------------------------- Translator

PATTERN = _names_pattern(["Potato FC", "Potato", "Madekuta"])


def test_names_and_clocks_are_protected_longest_first():
    html_text = protect("Madekuta scores for Potato FC at 45+2' & 6', 2–1.", PATTERN)
    assert '<span class="notranslate">Potato FC</span>' in html_text
    assert '<span class="notranslate">45+2\'</span>' in html_text and "&amp;" in html_text
    assert unprotect(html_text) == "Madekuta scores for Potato FC at 45+2' & 6', 2–1."


def test_spaces_dropped_next_to_names_are_put_back_except_in_chinese():
    s = 'Das ist <span class="notranslate">Potato</span>zweite Phase'
    assert unprotect(s, "de") == "Das ist Potato zweite Phase"
    assert unprotect('<span class="notranslate">Potato</span>的动量', "zh-Hans") == "Potato的动量"


def test_check_reads_numbers_in_every_language():
    assert check("xG 3.88 for Potato", "xG 3,88 für Potato", PATTERN) == []         # decimal comma
    assert check("Potato momentum 0.75", "Potato的动量高0.75", PATTERN) == []          # no space in Chinese
    assert check("His 3rd goal for Potato.", "Sein drittes Tor für Potato.", PATTERN) == []  # ordinal as a word
    assert check("Potato lead 2-1", "Patate mène 2-1", PATTERN) == ["Potato"]          # a name was translated
    assert check("Potato at 6'", "Potato auf 1,80 m", PATTERN) == ["6'", "6"]          # a clock became feet


def test_translator_batches_and_counts_characters():
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append((len(body), [v for k, v in req.url.params.multi_items() if k == "to"]))
        return httpx.Response(200, json=[{"translations": [{"to": lang, "text": f"[{lang}]{item['Text']}"}
                                                           for lang in ("de", "fr")]} for item in body])
    t = Translator("https://tr.example/", "k", client=mock(handler))
    out = run(t.translate(["a" * 600, "b" * 600, "c"], ["de", "fr"]))
    assert [o["de"] for o in out] == ["[de]" + "a" * 600, "[de]" + "b" * 600, "[de]c"]
    assert seen == [(1, ["de", "fr"]), (2, ["de", "fr"])]  # 1,000 source characters per request at most
    assert t.characters == 1201 * 2


def test_translated_moments_only_use_translations_of_the_same_text(match):
    meta, moments = match
    m = moments[0]
    texts = moment_texts(m)
    entry = {"source_hash": source_hash(texts), "de": {"headline": "Überschrift"}}
    de = translated_moment(m, entry, "de")
    assert de["headline"] == "Überschrift" and de["lang"] == "de"
    assert de["facts"] == m["facts"]                                # missing keys stay English
    assert translated_moment(m, entry | {"source_hash": "old"}, "de") is m  # English changed: stale
    assert translated_moment(m, entry, "xx") is m and set(LANGUAGES) == {"es", "fr", "de", "nl", "zh-Hans"}


# ---------------------------------------------------------------- tracing and the server

def test_tracing_is_off_without_a_connection_string():
    assert setup_tracing(AgentSettings()) is False


def test_server_falls_back_to_english_for_unknown_languages():
    from fastapi.testclient import TestClient

    from pitch_insights.server import app

    with TestClient(app).websocket_connect("/ws/replay/comeback-POT-CAR?speed=600&from=95&lang=klingon") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "meta" and msg["lang"] == "en" and msg["languages"]["en"] == "English"
