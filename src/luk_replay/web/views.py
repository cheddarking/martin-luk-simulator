"""Server-rendered inspector views; present derived explanations, not advice."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from luk_replay.storage.sqlite_store import SQLiteStore

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def router() -> APIRouter:
    pages = APIRouter()

    @pages.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(request, "index.html", {
            "page_title": "Replay the decision",
            "subtitle": "Inspect the information available when each rule made its call.",
        })

    @pages.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_detail(run_id: str, request: Request) -> HTMLResponse:
        with SQLiteStore(request.app.state.db_path) as store:
            summary = store.get_summary(run_id)
        if summary is None:
            raise HTTPException(status_code=404, detail="run not found")
        return TEMPLATES.TemplateResponse(request, "run.html", {
            "run_id": run_id,
            "page_title": "Recorded replay",
            "summary": summary,
        })

    @pages.get("/decisions/{run_id}/{sequence}", response_class=HTMLResponse)
    def decision_detail(run_id: str, sequence: int, request: Request) -> HTMLResponse:
        with SQLiteStore(request.app.state.db_path) as store:
            if not store.exists(run_id):
                raise HTTPException(status_code=404, detail="run not found")
            events = store.get_events(run_id, offset=sequence, limit=1)
        if not events:
            raise HTTPException(status_code=404, detail="event not found")
        return TEMPLATES.TemplateResponse(request, "decision.html", {
            "page_title": "Decision evidence", "run_id": run_id, "event": events[0],
        })

    return pages
