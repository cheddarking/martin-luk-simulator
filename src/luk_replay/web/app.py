"""Factory for a loopback-only FastAPI inspector with no network integrations."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import router as api_router
from .views import router as view_router


DEFAULT_DB = Path.home() / ".local" / "share" / "luk-replay" / "runs.db"
DEFAULT_HISTORY = Path.home() / ".local" / "share" / "luk-replay" / "history"


def create_app(*, db_path: str | Path = DEFAULT_DB,
               history_dir: str | Path = DEFAULT_HISTORY) -> FastAPI:
    app = FastAPI(
        title="Replay Lab", version="0.1.0",
        description="Local-only educational trading rule inspector, not a broker client.",
        docs_url=None, redoc_url=None,
    )
    app.state.db_path = Path(db_path)
    app.state.history_dir = Path(history_dir)
    app.include_router(view_router())
    app.include_router(api_router())
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"),
              name="static")
    return app
