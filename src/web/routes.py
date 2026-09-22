"""Dashboard HTTP routes."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from src.config_loader import load_settings, manageable_service_units
from src.metrics import get_host_metrics, get_top_processes
from src.services import (
    format_uptime,
    get_hostname_label,
    list_services,
    restart_service,
    start_service,
    stop_service,
)

router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


def _settings(request: Request):
    return request.app.state.settings


def _status_context(settings) -> dict:
    host = get_host_metrics(sample_cpu=False)
    return {
        "hostname": get_hostname_label(settings.hostname_label),
        "host": host,
        "uptime": format_uptime(host["uptime_seconds"]),
        "services": list_services(settings.services),
        "top_processes": get_top_processes(settings.top_processes_limit),
        "now_str": datetime.now().strftime("%A %d %b %Y · %H:%M"),
    }


@router.get("/", response_class=HTMLResponse)
def dashboard_home(request: Request):
    settings = _settings(request)
    ctx = {
        "page_title": "Dashboard",
        "active_nav": "dashboard",
        "status": _status_context(settings),
    }
    return _templates(request).TemplateResponse(request, "dashboard.html", ctx)


@router.get("/services", response_class=HTMLResponse)
def services_page(request: Request):
    settings = _settings(request)
    ctx = {
        "page_title": "Services",
        "active_nav": "services",
        "status": _status_context(settings),
    }
    return _templates(request).TemplateResponse(request, "services.html", ctx)


@router.get("/partials/host-metrics", response_class=HTMLResponse)
def host_metrics_partial(request: Request):
    host = get_host_metrics(sample_cpu=True)
    return _templates(request).TemplateResponse(
        request,
        "partials/host_metrics.html",
        {"host": host},
    )


@router.get("/partials/services", response_class=HTMLResponse)
def services_partial(request: Request):
    settings = _settings(request)
    return _templates(request).TemplateResponse(
        request,
        "partials/services_list.html",
        {"services": list_services(settings.services)},
    )


@router.get("/partials/processes", response_class=HTMLResponse)
def processes_partial(request: Request):
    settings = _settings(request)
    return _templates(request).TemplateResponse(
        request,
        "partials/processes.html",
        {"processes": get_top_processes(settings.top_processes_limit)},
    )


def _service_action_response(
    request: Request,
    unit: str,
    ok: bool,
    message: str,
):
    if request.headers.get("HX-Request"):
        return _templates(request).TemplateResponse(
            request,
            "partials/action_result.html",
            {"ok": ok, "message": message},
            headers={"HX-Trigger": "refreshServices"},
        )
    if not ok:
        raise HTTPException(status_code=500, detail=message)
    return RedirectResponse("/services", status_code=303)


def _assert_manageable_unit(request: Request, unit: str) -> None:
    settings = _settings(request)
    if unit not in manageable_service_units(settings):
        raise HTTPException(status_code=400, detail="Service not allowed")


@router.post("/actions/start-service")
def action_start_service(request: Request, unit: str = Form(...)):
    _assert_manageable_unit(request, unit)
    ok, message = start_service(unit)
    return _service_action_response(request, unit, ok, message)


@router.post("/actions/stop-service")
def action_stop_service(request: Request, unit: str = Form(...)):
    _assert_manageable_unit(request, unit)
    ok, message = stop_service(unit)
    return _service_action_response(request, unit, ok, message)


@router.post("/actions/restart-service")
def action_restart_service(request: Request, unit: str = Form(...)):
    _assert_manageable_unit(request, unit)
    ok, message = restart_service(unit)
    return _service_action_response(request, unit, ok, message)


@router.get("/api/health")
def health_check():
    return {"status": "ok", "app": "mini-pc-monitor"}


@router.get("/api/status")
def status_api(request: Request):
    settings = _settings(request)
    return _status_context(settings)
