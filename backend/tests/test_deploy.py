"""What the Azure deployment adds to the replay server: viewer profiles, the allowed origins, a lean import set."""

import asyncio
import subprocess
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

from pitch_insights import profiles
from pitch_insights.origins import origin_allowed
from pitch_insights.server import app

PROFILE = {"version": 1, "mode": "casual", "lang": "de", "team": "POT", "player": "POT-11", "focus": "xg"}
SWA = "https://happy-sea-0123.1.azurestaticapps.net"


@pytest.fixture
def store():
    memory = profiles.MemoryProfileStore()
    app.dependency_overrides[profiles.get_store] = lambda: memory
    profiles._hits.clear()
    yield memory
    app.dependency_overrides.clear()


@pytest.fixture
def client(store):
    return TestClient(app)


def vid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------- the profile API

def test_a_profile_round_trips_and_is_forgotten(client):
    v = vid()
    assert client.get(f"/api/profile/{v}").status_code == 404
    assert client.put(f"/api/profile/{v}", json=PROFILE).status_code == 204
    r = client.get(f"/api/profile/{v}")
    assert r.json() == PROFILE and r.headers["cache-control"] == "no-store"
    assert client.delete(f"/api/profile/{v}").status_code == 204
    assert client.get(f"/api/profile/{v}").status_code == 404
    assert client.delete(f"/api/profile/{v}").status_code == 204  # forgetting twice is fine


def test_an_empty_choice_is_stored_as_none(client):
    v = vid()
    client.put(f"/api/profile/{v}", json={"mode": "analyst", "lang": "en"})
    assert client.get(f"/api/profile/{v}").json() == {"version": 1, "mode": "analyst", "lang": "en",
                                                      "team": None, "player": None, "focus": None}


@pytest.mark.parametrize("bad", [
    {**PROFILE, "mode": "expert"},
    {**PROFILE, "lang": "xx"},
    {**PROFILE, "team": "pot"},
    {**PROFILE, "player": "POT-"},
    {**PROFILE, "focus": "goals"},
    {**PROFILE, "name": "Austin"},                 # nothing but the five choices is kept
    {**PROFILE, "email": "a@example.com"},
    {k: v for k, v in PROFILE.items() if k != "mode"},
])
def test_only_the_five_choices_are_accepted(client, store, bad):
    assert client.put(f"/api/profile/{vid()}", json=bad).status_code == 422
    assert store.items == {}


@pytest.mark.parametrize("viewer", ["me", "1", "../../etc", "ABCDEF12-0000-0000-0000-000000000000", "x" * 200])
def test_a_viewer_id_must_be_a_uuid(client, store, viewer):
    assert client.put(f"/api/profile/{viewer}", json=PROFILE).status_code in (404, 405)
    assert store.items == {}


def test_without_storage_the_api_says_so():
    app.dependency_overrides[profiles.get_store] = lambda: None
    try:
        r = TestClient(app).get(f"/api/profile/{vid()}")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 503  # the app falls back to the browser's copy


def test_a_failing_store_is_a_503_that_says_nothing_about_why(client, store):
    class Broken:
        async def get(self, viewer_id):
            raise RuntimeError("secret endpoint details")
    app.dependency_overrides[profiles.get_store] = lambda: Broken()
    r = client.get(f"/api/profile/{vid()}")
    assert r.status_code == 503 and "secret" not in r.text


def test_one_address_is_limited(client, store, monkeypatch):
    monkeypatch.setattr(profiles, "RATE_LIMIT", 3)
    v = vid()
    codes = [client.get(f"/api/profile/{v}", headers={"x-forwarded-for": "9.9.9.9"}).status_code for _ in range(4)]
    assert codes == [404, 404, 404, 429]
    assert client.get(f"/api/profile/{v}", headers={"x-forwarded-for": "8.8.8.8"}).status_code == 404  # another address
    # only the address the ingress saw counts: a client can't dodge the limit by adding its own header values
    assert client.get(f"/api/profile/{v}", headers={"x-forwarded-for": "1.1.1.1, 9.9.9.9"}).status_code == 429


# ---------------------------------------------------------------- Cosmos DB, with a fake container

