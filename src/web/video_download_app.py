"""Standalone video download web app (separate port from the mini-PC dashboard)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.config_loader import load_settings
from src.video_download import get_video_download_status, start_download

ROOT = Path(__file__).resolve().parents[2]
STYLE_PATH = ROOT / "static" / "style.css"


def create_app() -> FastAPI:
    settings = load_settings()
    app = FastAPI(title="Video Download")
    app.state.settings = settings
    templates = Jinja2Templates(directory=str(ROOT / "templates"))
    templates.env.globals["static_version"] = (
        int(STYLE_PATH.stat().st_mtime) if STYLE_PATH.is_file() else 0
    )
    app.state.templates = templates

    static_dir = ROOT / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    def _templates(request: Request):
        return request.app.state.templates

    def _settings(request: Request):
        return request.app.state.settings

    def _context(request: Request) -> dict:
        cfg = _settings(request).video_download
        return {"video_download": get_video_download_status(cfg)}

    def _require_enabled(request: Request) -> None:
        if not _settings(request).video_download.enabled:
            raise HTTPException(status_code=404, detail="Video download disabled")

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        _require_enabled(request)
        cfg = _settings(request).video_download
        return _templates(request).TemplateResponse(
            request,
            "video_download.html",
            {"page_title": "Video download", **_context(request), "public_url": cfg.public_url},
        )

    @app.get("/partials/overview", response_class=HTMLResponse)
    def overview_partial(request: Request):
        _require_enabled(request)
        return _templates(request).TemplateResponse(
            request,
            "partials/video_download_overview.html",
            _context(request),
        )

    def _action_response(request: Request, ok: bool, message: str):
        if request.headers.get("HX-Request"):
            return _templates(request).TemplateResponse(
                request,
                "partials/action_result.html",
                {"ok": ok, "message": message},
                headers={"HX-Trigger": "refreshVideoDownload"},
            )
        if not ok:
            raise HTTPException(status_code=400, detail=message)
        return RedirectResponse("/", status_code=303)

    @app.post("/actions/download")
    def action_download(request: Request, url: str = Form(...)):
        _require_enabled(request)
        cfg = _settings(request).video_download
        ok, message, _job_id = start_download(url, cfg)
        return _action_response(request, ok, message)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "app": "video-download"}

    return app


app = create_app()
