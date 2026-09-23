"""FastAPI application — mini-PC monitoring dashboard (no background jobs)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.config_loader import load_settings
from src.web.routes import router

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = Jinja2Templates(directory=str(ROOT / "templates"))
STYLE_PATH = ROOT / "static" / "style.css"
TEMPLATES.env.globals["static_version"] = (
    int(STYLE_PATH.stat().st_mtime) if STYLE_PATH.is_file() else 0
)


def create_app() -> FastAPI:
    settings = load_settings()
    app = FastAPI(title="Mini-PC Monitor")
    app.state.settings = settings
    app.state.templates = TEMPLATES
    static_dir = ROOT / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.include_router(router)
    return app


app = create_app()