class FakeContainer:
    def __init__(self):
        self.items: dict[str, dict] = {}

    async def read_item(self, item, partition_key):
        from azure.cosmos.exceptions import CosmosResourceNotFoundError
        assert partition_key == item  # one document per viewer, partitioned by the viewer's own id
        if item not in self.items:
            raise CosmosResourceNotFoundError(status_code=404, message="not found")
        return self.items[item]

    async def upsert_item(self, body):
        self.items[body["id"]] = body

    async def delete_item(self, item, partition_key):
        from azure.cosmos.exceptions import CosmosResourceNotFoundError
        assert partition_key == item
        if self.items.pop(item, None) is None:
            raise CosmosResourceNotFoundError(status_code=404, message="not found")


def test_cosmos_store_keeps_the_choices_and_a_time_to_live_and_nothing_else():
    cosmos = profiles.CosmosProfileStore("https://example.documents.azure.com:443/", "db", "profiles")
    cosmos._container = FakeContainer()
    v = vid()

    async def go():
        assert await cosmos.get(v) is None
        await cosmos.put(v, PROFILE)
        doc = cosmos._container.items[v]
        assert set(doc) == {"id", "profile", "ttl", "updated"} and doc["ttl"] == profiles.PROFILE_TTL_S
        assert await cosmos.get(v) == PROFILE
        await cosmos.delete(v)
        await cosmos.delete(v)  # already gone: fine
        assert await cosmos.get(v) is None

    asyncio.run(go())


def test_the_environment_picks_the_store(monkeypatch):
    def fresh(**env):
        for k in ("COSMOS_ENDPOINT", "PITCH_PROFILE_STORE"):
            monkeypatch.delenv(k, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setattr(profiles, "_configured", False)
        monkeypatch.setattr(profiles, "_store", None)
        return profiles.get_store()

    assert fresh() is None
    assert isinstance(fresh(PITCH_PROFILE_STORE="memory"), profiles.MemoryProfileStore)
    cosmos = fresh(COSMOS_ENDPOINT="https://x.documents.azure.com:443/", PITCH_PROFILE_STORE="memory")
    assert isinstance(cosmos, profiles.CosmosProfileStore)  # Cosmos wins; creating it connects to nothing yet
    assert (cosmos.database, cosmos.container_name) == ("pitch-insights", "profiles")


# ---------------------------------------------------------------- who may call the server

def test_origins(monkeypatch):
    monkeypatch.setenv("PITCH_ALLOWED_ORIGINS", f"{SWA}/, https://other.example")
    assert origin_allowed(None)                                  # not a web page
    assert origin_allowed(SWA) and origin_allowed("https://other.example")
    for dev in ("http://localhost:5173", "http://127.0.0.1:8001", "http://localhost", "http://[::1]:5173"):
        assert origin_allowed(dev)
    for bad in ("https://evil.example", f"{SWA}.evil.example", "http://localhost.evil.example",
                "https://localhost.evil.example:5173", "http://localhost:5173@evil.example", "null"):
        assert not origin_allowed(bad), bad


def test_the_replay_refuses_a_page_from_another_origin(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/replay/comeback-POT-CAR?speed=600",
                                      headers={"origin": "https://evil.example"}):
            pass
    with client.websocket_connect("/ws/replay/comeback-POT-CAR?speed=600&from=95",
                                  headers={"origin": "http://localhost:5173"}) as ws:
        assert ws.receive_json()["type"] == "meta"


def test_cors_headers_go_only_to_the_allowed_origins(client):
    ok = client.options(f"/api/profile/{vid()}", headers={"origin": "http://localhost:5173",
                        "access-control-request-method": "PUT", "access-control-request-headers": "content-type"})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "PUT" in ok.headers["access-control-allow-methods"]
    bad = client.get("/api/matches", headers={"origin": "https://evil.example"})
    assert "access-control-allow-origin" not in bad.headers
    assert client.options("/api/matches", headers={"origin": "https://evil.example",
                          "access-control-request-method": "GET"}).status_code == 400


# ---------------------------------------------------------------- the image's dependencies

def test_the_server_imports_without_the_model_packages():
    """The container image leaves out Agent Framework and openai: the server must not need them."""
    code = ("import sys\n"
            "for m in ('openai', 'agent_framework', 'agent_framework_openai', 'azure.ai.evaluation'): sys.modules[m] = None\n"
            "import pitch_insights.server\n"
            "print('ok')")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "ok", out.stderr
