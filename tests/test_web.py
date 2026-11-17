"""Local web endpoints expose evidence without fabricating market history."""

from pathlib import Path

from fastapi.testclient import TestClient

from luk_replay.web.app import create_app


FIXTURE = Path(__file__).parent / "fixtures" / "short_session.csv"


def test_run_detail_exposes_asof_reason_and_no_future_prices(tmp_path: Path) -> None:
    app = create_app(db_path=tmp_path / "runs.db")
    with TestClient(app) as client:
        imported = client.post("/api/replay", json={"bars_csv": FIXTURE.read_text()})
        assert imported.status_code == 200
        run_id = imported.json()["run_id"]
        assert imported.json()["summary"]["decisions"] == 3
        response = client.get(f"/api/runs/{run_id}/events")
        assert response.status_code == 200
        events = response.json()["events"]
        assert events[0]["as_of"] == "2026-11-16T14:31:00+00:00"
        assert events[0]["details"]["close_usd"] == "115.04"
        assert events[1]["reason"] == "NO_DATA"
        assert "115.18" not in str(events[:2])
        assert client.get(f"/runs/{run_id}").status_code == 200


def test_no_price_cache_shows_setup_not_synthetic_chart(tmp_path: Path) -> None:
    app = create_app(db_path=tmp_path / "runs.db", history_dir=tmp_path / "missing")
    with TestClient(app) as client:
        assert client.get("/api/history").json()["count"] == 0
        page = client.get("/").text
        assert "Add private daily prices" in page
        assert "Load synthetic session" not in page
        assert client.get("/api/demo").status_code == 404


def test_cached_daily_source_is_visible_with_provenance(tmp_path: Path) -> None:
    prices = tmp_path / "history"
    prices.mkdir()
    (prices / "AAPL.csv").write_bytes(
        (Path(__file__).parent / "fixtures" / "daily_yahoo_format.csv").read_bytes())
    app = create_app(db_path=tmp_path / "runs.db", history_dir=prices)
    with TestClient(app) as client:
        listing = client.get("/api/history").json()
        assert listing["count"] == 1
        assert listing["symbols"][0]["symbol"] == "AAPL"
        payload = client.post("/api/history/AAPL/replay").json()
        saved = client.get("/api/runs/" + payload["run_id"]).json()["summary"]
    assert saved["source_kind"] == "yfinance_cache"
    assert saved["timeframe"] == "daily"
    assert saved["adjustment"] == "unknown"
    assert payload["source_kind"] == "yfinance_cache"
    assert payload["timeframe"] == "daily"
    assert payload["adjustment"] == "unknown"
    assert len(payload["series"]) == 2


def test_invalid_csv_and_unknown_run_have_distinct_errors(tmp_path: Path) -> None:
    app = create_app(db_path=tmp_path / "runs.db")
    with TestClient(app) as client:
        assert client.post("/api/replay", json={"bars_csv": "broken"}).status_code == 422
        assert client.get("/api/runs/nonexistent/events").status_code == 404
        assert client.get("/").status_code == 200
