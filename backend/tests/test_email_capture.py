from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlmodel import Session, select

from app import email_capture
from app.email_capture import EmailList, timezone_offset_hours
from app.main import app

client = TestClient(app)


def _use_test_database(monkeypatch):
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(email_capture, "engine", test_engine)
    return test_engine


def _signup(email="alex@example.com", name="Alex", skin_type="III", location_name="Quito"):
    return {
        "email_address": email,
        "name": name,
        "latitude": -0.18,
        "longitude": -78.47,
        "location_name": location_name,
        "skin_type": skin_type,
    }


def test_email_signup_creates_unique_record(monkeypatch):
    test_engine = _use_test_database(monkeypatch)
    monkeypatch.setattr(email_capture, "_timezone_finder", lambda: _FixedTimezoneFinder("Asia/Kolkata"))
    response = client.post("/email_list", json=_signup())

    assert response.status_code == 200
    result = response.json()
    assert result["email_address"] == "alex@example.com"
    assert result["name"] == "Alex"
    assert result["skin_type"] == "III"
    assert result["location"] == {"name": "Quito", "latitude": -0.18, "longitude": -78.47}
    assert result["timezone"] == 5.5
    with Session(test_engine) as session:
        entries = session.exec(select(EmailList)).all()
    assert len(entries) == 1


def test_existing_email_updates_location_skin_and_timezone_but_keeps_name(monkeypatch):
    test_engine = _use_test_database(monkeypatch)
    monkeypatch.setattr(email_capture, "_timezone_finder", lambda: _FixedTimezoneFinder("UTC"))
    first = client.post("/email_list", json=_signup())
    updated = client.post(
        "/email_list",
        json={
            **_signup(email="ALEX@example.com", name="Alexandra", skin_type="V", location_name="Updated city"),
            "latitude": 51.5,
            "longitude": -0.12,
        },
    )

    assert first.status_code == 200
    assert updated.status_code == 200
    result = updated.json()
    assert result["id"] == first.json()["id"]
    assert result["email_address"] == "alex@example.com"
    assert result["name"] == "Alex"
    assert result["skin_type"] == "V"
    assert result["location"]["name"] == "Updated city"
    assert result["timezone"] == 0
    with Session(test_engine) as session:
        assert len(session.exec(select(EmailList)).all()) == 1


def test_timezone_for_unknown_location_is_a_validation_error(monkeypatch):
    _use_test_database(monkeypatch)
    monkeypatch.setattr(email_capture, "_timezone_finder", lambda: _FixedTimezoneFinder(None))
    response = client.post("/email_list", json=_signup())

    assert response.status_code == 422
    assert "timezone" in response.json()["detail"].lower()


def test_signup_rejects_invalid_email_and_coordinates(monkeypatch):
    _use_test_database(monkeypatch)
    invalid_email = client.post("/email_list", json=_signup(email="not-an-email"))
    invalid_coordinates = client.post("/email_list", json={**_signup(), "latitude": 91})

    assert invalid_email.status_code == 422
    assert invalid_coordinates.status_code == 422


def test_timezone_offset_is_calculated_for_current_dst_date(monkeypatch):
    monkeypatch.setattr(email_capture, "_timezone_finder", lambda: _FixedTimezoneFinder("Asia/Kolkata"))
    assert timezone_offset_hours(0, 0) == 5.5


def test_success_page_is_served_by_the_confirmation_endpoint(monkeypatch, tmp_path):
    confirmation = tmp_path / "successful_submission"
    confirmation.mkdir()
    (confirmation / "index.html").write_text("<main>Signup complete</main>", encoding="utf-8")
    monkeypatch.setattr("app.main.FRONTEND_DIR", tmp_path)

    response = client.get("/successful_submission")

    assert response.status_code == 200
    assert "Signup complete" in response.text


class _FixedTimezoneFinder:
    def __init__(self, timezone_name):
        self.timezone_name = timezone_name
        self.coordinates = None

    def timezone_at(self, *, lng, lat):
        self.coordinates = (lat, lng)
        return self.timezone_name
