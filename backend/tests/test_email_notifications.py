import asyncio
import json
from datetime import datetime, timezone
from email.message import EmailMessage

import pytest
from sqlalchemy import Column, Float, Integer, MetaData, String, Table, create_engine, insert
from sqlalchemy.pool import StaticPool

from app.email_notifications import (
    EmailRecipient,
    _chart_html,
    _load_recipients,
    _local_time,
    create_daily_email,
    create_email_scheduler,
    process_due_emails,
    send_email,
)
from app.main import app, scheduler
from fastapi.testclient import TestClient


def make_database(recipients):
    database_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata = MetaData()
    email_list = Table(
        "email_list",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("email_address", String, nullable=False, unique=True),
        Column("name", String, nullable=False),
        Column("skin_type", String, nullable=False),
        Column("location", String, nullable=False),
        Column("timezone", Float, nullable=False),
    )
    metadata.create_all(database_engine)
    rows = [
        {**record, "location": json.dumps(record["location"]) if isinstance(record["location"], dict) else record["location"]}
        for record in recipients
    ]
    with database_engine.begin() as connection:
        connection.execute(insert(email_list), rows)
    return database_engine


@pytest.fixture
def database_factory():
    engines = []

    def create_database(recipients):
        database_engine = make_database(recipients)
        engines.append(database_engine)
        return database_engine

    yield create_database
    for database_engine in engines:
        database_engine.dispose()


def recipient(email, *, timezone_offset=0, location=None, skin_type="III"):
    return {
        "email_address": email,
        "name": "Sun Seeker",
        "skin_type": skin_type,
        "location": location or {
            "name": "Quito",
            "latitude": 0,
            "longitude": 0,
        },
        "timezone": timezone_offset,
    }


def forecast_for(day):
    return {
        "utc_offset_seconds": 0,
        "hourly": {
            "time": [f"{day.isoformat()}T{hour:02d}:00" for hour in range(24)],
            "uv_index": [6] * 24,
            "cloud_cover": [10] * 24,
            "precipitation_probability": [0] * 24,
            "precipitation": [0] * 24,
            "rain": [0] * 24,
            "showers": [0] * 24,
            "snowfall": [0] * 24,
        },
    }


def test_local_time_respects_offsets_and_naive_input():
    utc_now = datetime(2026, 10, 20, 4, tzinfo=timezone.utc)
    assert _local_time(utc_now, 1).hour == 5
    assert _local_time(utc_now, 5.5).minute == 30
    assert _local_time(datetime(2026, 10, 20, 4), 0).hour == 4


def test_local_time_applies_daylight_saving_rules_from_location():
    new_york = {"latitude": 40.7128, "longitude": -74.006}
    winter_now = datetime(2026, 1, 20, 10, tzinfo=timezone.utc)
    summer_now = datetime(2026, 7, 20, 9, tzinfo=timezone.utc)

    assert _local_time(winter_now, -5, new_york).hour == 5
    assert _local_time(summer_now, -5, new_york).hour == 5


def test_load_recipients_reads_json_locations_from_email_list(database_factory):
    database_engine = database_factory([
        recipient("one@example.com"),
        {
            **recipient("two@example.com"),
            "location": json.dumps({"name": "Athens", "latitude": 38, "longitude": 24}),
        },
    ])

    records = _load_recipients(database_engine)

    assert len(records) == 2
    assert records[0].location["name"] == "Quito"
    assert records[1].location["name"] == "Athens"


def test_email_contains_template_recommendation_plain_text_and_hourly_chart():
    saved_user = EmailRecipient(
        email_address="sun@example.com",
        name="Sam",
        skin_type="II",
        location={"name": "Athens", "latitude": 38, "longitude": 24},
        timezone=3,
    )
    result = {
        "date": "2026-10-20",
        "recommendation": "You should stay under the sun for 8 minutes between 12:00 and 13:00 local time.",
        "hourly_exposure_minutes": [0] * 12 + [8] + [0] * 11,
        "advisory": "An educational estimate only.",
    }

    message = create_daily_email(saved_user, result)
    plain_text, html = message.get_body(preferencelist=("plain", "html")), message.get_body(preferencelist=("html",))

    assert message["Subject"] == "Your daily Vitamin D window — 2026-10-20"
    assert message["To"] == "sun@example.com"
    assert "Dear Sam," in plain_text.get_content()
    assert result["recommendation"] in plain_text.get_content()
    assert html is not None
    html_content = html.get_content()
    assert "Dear Sam," in html_content
    assert result["recommendation"] in html_content
    assert "Today's exposure guide" in html_content
    assert "12:00 — 8 minutes" in html_content
    assert "12 PM" in html_content
    chart = _chart_html([0] * 23 + [2])
    assert chart.count("<td") == 49
    assert "height:40px" in chart


