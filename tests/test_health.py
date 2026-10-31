"""Data-health freshness rules and the /api/health/data endpoint."""
from datetime import date, datetime

from fastapi.testclient import TestClient

from app.main import app
from app.services.health import business_days_between, expected_date, freshness


def test_expected_date_respects_publish_hour():
    thu_morning = datetime(2026, 10, 29, 9, 0)  # Thursday before 15:00 -> Wednesday counts as fresh
    assert expected_date(thu_morning, 15) == date(2026, 10, 28)
    thu_afternoon = datetime(2026, 10, 29, 15, 30)
    assert expected_date(thu_afternoon, 15) == date(2026, 10, 29)
    assert expected_date(thu_afternoon, 17) == date(2026, 10, 28)  # institutional not out yet
    saturday = datetime(2026, 10, 31, 12, 0)
    assert expected_date(saturday, 22) == date(2026, 10, 30)  # weekend -> last Friday
    monday_early = datetime(2026, 11, 2, 8, 0)
    assert expected_date(monday_early, 15) == date(2026, 10, 30)


def test_freshness_levels():
    exp = date(2026, 10, 30)  # Friday
    assert freshness(None, exp) == "missing"
    assert freshness(date(2026, 10, 30), exp) == "ok"
    assert freshness(date(2026, 10, 29), exp) == "warn"
    assert freshness(date(2026, 10, 27), exp) == "bad"
    assert business_days_between(date(2026, 10, 30), date(2026, 11, 2)) == 1  # Fri -> Mon skips the weekend
    assert business_days_between(date(2026, 11, 2), date(2026, 10, 30)) == 0


def test_health_data_endpoint_shape():
    with TestClient(app) as c:
        r = c.get("/api/health/data")
    assert r.status_code == 200
    body = r.json()
    assert body["overall"] in {"ok", "warn", "bad"}
    tables = {t["table"]: t for t in body["tables"]}
    assert {"daily_prices", "institutional_flows", "margin_balances", "screener_results", "realtime_quotes", "stocks"} <= set(tables)
    assert all(t["status"] in {"ok", "warn", "bad", "missing", "idle"} for t in tables.values())
    assert "failed_24h" in body["jobs"] and "db_mb" in body["storage"]
