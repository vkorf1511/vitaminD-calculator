import asyncio
import json
import logging
from datetime import datetime, timezone

import httpx
import pytest
from opentelemetry import trace
from fastapi.testclient import TestClient

from app.main import REQUEST_ID, JsonFormatter, app

client = TestClient(app)


def test_health_and_locations():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    locations = client.get("/locations")
    assert locations.status_code == 200
    countries = locations.json()
    assert len(countries) > 200
    assert countries[0]["cities"]


def test_health_reports_down_when_required_location_data_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("app.main.CITY_DATA", tmp_path / "missing.json")
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "DOWN"}


def test_request_id_is_echoed_and_validation_is_friendly():
    response = client.post("/process", headers={"X-Request-ID": "test-request_1"}, json={})
    assert response.status_code == 422
    assert response.headers["x-request-id"] == "test-request_1"
    assert response.json()["request_id"] == "test-request_1"
    assert "check" in response.json()["detail"]


def test_untrusted_request_id_is_replaced():
    response = client.get("/health", headers={"X-Request-ID": "bad value"})
    assert response.status_code == 200
    assert response.headers["x-request-id"] != "bad value"


def test_process_returns_complete_result(monkeypatch):
    fixed_now = datetime.now(timezone.utc).replace(hour=5, minute=0, second=0, microsecond=0)
    today = fixed_now.date().isoformat()
    times = [f"{today}T{hour:02d}:00" for hour in range(24)]
    forecast = {
        "utc_offset_seconds": 0,
        "hourly": {
            "time": times,
            "uv_index": [6] * 24,
            "cloud_cover": [10] * 24,
            "precipitation_probability": [0] * 24,
            "precipitation": [0] * 24,
            "rain": [0] * 24,
            "showers": [0] * 24,
            "snowfall": [0] * 24,
        },
    }

    async def fake_fetch_weather(latitude, longitude):
        assert (latitude, longitude) == (0, 0)
        return forecast

    monkeypatch.setattr("app.main.fetch_weather", fake_fetch_weather)
    fixed_datetime = type(
        "FixedDateTime",
        (datetime,),
        {"now": classmethod(lambda cls, tz=None: fixed_now)},
    )
    monkeypatch.setattr("app.services.datetime", fixed_datetime)
    response = client.post(
        "/process",
        json={
            "latitude": 0,
            "longitude": 0,
            "location_name": "Quito",
            "skin_type": "III",
            "clothing_density": "summer clothes",
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["location"] == "Quito"
    assert result["date"] == today
    assert len(result["hourly_exposure_minutes"]) == 24
    assert result["recommendation"].startswith("You should stay under the sun for")


def test_weather_failure_is_returned_as_readable_502(monkeypatch):
    from app.services import WeatherServiceError

    async def fake_fetch_weather(*_):
        raise WeatherServiceError("The weather forecast is temporarily unavailable.")

    monkeypatch.setattr("app.main.fetch_weather", fake_fetch_weather)
    response = client.post(
        "/process",
        json={
            "latitude": 0,
            "longitude": 0,
            "skin_type": "III",
            "clothing_density": "summer clothes",
        },
    )
    assert response.status_code == 502
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert "temporarily unavailable" in response.json()["detail"]


def test_metrics_endpoint_is_exposed():
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "http_requests_total" in response.text


def test_generated_openapi_exposes_allowed_input_options():
    document = client.get("/openapi.json").json()
    schemas = document["components"]["schemas"]
    assert schemas["ExposureRequest"]["properties"]["skin_type"]["enum"] == ["I", "II", "III", "IV", "V"]
    assert schemas["ExposureRequest"]["properties"]["clothing_density"]["enum"] == [
        "naked", "swimsuit", "summer clothes", "winter clothes",
    ]


def test_landing_page_serves_the_built_frontend(monkeypatch, tmp_path):
    (tmp_path / "index.html").write_text("<main>Sunwise</main>", encoding="utf-8")
    monkeypatch.setattr("app.main.FRONTEND_DIR", tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert "Sunwise" in response.text


def test_unhandled_exception_is_logged_and_returned_as_json(monkeypatch, caplog):
    async def fail_fetch(*_):
        raise RuntimeError("private upstream detail")

    monkeypatch.setattr("app.main.fetch_weather", fail_fetch)
    safe_client = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="vitamin_d"):
        response = safe_client.post(
            "/process",
            json={
                "latitude": 0,
                "longitude": 0,
                "skin_type": "III",
                "clothing_density": "summer clothes",
            },
        )
    assert response.status_code == 500
    assert "private upstream detail" not in response.text
    assert "Unhandled application exception" in caplog.text
    assert response.json()["request_id"] == response.headers["x-request-id"]


def test_json_logs_include_timestamp_level_message_and_request_id():
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "estimate ready", (), None)
    token = REQUEST_ID.set("test-request-42")
    try:
        entry = json.loads(JsonFormatter().format(record))
    finally:
        REQUEST_ID.reset(token)
    assert entry["timestamp"]
    assert entry["level"] == "INFO"
    assert entry["message"] == "estimate ready"
    assert entry["request_id"] == "test-request-42"


@pytest.mark.asyncio
async def test_httpx_instrumentation_propagates_trace_context():
    received_headers = {}

    async def capture(reader, writer):
        request = await reader.readuntil(b"\r\n\r\n")
        for header in request.split(b"\r\n")[1:]:
            if b":" in header:
                key, value = header.split(b":", 1)
                received_headers[key.decode().lower()] = value.decode().strip()
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(capture, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        with trace.get_tracer("test").start_as_current_span("user-request"):
            async with httpx.AsyncClient() as http_client:
                await http_client.get(f"http://127.0.0.1:{port}/forecast")
    finally:
        server.close()
        await server.wait_closed()
    assert received_headers.get("traceparent", "").startswith("00-")
