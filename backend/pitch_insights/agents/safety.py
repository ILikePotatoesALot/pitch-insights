"""Safety check: Azure AI Content Safety screens every line before it can reach the screen.

Runs after the groundedness check. Text is scored in four harm categories (hate, self-harm,
sexual, violence) at severity 0, 2, 4 or 6. A line at or above the blocking level in any
category falls back to the Moment Scorer's plain headline, like a line that isn't grounded.

Fails closed: if the service can't be reached or answers with an error, the line isn't shown
(the plain headline is), because an unchecked line mustn't reach a viewer.

Called over plain REST (api-version 2024-09-01), so it needs no extra package:
https://learn.microsoft.com/en-us/rest/api/contentsafety/text-operations/analyze-text
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

import httpx

from pitch_insights.agents.clients import ssl_context

log = logging.getLogger("pitch_insights.agents")

API_VERSION = "2024-09-01"
CATEGORIES = ("Hate", "SelfHarm", "Sexual", "Violence")
MAX_CHARS = 10_000  # the service's limit per request
MAX_RETRIES = 4


@dataclass
class SafetyResult:
    passed: bool
    severities: dict[str, int] = field(default_factory=dict)  # category -> 0, 2, 4 or 6
    flagged: list[str] = field(default_factory=list)          # categories at or above the blocking level
    error: str | None = None                                  # why the check couldn't run (fails closed)

    def to_dict(self) -> dict:
        return {"passed": self.passed, "severities": self.severities, "flagged": self.flagged,
                "error": self.error, "service": "azure-content-safety", "api_version": API_VERSION}

    @property
    def reason(self) -> str:
        if self.error:
            return f"safety check unavailable ({self.error})"
        return "content safety: " + ", ".join(f"{c} {self.severities[c]}" for c in self.flagged)


class ContentSafety:
    def __init__(self, endpoint: str, key: str, block_at: int = 2, timeout_s: float = 10.0,
                 client: httpx.AsyncClient | None = None):
        self.url = endpoint.rstrip("/") + f"/contentsafety/text:analyze?api-version={API_VERSION}"
        self._key = key
        self.block_at = block_at
        self.client = client or httpx.AsyncClient(verify=ssl_context(), timeout=timeout_s)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def _post(self, text: str) -> httpx.Response:
        """One request, retried on 429 and 5xx with backoff that honours Retry-After (the free
        tier allows only a few requests a second)."""
        for attempt in range(MAX_RETRIES + 1):
            r = await self.client.post(self.url, headers={"Ocp-Apim-Subscription-Key": self._key},
                                       json={"text": text[:MAX_CHARS], "categories": list(CATEGORIES),
                                             "outputType": "FourSeverityLevels"})
            if (r.status_code != 429 and r.status_code < 500) or attempt == MAX_RETRIES:
                return r
            try:
                wait = float(r.headers.get("Retry-After", ""))
            except ValueError:
                wait = 2 ** attempt
            await asyncio.sleep(min(wait, 30.0))
        return r

    async def check(self, text: str) -> SafetyResult:
        try:
            r = await self._post(text)
            r.raise_for_status()
            severities = {c["category"]: int(c.get("severity") or 0) for c in r.json()["categoriesAnalysis"]}
        except httpx.HTTPStatusError as e:
            return SafetyResult(False, error=f"HTTP {e.response.status_code}")
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as e:
            return SafetyResult(False, error=type(e).__name__)
        flagged = [c for c in CATEGORIES if severities.get(c, 0) >= self.block_at]
        return SafetyResult(not flagged, severities, flagged)


def safety_from_settings(settings) -> ContentSafety | None:
    """The configured service, or None if .env has no Content Safety values."""
    if not (settings.safety_endpoint and settings.safety_key):
        return None
    return ContentSafety(settings.safety_endpoint, settings.safety_key, settings.safety_block_at, settings.timeout_s)
