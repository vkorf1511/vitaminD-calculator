from __future__ import annotations

import os
import threading
from datetime import datetime
from functools import lru_cache
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import Column, JSON, create_engine, text
from sqlalchemy.engine import Engine
from sqlmodel import Field as SQLField
from sqlmodel import Session, SQLModel, select
from timezonefinder import TimezoneFinder

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres@localhost:5432/email_list",
)
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
_initialized_engines: set[Engine] = set()
_initialization_lock = threading.Lock()


class TimezoneLookupError(ValueError):
    pass


class EmailList(SQLModel, table=True):
    __tablename__ = "email_list"

    id: int | None = SQLField(default=None, primary_key=True)
    email_address: str = SQLField(index=True, unique=True, max_length=320)
    name: str = SQLField(max_length=120)
    skin_type: str = SQLField(max_length=3)
    location: dict[str, Any] = SQLField(sa_column=Column(JSON, nullable=False))
    timezone: float


class EmailSignupRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email_address: EmailStr
    name: str = Field(min_length=1, max_length=120)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    location_name: str | None = Field(default=None, max_length=120)
    skin_type: Literal["I", "II", "III", "IV", "V"]


class EmailSignupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email_address: EmailStr
    name: str
    skin_type: str
    location: dict[str, Any]
    timezone: float


@lru_cache(maxsize=1)
def _timezone_finder() -> TimezoneFinder:
    return TimezoneFinder()


def timezone_offset_hours(latitude: float, longitude: float) -> float:
    timezone_name = _timezone_finder().timezone_at(lng=longitude, lat=latitude)
    if timezone_name is None:
        raise TimezoneLookupError("We could not determine the timezone for this location.")
    try:
        offset = datetime.now(ZoneInfo(timezone_name)).utcoffset()
    except ZoneInfoNotFoundError as exc:
        raise TimezoneLookupError("We could not determine the timezone for this location.") from exc
    if offset is None:
        raise TimezoneLookupError("We could not determine the timezone for this location.")
    return round(offset.total_seconds() / 3600, 2)


def _create_database_if_missing(database_engine: Engine) -> None:
    if database_engine.dialect.name != "postgresql":
        return
    database_url = database_engine.url
    database_name = database_url.database
    if not database_name:
        raise ValueError("The PostgreSQL URL must include a database name.")
    admin_engine = create_engine(
        database_url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    try:
        with admin_engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": database_name},
            ).scalar()
            if not exists:
                quoted_name = '"' + database_name.replace('"', '""') + '"'
                connection.exec_driver_sql(f"CREATE DATABASE {quoted_name}")
    finally:
        admin_engine.dispose()


def initialize_email_storage(database_engine: Engine | None = None) -> None:
    target_engine = database_engine or engine
    if target_engine in _initialized_engines:
        return
    with _initialization_lock:
        if target_engine in _initialized_engines:
            return
        _create_database_if_missing(target_engine)
        SQLModel.metadata.create_all(target_engine)
        _initialized_engines.add(target_engine)


def save_email_signup(payload: EmailSignupRequest) -> EmailSignupResponse:
    initialize_email_storage()
    timezone_offset = timezone_offset_hours(payload.latitude, payload.longitude)
    location = {
        "name": payload.location_name or f"{payload.latitude:.6f}, {payload.longitude:.6f}",
        "latitude": payload.latitude,
        "longitude": payload.longitude,
    }
    normalized_email = str(payload.email_address).strip().casefold()

    with Session(engine) as session:
        entry = session.exec(
            select(EmailList).where(EmailList.email_address == normalized_email)
        ).first()
        if entry is None:
            entry = EmailList(
                email_address=normalized_email,
                name=payload.name,
                skin_type=payload.skin_type,
                location=location,
                timezone=timezone_offset,
            )
        else:
            entry.skin_type = payload.skin_type
            entry.location = location
            entry.timezone = timezone_offset
        session.add(entry)
        session.commit()
        session.refresh(entry)
        return EmailSignupResponse.model_validate(entry)


def submit_email_signup(payload: EmailSignupRequest) -> EmailSignupResponse:
    try:
        return save_email_signup(payload)
    except TimezoneLookupError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
