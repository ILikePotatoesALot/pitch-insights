"""Viewer profiles: the five choices a viewer makes, kept per anonymous viewer id.

GET    /api/profile/{viewer_id}     the saved choices, or 404
PUT    /api/profile/{viewer_id}     save them (the body is the app's Profile)
DELETE /api/profile/{viewer_id}     forget them

A viewer id is a random UUID the browser makes for itself (nothing links it to a person) and is the Cosmos DB
document id and partition key, so each call is one point read or write (1 RU for a 1 KB read). The document holds
only the choices (club, player, mode, language, focus metric) and a time to live, so an unused profile is deleted
by Cosmos DB 90 days after its last save. No name, email, IP address or history is stored.

Storage, in order of preference:
  COSMOS_ENDPOINT set          Cosmos DB for NoSQL, signed in with the Container App's managed identity (Microsoft
                               Entra ID through DefaultAzureCredential, never an account key). COSMOS_DATABASE and
                               COSMOS_CONTAINER default to "pitch-insights" and "profiles"; the container's
                               partition key is /id and its time to live is switched on.
  PITCH_PROFILE_STORE=memory   in this process only, for development and tests
  neither                      503, and the app keeps profiles in the browser (its fallback)

The app treats any failure here as "use the browser's copy", so the replay never depends on this.
Follows Microsoft's guidance: https://learn.microsoft.com/azure/cosmos-db/nosql/how-to-grant-data-plane-access
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections import deque
from datetime import datetime, timezone
from typing import Annotated, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, StringConstraints

from pitch_insights.agents.translate import LANGUAGES
from pitch_insights.director.personalise import FOCUS_METRICS, MODES

log = logging.getLogger("pitch_insights.profiles")

PROFILE_TTL_S = 90 * 24 * 3600
VIEWER_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
RATE_LIMIT = 60   # calls a minute from one address; the free tier's 1,000 RU/s is shared by every viewer
RATE_WINDOW_S = 60.0

Language = Literal[("en", *LANGUAGES)]  # type: ignore[valid-type]
Club = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2,5}$")]
Player = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2,5}-[0-9]{1,3}$")]


class ProfileBody(BaseModel):
    """A viewer's choices, as the app's `Profile` (frontend/src/types.ts). Anything else is refused."""

    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    mode: Literal[MODES]  # type: ignore[valid-type]
    lang: Language
    team: Club | None = None
    player: Player | None = None
    focus: Literal[FOCUS_METRICS] | None = None  # type: ignore[valid-type]


class ProfileStore(Protocol):
    async def get(self, viewer_id: str) -> dict | None: ...
    async def put(self, viewer_id: str, profile: dict) -> None: ...
    async def delete(self, viewer_id: str) -> None: ...


class MemoryProfileStore:
    """Profiles kept in this process: for development, and the tests."""

    def __init__(self) -> None:
        self.items: dict[str, dict] = {}

    async def get(self, viewer_id: str) -> dict | None:
        return self.items.get(viewer_id)

    async def put(self, viewer_id: str, profile: dict) -> None:
        self.items[viewer_id] = profile

    async def delete(self, viewer_id: str) -> None:
        self.items.pop(viewer_id, None)


class CosmosProfileStore:
    """Cosmos DB for NoSQL through the async SDK, authenticated with Microsoft Entra ID.

    On Container Apps `DefaultAzureCredential` finds the managed identity (the user-assigned one is named by
    AZURE_CLIENT_ID); on a laptop it uses whoever is signed in to the Azure CLI or Visual Studio Code.
    """

    def __init__(self, endpoint: str, database: str, container: str) -> None:
        self.endpoint, self.database, self.container_name = endpoint, database, container
        self._client = None
        self._credential = None
        self._container = None
        self._lock = asyncio.Lock()

    async def _open(self):
        async with self._lock:
            if self._container is None:
                from azure.cosmos.aio import CosmosClient
                from azure.identity.aio import DefaultAzureCredential

                self._credential = DefaultAzureCredential()
                self._client = CosmosClient(self.endpoint, credential=self._credential)
                self._container = self._client.get_database_client(self.database).get_container_client(self.container_name)
        return self._container

    async def get(self, viewer_id: str) -> dict | None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        container = await self._open()
        try:
            item = await container.read_item(item=viewer_id, partition_key=viewer_id)
        except CosmosResourceNotFoundError:
            return None
        return item.get("profile")

    async def put(self, viewer_id: str, profile: dict) -> None:
        container = await self._open()
        await container.upsert_item({"id": viewer_id, "profile": profile, "ttl": PROFILE_TTL_S,
                                     "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")})

    async def delete(self, viewer_id: str) -> None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        container = await self._open()
        try:
            await container.delete_item(item=viewer_id, partition_key=viewer_id)
        except CosmosResourceNotFoundError:
            pass

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            await self._credential.close()
            self._client = self._credential = self._container = None


_store: ProfileStore | None = None
_configured = False


def get_store() -> ProfileStore | None:
    """The store the environment asks for (made on first use), or None if there isn't one."""
    global _store, _configured
    if not _configured:
        _configured = True
        endpoint = os.getenv("COSMOS_ENDPOINT", "").strip()
        if endpoint:
            _store = CosmosProfileStore(endpoint, os.getenv("COSMOS_DATABASE", "pitch-insights"),
                                        os.getenv("COSMOS_CONTAINER", "profiles"))
        elif os.getenv("PITCH_PROFILE_STORE", "").strip().lower() == "memory":
            _store = MemoryProfileStore()
    return _store


