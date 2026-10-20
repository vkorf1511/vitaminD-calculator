from __future__ import annotations

import json
import logging
import os
import re
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, ConfigDict, Field

from app.services import WeatherServiceError, calculate_recommendation, fetch_weather

BASE_DIR = Path(__file__).resolve().parents[2]
CITY_DATA = Path(__file__).resolve().parent / "data" / "cities.json"
FRONTEND_DIR = BASE_DIR / "frontend" / "out"
if not FRONTEND_DIR.is_dir():
    FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend" / "out"
REQUEST_ID = ContextVar("request_id", default="-")
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
logger = logging.getLogger("vitamin_d")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "message": record.getMessage(),
            "request_id": REQUEST_ID.get(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())


configure_logging()

app = FastAPI(
    title="Vitamin D Exposure Estimate API",
    version="1.0.0",
    description="An educational, weather-aware outdoor exposure estimate. Not medical advice.",
    openapi_url="/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Request-ID"],
)

if trace.get_tracer_provider().__class__.__name__ == "ProxyTracerProvider":
    trace.set_tracer_provider(TracerProvider())
FastAPIInstrumentor.instrument_app(app)
HTTPXClientInstrumentor().instrument()
Instrumentator().instrument(app).expose(app, include_in_schema=False)


class ExposureRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    location_name: str | None = Field(default=None, max_length=120)
    skin_type: Literal["I", "II", "III", "IV", "V"]
    clothing_density: Literal["naked", "swimsuit", "summer clothes", "winter clothes"]


@app.middleware("http")
async def add_request_id(request: Request, call_next: Any) -> Any:
    supplied_id = request.headers.get("X-Request-ID", "")
    request_id = supplied_id if SAFE_REQUEST_ID.fullmatch(supplied_id) else str(uuid.uuid4())
    token = REQUEST_ID.set(request_id)
    try:
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Unhandled application exception")
            response = JSONResponse(
                status_code=500,
                content={
                    "detail": "Something went wrong while preparing your estimate. Please try again.",
                    "request_id": request_id,
                },
            )
        response.headers["X-Request-ID"] = request_id
        if response.status_code >= 500:
            logger.error("Request failed with server error: %s %s", request.method, request.url.path)
        else:
            logger.info("Request completed: %s %s (%s)", request.method, request.url.path, response.status_code)
        return response
    finally:
        REQUEST_ID.reset(token)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    logger.error("Request validation failed: %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=422,
        content={"detail": "Please check the location, skin type, and clothing selection.", "request_id": REQUEST_ID.get()},
    )


@app.exception_handler(WeatherServiceError)
async def weather_error_handler(request: Request, exc: WeatherServiceError) -> JSONResponse:
    logger.error("Weather forecast unavailable: %s", str(exc))
    return JSONResponse(
        status_code=502,
        content={"detail": str(exc), "request_id": REQUEST_ID.get()},
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled application exception")
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Something went wrong while preparing your estimate. Please try again.",
            "request_id": REQUEST_ID.get(),
        },
    )


@app.get("/", include_in_schema=False)
async def landing_page() -> Any:
    index_file = FRONTEND_DIR / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    return JSONResponse(
        status_code=503,
        content={"detail": "The web interface is not built. Run the frontend development server or build it first."},
    )


@app.post("/process", name="calculate_exposure")
async def process_exposure(payload: ExposureRequest) -> dict[str, Any]:
    forecast = await fetch_weather(payload.latitude, payload.longitude)
    return calculate_recommendation(
        forecast=forecast,
        latitude=payload.latitude,
        longitude=payload.longitude,
        skin_type=payload.skin_type,
        clothing_density=payload.clothing_density,
        location_name=payload.location_name,
    )


@app.get("/locations")
async def list_locations() -> list[dict[str, Any]]:
    try:
        with CITY_DATA.open(encoding="utf-8") as data_file:
            return json.load(data_file)
    except (OSError, json.JSONDecodeError):
        logger.exception("Bundled location data could not be loaded")
        raise


@app.get("/health")
async def health() -> Any:
    if not CITY_DATA.is_file():
        logger.error("Bundled location data is missing")
        return JSONResponse(status_code=503, content={"status": "DOWN"})
    return {"status": "ok"}


if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
