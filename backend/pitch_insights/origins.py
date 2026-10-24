"""Which web pages may call the replay server.

The deployed app is a static site on its own origin (https://<name>.azurestaticapps.net), so the browser makes
cross-origin calls to the Container App. Only that origin and localhost (development, on any port) are let in:

  PITCH_ALLOWED_ORIGINS   comma-separated origins, e.g. https://happy-sea-0123.1.azurestaticapps.net

CORS covers `fetch`. A browser doesn't apply it to a WebSocket, so the replay endpoint checks the `Origin` header
itself (`origin_allowed`). Requests with no Origin header (curl, a server, a test) aren't from a web page and pass.
Follows Microsoft's CORS guidance for Container Apps: list the origins, never `*`.
https://learn.microsoft.com/azure/container-apps/cors
"""

from __future__ import annotations

import os
import re

LOCALHOST = r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?"
_LOCALHOST = re.compile(LOCALHOST + r"\Z")


def configured_origins() -> list[str]:
    """The origins named in PITCH_ALLOWED_ORIGINS, without trailing slashes."""
    return [o.strip().rstrip("/") for o in os.getenv("PITCH_ALLOWED_ORIGINS", "").split(",") if o.strip()]


def origin_allowed(origin: str | None) -> bool:
    if origin is None:
        return True
    return origin in configured_origins() or bool(_LOCALHOST.match(origin))