async def close_store() -> None:
    if isinstance(_store, CosmosProfileStore):
        await _store.close()


# A sliding window per client address (the address Container Apps' ingress saw, which is the last one in
# X-Forwarded-For), kept in memory: the Throttling pattern, so one client can't use up the shared throughput.
_hits: dict[str, deque[float]] = {}


def _throttle(request: Request) -> None:
    ip = request.headers.get("x-forwarded-for", "").split(",")[-1].strip() or (request.client.host if request.client else "")
    now = time.monotonic()
    if len(_hits) > 5000:  # drop the quiet ones so the table can't grow without end
        for key in [k for k, q in _hits.items() if not q or q[-1] < now - RATE_WINDOW_S]:
            del _hits[key]
    q = _hits.setdefault(ip, deque())
    while q and q[0] < now - RATE_WINDOW_S:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        raise HTTPException(429, "too many requests", headers={"Retry-After": str(int(RATE_WINDOW_S))})
    q.append(now)


def _viewer(viewer_id: str) -> str:
    if not VIEWER_ID.match(viewer_id):
        raise HTTPException(404, "no such viewer")
    return viewer_id


def _storage(store: ProfileStore | None = Depends(get_store)) -> ProfileStore:
    if store is None:
        raise HTTPException(503, "profile storage isn't set up here")
    return store


router = APIRouter(prefix="/api/profile", dependencies=[Depends(_throttle)])


async def _guarded(call):
    """Run a store call; a failure is logged by type only (nothing from the request or the service) and becomes a 503."""
    try:
        return await call
    except HTTPException:
        raise
    except Exception as e:
        log.warning("profile store failed: %s", type(e).__name__)
        raise HTTPException(503, "profile storage is unavailable") from e


@router.get("/{viewer_id}")
async def read_profile(viewer_id: str, response: Response, store: ProfileStore = Depends(_storage)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    profile = await _guarded(store.get(_viewer(viewer_id)))
    if profile is None:
        raise HTTPException(404, "no saved profile")
    return profile


@router.put("/{viewer_id}", status_code=204)
async def save_profile(viewer_id: str, body: ProfileBody, store: ProfileStore = Depends(_storage)) -> Response:
    await _guarded(store.put(_viewer(viewer_id), body.model_dump()))
    return Response(status_code=204)


@router.delete("/{viewer_id}", status_code=204)
async def forget_profile(viewer_id: str, store: ProfileStore = Depends(_storage)) -> Response:
    await _guarded(store.delete(_viewer(viewer_id)))
    return Response(status_code=204)
