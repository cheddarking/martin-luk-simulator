"""CLI operations must be local and report real decisions, not only test status."""

import json
import socket
from pathlib import Path

import pytest

from luk_replay.cli import main


FIXTURE = Path(__file__).parent / "fixtures" / "short_session.csv"


def test_offline_replay_works_without_network(capsys: object, monkeypatch: pytest.MonkeyPatch) -> None:
    def reject_connect(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("replay unexpectedly attempted network access")

    monkeypatch.setattr(socket.socket, "connect", reject_connect)
    result = main(["replay", str(FIXTURE), "--no-store"])
    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["symbol"] == "EXAMPLE"
    assert payload["decisions"] == 3
    assert payload["entries"] == 0
    assert payload["reasons"]["NO_DATA"] == 3


def test_generate_and_replay_synthetic_trade_from_cli(tmp_path: Path, capsys: object) -> None:
    prices = tmp_path / "prices.csv"
    daily = tmp_path / "daily.csv"
    assert main(["generate", str(prices), "--scenario", "steady", "--minutes", "75",
                 "--initial", "107.98"]) == 0
    capsys.readouterr()
    assert main(["generate", str(daily), "--daily-lookback"]) == 0
    capsys.readouterr()
    assert main(["replay", str(prices), "--daily-csv", str(daily), "--no-store"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["entries"] >= 1


def test_real_format_daily_history_stays_offline(tmp_path: Path, capsys: object,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    data = (Path(__file__).parent / "fixtures" / "daily_yahoo_format.csv").read_text()
    (tmp_path / "EXAMPLE.csv").write_text(data, encoding="utf-8")
    def no_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("offline daily replay attempted a network request")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    assert main(["history", "status", "--source-dir", str(tmp_path),
                 "--symbols", "EXAMPLE"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["symbols"]["EXAMPLE"]["complete_six_years"] is False
    assert main(["replay-daily", "EXAMPLE", "--source-dir", str(tmp_path),
                 "--no-store"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["timeframe"] == "daily"
    assert result["source"] == "yfinance_cache"
    assert result["decisions"] == 2


def test_market_clock_diagnostic_reports_early_close(capsys: object) -> None:
    assert main(["market-day", "2026-11-27"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["early_close"] is True
    assert data["close_local"].startswith("2026-11-27T13:00:00")
    assert main(["market-day", "2026-12-25"]) == 2
    assert "closed" in capsys.readouterr().err


def test_cli_reports_invalid_import_and_exit_code(tmp_path: Path, capsys: object) -> None:
    wrong = tmp_path / "missing.csv"
    assert main(["replay", str(wrong), "--no-store"]) == 2
    assert "error" in capsys.readouterr().err
