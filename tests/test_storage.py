"""An offline replay is repeatable and can be inspected after process restart."""

from pathlib import Path

from luk_replay.engine.replay import replay
from luk_replay.ingest.csv_import import read_bars
from luk_replay.storage.sqlite_store import SQLiteStore


FIXTURE = Path(__file__).parent / "fixtures" / "short_session.csv"


def test_replay_twice_produces_identical_decision_event_stream(tmp_path: Path) -> None:
    bars = read_bars(FIXTURE)
    first = replay(bars)
    second = replay(bars)
    assert tuple(e.as_record() for e in first.events) == tuple(
        e.as_record() for e in second.events
    )
    with SQLiteStore(tmp_path / "runs.db") as store:
        run_id = store.save_run(first)
        assert store.save_run(second) == run_id
        assert store.get_events(run_id) == [e.as_record() for e in first.events]
        assert store.list_runs()[0]["run_id"] == run_id
    with SQLiteStore(tmp_path / "runs.db") as reopened:
        assert reopened.get_events(run_id) == [e.as_record() for e in first.events]


def test_store_rejects_unknown_run_without_mutating_history(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "runs.db") as store:
        assert store.get_events("no-such-run") == []
        assert store.list_runs() == []
