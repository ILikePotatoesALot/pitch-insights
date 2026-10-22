"""Chat clients for each provider, and the Memory agent's embeddings client, all through the
OpenAI-compatible API.

Foundry deployments are reached through the resource's v1 API with an API key. At
deployment time this can move to keyless auth (managed identity); see docs/DESIGN.md.
"""

from __future__ import annotations

import ssl
from urllib.parse import urlsplit

import httpx
import truststore
from agent_framework_openai import OpenAIChatCompletionClient
from openai import AsyncOpenAI, OpenAI

from pitch_insights.agents.settings import AgentSettings


def ssl_context() -> ssl.SSLContext:
    """Verify certificates against the operating system's store, not Python's bundled list.

    Networks that inspect HTTPS add their own root certificate to the OS store, so the
    bundled list rejects them. Verification is never turned off.
    """
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def foundry_v1(endpoint: str) -> str:
    """A Foundry resource's v1 base URL. Accepts a resource URL or one copied with a path
    (e.g. /openai/v1/responses)."""
    url = urlsplit(endpoint)  # keep only scheme and host; a host may itself start with "openai"
    return f"{url.scheme}://{url.netloc}/openai/v1/"


def base_url(settings: AgentSettings) -> str:
    """The chat provider's v1 base URL."""
    if settings.provider != "foundry":
        return settings.endpoint.rstrip("/") + "/"
    return foundry_v1(settings.endpoint)


def make_chat_client(settings: AgentSettings) -> OpenAIChatCompletionClient:
    if not settings.configured:
        raise RuntimeError(f"the {settings.provider} provider isn't configured; fill in .env (see .env.example)")
    oai = AsyncOpenAI(
        base_url=base_url(settings), api_key=settings.api_key,
        timeout=settings.timeout_s, max_retries=settings.max_retries,
        http_client=httpx.AsyncClient(verify=ssl_context(), timeout=settings.timeout_s),
    )
    return OpenAIChatCompletionClient(model=settings.model, async_client=oai)


def make_embeddings_client(settings: AgentSettings) -> OpenAI:
    """The Memory agent's embeddings client: always the Foundry resource, whatever the chat provider."""
    if not settings.embeddings_configured:
        raise RuntimeError("embeddings aren't configured; fill in AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY "
                           "and AZURE_OPENAI_EMBEDDING_DEPLOYMENT in .env (see .env.example)")
    return OpenAI(
        base_url=foundry_v1(settings.embedding_endpoint), api_key=settings.embedding_api_key,
        timeout=settings.timeout_s, max_retries=settings.max_retries,
        http_client=httpx.Client(verify=ssl_context(), timeout=settings.timeout_s),
    )
