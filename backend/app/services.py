from __future__ import annotations

import logging
import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
SKIN_BASE_MINUTES = {"I": 5, "II": 8, "III": 12, "IV": 16, "V": 20}
CLOTHING_EXPOSURE = {
    "naked": 1.0,
    "swimsuit": 0.85,
    "summer clothes": 0.30,
    "winter clothes": 0.05,
}
WEATHER_PARAMETERS = (
    "uv_index,cloud_cover,precipitation_probability,precipitation,rain,"
    "showers,snowfall,weather_code"
)


class WeatherServiceError(Exception):
    """Raised when the weather provider cannot supply a usable forecast."""


async def fetch_weather(latitude: float, longitude: float) -> dict[str, Any]:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": WEATHER_PARAMETERS,
        "forecast_days": 1,
        "timezone": "auto",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(OPEN_METEO_URL, params=params)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.error("Open-Meteo request failed", exc_info=True)
        raise WeatherServiceError("The weather forecast is temporarily unavailable.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("hourly"), dict):
        logger.error("Open-Meteo returned an invalid forecast")
        raise WeatherServiceError("The weather forecast is temporarily unavailable.")
    logger.info("Open-Meteo forecast received")
    return payload


def solar_elevation(latitude: float, longitude: float, local_time: datetime, utc_offset: int) -> float:
    """Estimate solar elevation using the NOAA fractional-year approximation."""
    day_of_year = local_time.timetuple().tm_yday
    fractional_hour = local_time.hour + local_time.minute / 60
    gamma = 2 * math.pi / 365 * (day_of_year - 1 + (fractional_hour - 12) / 24)
    equation_of_time = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )
    declination = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )
    time_offset = equation_of_time + 4 * longitude - utc_offset / 60
    solar_minutes = (fractional_hour * 60 + time_offset) % 1440
    hour_angle = math.radians(solar_minutes / 4 - 180)
    latitude_radians = math.radians(latitude)
    cosine_zenith = (
        math.sin(latitude_radians) * math.sin(declination)
        + math.cos(latitude_radians) * math.cos(declination) * math.cos(hour_angle)
    )
    return 90 - math.degrees(math.acos(max(-1.0, min(1.0, cosine_zenith))))


def _hour_value(hourly: dict[str, Any], field: str, index: int, default: float = 0) -> float:
    values = hourly.get(field)
    if not isinstance(values, list) or index >= len(values) or values[index] is None:
        return default
    try:
        return float(values[index])
    except (TypeError, ValueError) as exc:
        raise WeatherServiceError("The weather forecast could not be interpreted.") from exc


def _valid_hourly_data(hourly: dict[str, Any]) -> tuple[list[str], list[float], list[float]]:
    times = hourly.get("time")
    uv_values = hourly.get("uv_index")
    cloud_values = hourly.get("cloud_cover")
    if not isinstance(times, list) or not isinstance(uv_values, list) or not isinstance(cloud_values, list):
        raise WeatherServiceError("The weather forecast could not be interpreted.")
    if len(times) != len(uv_values) or len(times) != len(cloud_values):
        raise WeatherServiceError("The weather forecast could not be interpreted.")
    try:
        parsed_times = [datetime.fromisoformat(value) for value in times]
        parsed_uv = [float(value or 0) for value in uv_values]
        parsed_cloud = [float(value or 0) for value in cloud_values]
    except (TypeError, ValueError) as exc:
        raise WeatherServiceError("The weather forecast could not be interpreted.") from exc
    return [value.isoformat() for value in parsed_times], parsed_uv, parsed_cloud


def calculate_recommendation(
    forecast: dict[str, Any],
    latitude: float,
    longitude: float,
    skin_type: str,
    clothing_density: str,
    location_name: str | None = None,
    current_utc: datetime | None = None,
) -> dict[str, Any]:
    hourly = forecast.get("hourly")
    if not isinstance(hourly, dict):
        raise WeatherServiceError("The weather forecast could not be interpreted.")
    times, _, _ = _valid_hourly_data(hourly)
    offset_seconds = forecast.get("utc_offset_seconds", 0)
    try:
        utc_offset = int(offset_seconds)
    except (TypeError, ValueError) as exc:
        raise WeatherServiceError("The weather forecast could not be interpreted.") from exc
    current_utc = current_utc or datetime.now(timezone.utc)
    if current_utc.tzinfo is None:
        current_utc = current_utc.replace(tzinfo=timezone.utc)
    local_now = (current_utc.astimezone(timezone.utc) + timedelta(seconds=utc_offset)).replace(tzinfo=None)
    local_date = local_now.date()
    hourly_minutes = [0] * 24
    hourly_uv = [0.0] * 24
    suitable: list[tuple[int, float, int]] = []

    for index, timestamp in enumerate(times):
        point = datetime.fromisoformat(timestamp)
        if point.date() != local_date:
            continue
        hour = point.hour
        uv_index = _hour_value(hourly, "uv_index", index)
        cloud_cover = _hour_value(hourly, "cloud_cover", index)
        precipitation_probability = _hour_value(hourly, "precipitation_probability", index)
        precipitation = sum(
            _hour_value(hourly, field, index)
            for field in ("precipitation", "rain", "showers", "snowfall")
        )
        elevation = solar_elevation(latitude, longitude, point, utc_offset)
        hourly_uv[hour] = round(max(0, uv_index), 1)
        still_ahead = point + timedelta(hours=1) > local_now
        if (
            still_ahead
            and elevation >= 25
            and uv_index >= 1
            and cloud_cover <= 85
            and precipitation_probability < 50
            and precipitation < 0.1
        ):
            cloud_factor = max(0.1, 1 - cloud_cover / 100 * 0.75)
            effective_uv = uv_index * cloud_factor
            exposure_fraction = CLOTHING_EXPOSURE[clothing_density]
            minutes = math.ceil(
                SKIN_BASE_MINUTES[skin_type] * 3 / max(effective_uv, 0.5) / math.sqrt(exposure_fraction)
            )
            minutes = min(30, max(2, minutes))
            hourly_minutes[hour] = minutes
            suitable.append((hour, effective_uv, minutes))

    if suitable:
        best_hour, _, recommended_minutes = max(suitable, key=lambda candidate: candidate[1])
        start = f"{best_hour:02d}:00"
        end = f"{(best_hour + 1) % 24:02d}:00"
        recommendation = (
            f"You should stay under the sun for {recommended_minutes} minutes "
            f"between {start} and {end} local time."
        )
    else:
        start = None
        end = None
        recommended_minutes = 0
        recommendation = (
            "No suitable sun-exposure window remains today based on the sunlight "
            "and weather forecast. Consider discussing vitamin D with a healthcare professional."
        )

    resolved_location = location_name or f"{latitude:.4f}, {longitude:.4f}"
    return {
        "location": resolved_location,
        "date": local_date.isoformat(),
        "recommendation": recommendation,
        "window_start": start,
        "window_end": end,
        "recommended_minutes": recommended_minutes,
        "hourly_exposure_minutes": hourly_minutes,
        "hourly_uv_index": hourly_uv,
        "advisory": (
            "This is a simplified educational estimate, not medical advice or a guaranteed "
            "way to produce vitamin D. UV exposure can damage skin; never stay out long "
            "enough to burn, use appropriate sun protection, and ask a healthcare professional "
            "about your vitamin D needs."
        ),
    }
