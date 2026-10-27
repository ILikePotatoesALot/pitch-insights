"""Exercise exported spans and transport logs with deliberately private inputs."""

import io
import logging

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from pitch_insights.telemetry import RequestTelemetry, configure_privacy_logging, setup_telemetry

VIEWER = "12345678-1234-4234-8234-123456789abc"
PRIVATE = "private-person@example.test"


@pytest.fixture
def monitored():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    app = FastAPI()
    app.add_middleware(RequestTelemetry, tracer=provider.get_tracer("privacy-test"))

    @app.api_route("/api/profile/{viewer_id}", methods=["GET", "PUT", "DELETE"])
    async def profile(viewer_id: str):
        return {"mode": "analyst"}

    @app.get("/failure/{viewer_id}")
    async def failure(viewer_id: str):
        raise RuntimeError(f"{PRIVATE} {viewer_id}")

    @app.websocket("/ws/replay/{name}")
    async def replay(ws: WebSocket, name: str):
        await ws.accept()
        await ws.send_json({"ok": True})
        await ws.close()

    yield app, exporter
    provider.shutdown()


def serialise(exporter):
    return "\n".join(span.to_json() for span in exporter.get_finished_spans())


def test_profile_requests_keep_timings_status_and_route_without_private_inputs(monitored):
    app, exporter = monitored
    with TestClient(app, client=("198.51.100.23", 1234)) as client:
        for method in ("GET", "PUT", "DELETE"):
            response = client.request(method, f"/api/profile/{VIEWER}?contact={PRIVATE}",
                                      headers={"authorization": PRIVATE, "x-forwarded-for": "203.0.113.42"})
            assert response.status_code == 200
    spans = exporter.get_finished_spans()
    assert len(spans) == 3
    for span, method in zip(spans, ("GET", "PUT", "DELETE")):
        assert span.name == f"{method} /api/profile/{{viewer_id}}"
        assert dict(span.attributes) == {"network.protocol.name": "http", "http.request.method": method,
                                         "http.response.status_code": 200, "http.route": "/api/profile/{viewer_id}"}
        assert span.end_time >= span.start_time
    exported = serialise(exporter)
    for value in (VIEWER, PRIVATE, "198.51.100.23", "203.0.113.42", "authorization", "contact="):
        assert value not in exported


def test_unknown_paths_and_errors_never_become_span_names_or_exception_events(monitored):
    app, exporter = monitored
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get(f"/unknown/{PRIVATE}?id={VIEWER}").status_code == 404
        assert client.get(f"/failure/{VIEWER}").status_code == 500
    missing, failed = exporter.get_finished_spans()
    assert missing.name == "GET /unmatched"
    assert missing.attributes["http.response.status_code"] == 404
    assert failed.status.status_code == StatusCode.ERROR
    assert failed.attributes["error.type"] == "RuntimeError"
    assert failed.events == ()
    assert PRIVATE not in serialise(exporter) and VIEWER not in serialise(exporter)


def test_websocket_has_one_safe_span_and_unchanged_messages(monitored):
    app, exporter = monitored
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/replay/{VIEWER}?contact={PRIVATE}") as ws:
            assert ws.receive_json() == {"ok": True}
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "WEBSOCKET /ws/replay/{name}"
    assert spans[0].attributes["websocket.close.code"] == 1000
    assert PRIVATE not in serialise(exporter) and VIEWER not in serialise(exporter)


def test_transport_logs_drop_addresses_urls_and_exception_details():
    configure_privacy_logging()
    configure_privacy_logging()  # repeated startup must not add duplicate filters
    access = logging.getLogger("uvicorn.access")
    server = logging.getLogger("uvicorn.error")
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    previous_level = server.level
    server.setLevel(logging.DEBUG)
    server.addHandler(handler)
    access.addHandler(handler)
    try:
        access.info("198.51.100.23 GET /api/profile/%s?contact=%s", VIEWER, PRIVATE)
        server.info("198.51.100.23 WebSocket /ws/replay/%s?contact=%s [accepted]", VIEWER, PRIVATE)
        try:
            raise RuntimeError(f"{PRIVATE} {VIEWER}")
        except RuntimeError:
            server.exception("Exception in ASGI application")
        server.warning("Invalid HTTP request received.")
    finally:
        access.removeHandler(handler)
        server.removeHandler(handler)
        server.setLevel(previous_level)
    text = output.getvalue()
    assert "ASGI request failed (RuntimeError)" in text
    assert "Invalid HTTP request received." in text
    for value in (VIEWER, PRIVATE, "198.51.100.23", "Traceback"):
        assert value not in text


def test_cloud_setup_disables_automatic_capture_but_keeps_explicit_request_tracing(monkeypatch):
    import azure.monitor.opentelemetry as monitor

    calls = []
    monkeypatch.setattr(monitor, "configure_azure_monitor", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "test-only")
    app = FastAPI()
    assert setup_telemetry(app)
    from azure.monitor.opentelemetry._constants import _ALL_SUPPORTED_INSTRUMENTED_LIBRARIES

    options = calls[0]["instrumentation_options"]
    assert all(options[name]["enabled"] is False for name in _ALL_SUPPORTED_INSTRUMENTED_LIBRARIES)
    assert calls[0]["browser_sdk_loader_config"] == {"enabled": False}
    assert any(item.cls is RequestTelemetry for item in app.user_middleware)


def test_telemetry_configuration_failure_is_safe_and_optional(monkeypatch, caplog):
    import azure.monitor.opentelemetry as monitor

    def broken(**kwargs):
        raise RuntimeError(PRIVATE)

    monkeypatch.setattr(monitor, "configure_azure_monitor", broken)
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "test-only")
    with caplog.at_level(logging.WARNING, logger="pitch_insights"):
        assert setup_telemetry(FastAPI()) is False
    assert "RuntimeError" in caplog.text and PRIVATE not in caplog.text
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    assert setup_telemetry(FastAPI()) is False


def test_rejected_origin_is_not_copied_to_application_logs(caplog):
    from pitch_insights.server import app
    from starlette.websockets import WebSocketDisconnect

    with caplog.at_level(logging.WARNING, logger="pitch_insights.server"):
        with TestClient(app) as client:
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect("/ws/replay/comeback-POT-CAR",
                                              headers={"origin": f"https://example.test/{PRIVATE}"}):
                    pass
    assert "unapproved origin" in caplog.text and PRIVATE not in caplog.text
