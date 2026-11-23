from __future__ import annotations

import asyncio
import json
import logging
import os
import smtplib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from functools import lru_cache
from html import escape
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import Engine, create_engine, text
from sqlmodel import Session
from timezonefinder import TimezoneFinder

from app.services import calculate_recommendation, fetch_weather

logger = logging.getLogger("vitamin_d.notifications")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres@localhost:5432/email_list",
)
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
DEFAULT_CLOTHING_DENSITY = "summer clothes"


@dataclass(frozen=True)
class EmailRecipient:
    email_address: str
    name: str
    skin_type: str
    location: dict[str, Any]
    timezone: float


@lru_cache(maxsize=1)
def _timezone_finder() -> TimezoneFinder:
    return TimezoneFinder()


def _local_time(
    now_utc: datetime,
    offset_hours: float,
    location: dict[str, Any] | None = None,
) -> datetime:
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    if location and "latitude" in location and "longitude" in location:
        timezone_name = _timezone_finder().timezone_at(
            lng=float(location["longitude"]),
            lat=float(location["latitude"]),
        )
        if timezone_name:
            try:
                return now_utc.astimezone(ZoneInfo(timezone_name))
            except ZoneInfoNotFoundError as exc:
                raise ValueError("A saved location has an unknown timezone.") from exc
    return now_utc.astimezone(timezone.utc) + timedelta(hours=offset_hours)


def _load_recipients(database_engine: Engine) -> list[EmailRecipient]:
    with Session(database_engine) as session:
        rows = session.exec(
            text(
                "SELECT email_address, name, skin_type, location, timezone "
                "FROM email_list"
            )
        ).mappings()
        recipients: list[EmailRecipient] = []
        for row in rows:
            location = row["location"]
            if isinstance(location, str):
                location = json.loads(location)
            if not isinstance(location, dict):
                raise ValueError("A saved email location is not valid JSON.")
            recipients.append(
                EmailRecipient(
                    email_address=row["email_address"],
                    name=row["name"],
                    skin_type=row["skin_type"],
                    location=location,
                    timezone=float(row["timezone"]),
                )
            )
        return recipients


def _chart_html(values: list[int]) -> str:
    maximum = max([5, *values])
    value_cells = []
    bar_cells = []
    for hour, minutes in enumerate(values):
        height = max(10, round(minutes / maximum * 100)) if minutes else 3
        label = f"{hour:02d}" if hour % 3 == 0 else ""
        value_cells.append(
            f"<td align=\"center\" style=\"width:4.16%;height:12px;"
            f"font:8px Arial,sans-serif;color:#71836f\">{minutes or '&nbsp;'}</td>"
        )
        color = "linear-gradient(180deg,#e8be53,#9bc66f)" if minutes else "#e6eee2"
        bar_cells.append(
            "<td valign=\"bottom\" align=\"center\" "
            "style=\"width:4.16%;height:110px;padding:0 2px 0;vertical-align:bottom\">"
            f"<div title=\"{hour:02d}:00 — {minutes} minutes\" "
            f"style=\"height:{height}px;min-height:3px;background:{color};"
            "border-radius:5px 5px 2px 2px;margin:0 auto;width:13px;max-width:100%\"></div>"
            f"<div style=\"height:12px;font:8px Arial,sans-serif;color:#8d9b90\">{label or '&nbsp;'}</div>"
            "</td>"
        )
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%;max-width:720px;table-layout:fixed;border-collapse:collapse;'
        'border-bottom:1px solid #e9efe4">'
        f"<tr>{''.join(value_cells)}</tr><tr>{''.join(bar_cells)}</tr>"
        '<tr><td colspan="24" style="padding-top:7px;font:8px Arial,sans-serif;color:#9aa79d">'
        '<div style="display:flex;justify-content:space-between">'
        "<span>12 AM</span><span>6 AM</span><span>12 PM</span>"
        "<span>6 PM</span><span>12 AM</span></div></td></tr></table>"
    )