def test_sends_only_recipients_at_local_five_and_continues_after_per_user_failure(database_factory):
    database_engine = database_factory([
        recipient(
            "due@example.com",
            timezone_offset=1,
            location={"name": "London", "latitude": 51.5, "longitude": -0.12},
        ),
        recipient("not-due@example.com", timezone_offset=0),
        recipient(
            "bad-location@example.com",
            timezone_offset=1,
            location={"name": "Unknown"},
        ),
    ])
    fetched = []
    sent = []

    async def fake_weather(latitude, longitude):
        fetched.append((latitude, longitude))
        return forecast_for(datetime(2026, 10, 20).date())

    def fake_mailer(message):
        sent.append(message)

    summary = asyncio.run(
        process_due_emails(
            datetime(2026, 10, 20, 4, tzinfo=timezone.utc),
            database_engine=database_engine,
            weather_fetcher=fake_weather,
            mailer=fake_mailer,
        )
    )

    assert summary == {"due": 2, "sent": 1, "failed": 1}
    assert fetched == [(51.5, -0.12)]
    assert sent[0]["To"] == "due@example.com"


def test_no_due_recipients_does_not_fetch_or_send(database_factory):
    database_engine = database_factory([recipient("not-due@example.com")])

    async def fail_weather(*_):
        pytest.fail("Weather should only be fetched for due users.")

    summary = asyncio.run(
        process_due_emails(
            datetime(2026, 10, 20, 4, tzinfo=timezone.utc),
            database_engine=database_engine,
            weather_fetcher=fail_weather,
            mailer=lambda _: pytest.fail("No email should be sent."),
        )
    )

    assert summary == {"due": 0, "sent": 0, "failed": 0}


def test_email_scheduler_has_a_quarter_hour_cron_trigger():
    scheduler = create_email_scheduler()
    job = scheduler.get_job("daily-vitamin-d-email-notifications")

    assert job is not None
    assert str(job.trigger) == "cron[minute='*/15']"


def test_scheduler_starts_and_stops_with_application_lifespan():
    with TestClient(app):
        assert scheduler.running
    assert not scheduler.running


def test_send_email_validates_configuration(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_SENDER", raising=False)

    with pytest.raises(RuntimeError, match="SMTP_HOST and SMTP_SENDER"):
        send_email(EmailMessage())


def test_send_email_uses_starttls_auth_and_sends_message(monkeypatch):
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def starttls(self):
            calls.append(("starttls",))

        def login(self, username, password):
            calls.append(("login", username, password))

        def send_message(self, message):
            calls.append(("send", message["From"]))

    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_SENDER", "daily@example.com")
    monkeypatch.setenv("SMTP_USERNAME", "smtp-user")
    monkeypatch.setenv("SMTP_PASSWORD", "smtp-secret")
    monkeypatch.setenv("SMTP_USE_STARTTLS", "true")
    monkeypatch.setattr("app.email_notifications.smtplib.SMTP", FakeSMTP)

    message = EmailMessage()
    message["To"] = "person@example.com"
    send_email(message)

    assert message["From"] == "daily@example.com"
    assert calls == [
        ("connect", "smtp.example.com", 587, 20),
        ("starttls",),
        ("login", "smtp-user", "smtp-secret"),
        ("send", "daily@example.com"),
    ]


def test_send_email_rejects_partial_credentials(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_SENDER", "daily@example.com")
    monkeypatch.setenv("SMTP_USERNAME", "smtp-user")
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)

    with pytest.raises(RuntimeError, match="Both SMTP_USERNAME and SMTP_PASSWORD"):
        send_email(EmailMessage())
