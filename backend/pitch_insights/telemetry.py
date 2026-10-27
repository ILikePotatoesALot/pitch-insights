"""Request timings and outcomes without viewer identifiers, URLs, headers or IPs.

Off unless APPLICATIONINSIGHTS_CONNECTION_STRING is set. Automatic request and
dependency instrumentation is disabled: profile IDs also occur in Cosmos URLs.
The explicit server spans use route templates and never record exception text.
Agent generation has its own instrumentation in agents/tracing.py.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("pitch_insights")


class _SafeServerErrors(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Uvicorn's WebSocket INFO messages include the remote address and URL.
        if record.levelno < logging.WARNING:
            return False
        if record.exc_info:
            error = record.exc_info[0]
            record.msg = "ASGI request failed (%s)"
            record.args = (error.__name__ if error else "Exception",)
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


def configure_privacy_logging() -> None:
    """Apply even without cloud telemetry, including local Uvicorn runs."""
    logging.getLogger("uvicorn.access").disabled = True
    server_log = logging.getLogger("uvicorn.error")
    if not any(isinstance(item, _SafeServerErrors) for item in server_log.filters):
        server_log.addFilter(_SafeServerErrors())


class RequestTelemetry:
    """One span per HTTP request or WebSocket, containing only allowed fields."""

    def __init__(self, app, tracer=None):
        from opentelemetry import trace

        self.app = app
        self.tracer = tracer or trace.get_tracer(__name__)

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        from opentelemetry.trace import SpanKind, StatusCode

        protocol = scope["type"]
        method = scope.get("method", "")
        # HTTP methods are untrusted input too. Never use arbitrary strings as labels.
        method = method if method in {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "CONNECT", "TRACE"} else "OTHER"
        operation = method if protocol == "http" else "WEBSOCKET"
        with self.tracer.start_as_current_span(operation, kind=SpanKind.SERVER,
                                               record_exception=False, set_status_on_exception=False) as span:
            span.set_attribute("network.protocol.name", protocol)
            if protocol == "http":
                span.set_attribute("http.request.method", method)

            async def observed_send(message):
                if message["type"] == "http.response.start":
                    status = message["status"]
                    span.set_attribute("http.response.status_code", status)
                    if status >= 500:
                        span.set_status(StatusCode.ERROR)
                elif message["type"] == "websocket.close":
                    span.set_attribute("websocket.close.code", message.get("code", 1000))
                await send(message)

            try:
                await self.app(scope, receive, observed_send)
            except Exception as error:
                span.set_attribute("error.type", type(error).__name__)
                span.set_status(StatusCode.ERROR)
                raise
            finally:
                # The router sets this only after resolving the route. Unmatched paths
                # get a fixed label instead of a copy of the caller's path.
                route = getattr(scope.get("route"), "path", None) or "/unmatched"
                span.set_attribute("http.route", route)
                span.update_name(f"{operation} {route}")


def setup_telemetry(app) -> bool:
    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
    if not connection_string:
        return False
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        logging.getLogger("azure").setLevel(logging.WARNING)
        os.environ.setdefault("OTEL_SERVICE_NAME", "seize-the-game-api")
        configure_azure_monitor(
            connection_string=connection_string, logger_name="pitch_insights",
            instrumentation_options={name: {"enabled": False} for name in (
                "fastapi", "flask", "django", "httpx", "httpx2", "requests", "urllib", "urllib3", "psycopg2", "azure_sdk",
            )},
            browser_sdk_loader_config={"enabled": False},
        )
        app.add_middleware(RequestTelemetry)
    except Exception as error:
        log.warning("telemetry is off: %s", type(error).__name__)
        return False
    log.info("telemetry to Application Insights is on")
    return True
