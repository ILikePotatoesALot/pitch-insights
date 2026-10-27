"""The generated exhibition uses the same translation source as its replay."""

import asyncio
import importlib.util
from pathlib import Path
import shutil

from fastapi.testclient import TestClient

from pitch_insights.agents.store import load_commentary, with_commentary
from pitch_insights.agents.translate import (
    LANGUAGES, TRANSLATION_VERSION, check, load_translations, moment_texts,
    names_for, _names_pattern, source_hash,
)
from pitch_insights.explain.simulation import prototype_moments
from pitch_insights.generator.continuous import NAME, prototype
from pitch_insights import server

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "translate_moments.py"


def translation_script():
    spec = importlib.util.spec_from_file_location("translate_simulation_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_and_explicit_translation_paths_include_the_virtual_exhibition(tmp_path, monkeypatch):
    script = translation_script()
    monkeypatch.setattr(script, "SAMPLES", tmp_path)
    path = tmp_path / f"{NAME}.jsonl"
    assert script.sample_paths([NAME]) == [path]
    assert script.sample_paths([]).count(path) == 1
    path.touch()  # a later export must not add the same match twice
    assert script.sample_paths([]).count(path) == 1


def test_translation_generation_needs_no_source_file_or_model_and_reuses_unchanged_text(tmp_path, monkeypatch):
    script = translation_script()
    monkeypatch.setattr(script, "SAMPLES", tmp_path)
    path = tmp_path / f"{NAME}.jsonl"
    shutil.copy(SAMPLES / f"{NAME}.commentary.json", tmp_path)

    def no_file(*args):
        raise AssertionError("the exhibition is generated, not loaded from a JSONL file")

    monkeypatch.setattr(script, "read_match", no_file)

    class FakeTranslator:
        characters = 0
        calls = 0

        async def translate(self, texts, languages):
            self.calls += 1
            self.characters += sum(map(len, texts)) * len(languages)
            return [{lang: f"{lang}: {text}" for lang in languages} for text in texts]

    translator = FakeTranslator()
    asyncio.run(script.run_match(path, translator))
    assert not path.exists()
    saved = load_translations(path)
    assert saved["version"] == TRANSLATION_VERSION
    assert len(saved["moments"]) == len(prototype_moments())
    assert all(entry.get("de", {}).get("headline", "").startswith("de:") for entry in saved["moments"].values())
    calls, characters = translator.calls, translator.characters
    assert calls and characters
    asyncio.run(script.run_match(path, translator))
    assert (translator.calls, translator.characters) == (calls, characters)


def test_stored_exhibition_translations_match_current_evidence_and_keep_names_and_numbers():
    meta = prototype()[0]
    path = SAMPLES / f"{NAME}.jsonl"
    commentary = load_commentary(path)
    saved = load_translations(path)
    assert saved.get("version") == TRANSLATION_VERSION
    assert set(saved["languages"]) == set(LANGUAGES)
    assert set(saved["moments"]) == {moment["id"] for moment in prototype_moments()}
    pattern = _names_pattern(names_for(meta))
    for moment in prototype_moments():
        texts = moment_texts(with_commentary(moment, commentary, meta))
        entry = saved["moments"][moment["id"]]
        assert entry["source_hash"] == source_hash(texts)
        for lang in LANGUAGES:
            assert entry[lang]["headline"] != texts["headline"]
            for key, translated in entry[lang].items():
                assert not check(texts[key], translated, pattern), (moment["id"], lang, key)


def test_exhibition_language_selection_translates_catchup_and_live_goal_overlays():
    _, events, _ = prototype()
    path = SAMPLES / f"{NAME}.jsonl"
    stored = load_translations(path)
    goal = next(event for event in events if event["type"] == "shot" and event["outcome"] == "goal")
    moment = next(moment for moment in prototype_moments() if moment["type"] == "goal")
    for lang in LANGUAGES:
        translated = stored["moments"][moment["id"]][lang]
        with TestClient(server.app).websocket_connect(
            f"/ws/replay/{NAME}?at={goal['t'] - 0.4}&speed=5&mode=analyst&lang={lang}"
        ) as ws:
            info = ws.receive_json()
            assert info["lang"] == lang and set(info["languages"]) == {"en", *LANGUAGES}
            messages = []
            while True:
                message = ws.receive_json()
                messages.append(message)
                if message["type"] == "frame" and message["t"] >= goal["t"] + 1:
                    break
        catchup = next(message for message in messages if message["type"] == "catchup")
        assert catchup["moments"] and all(item["lang"] == lang for item in catchup["moments"])
        live = next(message["moment"] for message in messages if message["type"] == "moment"
                    and message["moment"]["id"] == moment["id"])
        assert live["headline"] == translated["headline"]
        assert live["commentary"]["analyst"] == translated["analyst"]
        goal_cue = next(message["cue"] for message in messages if message["type"] == "cue"
                        and message["cue"]["template"] == "lower_third"
                        and message["cue"]["moment_id"] == moment["id"])
        assert goal_cue["data"]["analyst"] == translated["analyst"]
