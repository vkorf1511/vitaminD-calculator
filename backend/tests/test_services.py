from datetime import datetime, timezone

import pytest

from app.services import (
    CLOTHING_EXPOSURE,
    SKIN_BASE_MINUTES,
    WeatherServiceError,
    calculate_recommendation,
    fetch_weather,
    solar_elevation,
)


def make_forecast(*, clouds=10, rain=0, uv=6):
    times = [f"2026-10-20T{hour:02d}:00" for hour in range(24)]
    return {
        "utc_offset_seconds": 0,
        "timezone": "UTC",
        "hourly": {
            "time": times,
            "uv_index": [uv] * 24,
            "cloud_cover": [clouds] * 24,
            "precipitation_probability": [0] * 24,
            "precipitation": [rain] * 24,
            "rain": [0] * 24,
            "showers": [0] * 24,
            "snowfall": [0] * 24,
        },
    }


def test_solar_elevation_is_high_at_equatorial_noon_and_low_at_midnight():
    noon = solar_elevation(0, 0, datetime(2026, 3, 20, 12), 0)
    midnight = solar_elevation(0, 0, datetime(2026, 3, 20, 0), 0)
    assert noon > 80
    assert midnight < 0


@pytest.mark.parametrize("skin_type,base", SKIN_BASE_MINUTES.items())
@pytest.mark.parametrize("clothing,exposed", CLOTHING_EXPOSURE.items())
def test_recommendation_uses_inputs_and_returns_24_points(skin_type, base, clothing, exposed):
    result = calculate_recommendation(
        make_forecast(),
        0,
        0,
        skin_type,
        clothing,
        "Quito",
        datetime(2026, 10, 20, 5, tzinfo=timezone.utc),
    )
    assert len(result["hourly_exposure_minutes"]) == 24
    assert result["date"] == "2026-10-20"
    assert result["location"] == "Quito"
    assert result["recommended_minutes"] >= 2
    assert result["recommended_minutes"] <= 30
    assert result["window_start"] is not None
    assert len(result["hourly_uv_index"]) == 24
    assert "not medical advice" in result["advisory"]


@pytest.mark.parametrize(
    "forecast",
    [
        make_forecast(clouds=100),
        make_forecast(rain=1),
        {"hourly": {"time": [], "uv_index": [2], "cloud_cover": []}},
        {"hourly": {"time": ["not-a-time"], "uv_index": [2], "cloud_cover": [0]}},
    ],
)
def test_no_suitable_window_or_invalid_forecast(forecast):
    if forecast["hourly"].get("time") == [] or forecast["hourly"].get("time") == ["not-a-time"]:
        with pytest.raises(WeatherServiceError):
            calculate_recommendation(
                forecast, 0, 0, "III", "summer clothes",
                current_utc=datetime(2026, 10, 20, 5, tzinfo=timezone.utc),
            )
        return
    result = calculate_recommendation(
        forecast, 0, 0, "III", "summer clothes",
        current_utc=datetime(2026, 10, 20, 5, tzinfo=timezone.utc),
    )
    assert result["recommended_minutes"] == 0
    assert result["window_start"] is None
    assert all(value == 0 for value in result["hourly_exposure_minutes"])


@pytest.mark.asyncio
async def test_fetch_weather_sends_expected_open_meteo_parameters(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"hourly": {"time": []}}

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["timeout"] == 10.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get(self, url, params):
            captured.update(url=url, params=params)
            return FakeResponse()

    monkeypatch.setattr("app.services.httpx.AsyncClient", FakeClient)
    result = await fetch_weather(51.5, -0.1)
    assert result == {"hourly": {"time": []}}
    assert captured["params"]["latitude"] == 51.5
    assert captured["params"]["timezone"] == "auto"
    assert "cloud_cover" in captured["params"]["hourly"]


@pytest.mark.asyncio
async def test_fetch_weather_reports_provider_failure(monkeypatch):
    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get(self, *_args, **_kwargs):
            raise __import__("httpx").ConnectError("offline")

    monkeypatch.setattr("app.services.httpx.AsyncClient", FakeClient)
    with pytest.raises(WeatherServiceError):
        await fetch_weather(0, 0)


def test_calculator_uses_location_local_date_and_rejects_current_past_day():
    forecast = make_forecast()
    forecast["utc_offset_seconds"] = 7200
    result = calculate_recommendation(
        forecast, 0, 0, "III", "swimsuit",
        current_utc=datetime(2026, 10, 19, 23, tzinfo=timezone.utc),
    )
    assert result["date"] == "2026-10-20"
    assert result["hourly_exposure_minutes"][0] == 0


def test_bad_weather_fields_raise_a_clear_error():
    forecast = make_forecast()
    forecast["hourly"]["uv_index"] = ["not-a-number"] * 24
    with pytest.raises(WeatherServiceError):
        calculate_recommendation(
            forecast, 0, 0, "III", "naked",
            current_utc=datetime(2026, 10, 20, 5, tzinfo=timezone.utc),
        )
