"""Playwright check against a real localhost server; no external assets."""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright

from luk_replay.web.app import create_app
from luk_replay.ingest.synthetic import make_session, write_session


@pytest.fixture
def local_server(tmp_path: Path) -> str:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    history = tmp_path / "history"
    history.mkdir()
    (history / "AAPL.csv").write_bytes(
        (Path(__file__).parents[1] / "fixtures" / "daily_yahoo_format.csv").read_bytes())
    app = create_app(db_path=tmp_path / "runs.db", history_dir=history)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                            log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=5)
        pytest.fail("local uvicorn did not start")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_local_browser_can_inspect_decision(local_server: str) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(local_server)
            assert page.get_by_role("heading", name="Replay the decision").is_visible()
            expect(page.get_by_label("Stock or index fund")).to_have_value("AAPL")
            page.get_by_role("button", name="Replay daily history").click()
            expect(page.get_by_text("INSUFFICIENT_HISTORY").first).to_be_visible()
            expect(page.get_by_text("cached daily prices")).to_be_visible()
            page.get_by_text("See the price observations as a table").click()
            expect(page.get_by_role("table", name="Price observations")).to_be_visible()
            assert not page.get_by_role("button", name="Place live trade").count()
        finally:
            browser.close()


def test_saved_multi_day_run_shows_all_decisions(local_server: str, tmp_path: Path) -> None:
    csv_path = write_session(
        tmp_path / "two_sessions.csv",
        make_session("2026-11-16") + make_session("2026-11-17"),
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            response = page.request.post(local_server + "/api/replay",
                                         data={"bars_csv": csv_path.read_text()})
            assert response.ok
            run_id = response.json()["run_id"]
            page.goto(local_server + "/runs/" + run_id)
            expect(page.locator("#decisions li")).to_have_count(780)
            expect(page.locator("#price-rows tr")).to_have_count(780)
        finally:
            browser.close()