def create_daily_email(recipient: EmailRecipient, result: dict[str, Any]) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = f"Your daily Vitamin D window — {result['date']}"
    message["To"] = recipient.email_address
    message.set_content(
        f"Dear {recipient.name},\n\n"
        "Below are your daily vitamin D production windows personalised for your skin type, "
        "location and time of the year.\n\n"
        "Have fun under the sun!\n\n"
        f"{result['recommendation']}\n\n"
        "Hourly estimated exposure minutes (local time):\n"
        + ", ".join(
            f"{hour:02d}:00 {minutes} min"
            for hour, minutes in enumerate(result["hourly_exposure_minutes"])
        )
        + f"\n\n{result['advisory']}\n"
    )

    html_body = f"""\
<!doctype html>
<html lang="en">
  <body style="margin:0;padding:24px;background:#fbfcf4;font-family:Arial,sans-serif;color:#173b32">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
      <tr><td align="center">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"
          style="max-width:720px;background:#fff;border:1px solid #edf0e8;border-radius:16px">
          <tr><td style="padding:28px">
            <p style="margin:0 0 18px;color:#368366;font-size:11px;font-weight:bold;letter-spacing:2px">SUNWISE · YOUR DAILY WINDOW</p>
            <p style="font-size:16px;margin:0 0 16px">Dear {escape(recipient.name)},</p>
            <p style="font-size:14px;line-height:1.6;margin:0 0 18px">
              Below are your daily vitamin D production windows personalised for your skin type,
              location and time of the year.<br><br>Have fun under the sun!
            </p>
            <h2 style="font-size:15px;margin:0 0 10px">Today's exposure guide</h2>
            <p style="font-size:12px;color:#73877c;margin:0 0 16px">Estimated minutes by local hour</p>
            {_chart_html(result["hourly_exposure_minutes"])}
            <p style="margin:20px 0 8px;padding:14px;border-radius:10px;background:#f1f7e8;
              font-size:14px;line-height:1.6;font-weight:bold">{escape(result["recommendation"])}</p>
            <p style="font-size:11px;line-height:1.6;color:#7b897d">{escape(result["advisory"])}</p>
          </td></tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>"""
    message.add_alternative(html_body, subtype="html")
    return message


def send_email(message: EmailMessage) -> None:
    host = os.getenv("SMTP_HOST")
    sender = os.getenv("SMTP_SENDER")
    if not host or not sender:
        raise RuntimeError("Email delivery is not configured: SMTP_HOST and SMTP_SENDER are required.")
    try:
        port = int(os.getenv("SMTP_PORT", "587"))
    except ValueError as exc:
        raise RuntimeError("SMTP_PORT must be a valid port number.") from exc
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    use_starttls = os.getenv("SMTP_USE_STARTTLS", "true").lower() in {"1", "true", "yes"}
    if username or password:
        if not username or not password:
            raise RuntimeError("Both SMTP_USERNAME and SMTP_PASSWORD must be configured together.")
    message["From"] = sender
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        if use_starttls:
            smtp.starttls()
        if username or password:
            smtp.login(username, password)
        smtp.send_message(message)


async def process_due_emails(
    now_utc: datetime | None = None,
    *,
    database_engine: Engine | None = None,
    weather_fetcher: Callable[..., Any] = fetch_weather,
    mailer: Callable[[EmailMessage], None] = send_email,
) -> dict[str, int]:
    now_utc = now_utc or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    database_engine = database_engine or engine
    recipients = _load_recipients(database_engine)
    due_recipients = []
    failed = 0
    for recipient in recipients:
        try:
            local_now = _local_time(now_utc, recipient.timezone, recipient.location)
        except (KeyError, TypeError, ValueError):
            failed += 1
            logger.exception("Could not resolve local time for %s", recipient.email_address)
            continue
        if local_now.hour == 5 and local_now.minute == 0:
            due_recipients.append(recipient)
    sent = 0

    for recipient in due_recipients:
        try:
            location = recipient.location
            latitude = float(location["latitude"])
            longitude = float(location["longitude"])
            forecast = await weather_fetcher(latitude, longitude)
            result = calculate_recommendation(
                forecast=forecast,
                latitude=latitude,
                longitude=longitude,
                skin_type=recipient.skin_type,
                clothing_density=DEFAULT_CLOTHING_DENSITY,
                location_name=location.get("name"),
                current_utc=now_utc,
            )
            message = create_daily_email(recipient, result)
            await asyncio.to_thread(mailer, message)
            sent += 1
            logger.info("Daily Vitamin D email sent to %s", recipient.email_address)
        except Exception:
            failed += 1
            logger.exception("Daily Vitamin D email failed for %s", recipient.email_address)

    return {"due": len(due_recipients), "sent": sent, "failed": failed}


def run_scheduled_email_job() -> None:
    from app.main import REQUEST_ID

    token = REQUEST_ID.set(f"email-notification-{uuid.uuid4()}")
    try:
        summary = asyncio.run(process_due_emails())
        logger.info(
            "Daily email notification run completed: due=%d sent=%d failed=%d",
            summary["due"],
            summary["sent"],
            summary["failed"],
        )
    except Exception:
        logger.exception("Daily email notification run could not query recipients")
    finally:
        REQUEST_ID.reset(token)


def create_email_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=timezone.utc)
    scheduler.add_job(
        run_scheduled_email_job,
        trigger=CronTrigger(minute="*/15", timezone=timezone.utc),
        id="daily-vitamin-d-email-notifications",
        name="Send daily exposure emails at each recipient's local 05:00",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
    )
    return scheduler
