"""Dashboard HTTP routes."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from src.azerothcore import get_azerothcore_status
from src.config_loader import load_settings, loggable_service_units, manageable_service_units
from src.service_logs import get_service_logs
from src.metrics import get_host_metrics, get_top_processes
from src.services import (
    format_uptime,
    get_hostname_label,
    list_services,
    restart_service,
    start_service,
    stop_service,
)
from src.sleep_schedule import apply_schedule, get_schedule_status, set_schedule_enabled

router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


def _settings(request: Request):
    return request.app.state.settings


def _layout_context(settings) -> dict:
    host = get_host_metrics(sample_cpu=False, include_ollama=False)
    return {
        "hostname": get_hostname_label(settings.hostname_label),
        "host": host,
        "uptime": format_uptime(host["uptime_seconds"]),
        "now_str": datetime.now().strftime("%A %d %b %Y · %H:%M"),
    }


def _status_context(settings) -> dict:
    host = get_host_metrics(sample_cpu=False)
    return {
        "hostname": get_hostname_label(settings.hostname_label),
        "host": host,
        "uptime": format_uptime(host["uptime_seconds"]),
        "now_str": datetime.now().strftime("%A %d %b %Y · %H:%M"),
        "services": list_services(settings.services),
        "top_processes": get_top_processes(
            settings.top_processes_limit,
            process_labels=settings.process_labels,
        ),
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


@router.get("/schedule", response_class=HTMLResponse)
def schedule_page(request: Request):
    settings = _settings(request)
    ctx = {
        "page_title": "Sleep schedule",
        "active_nav": "schedule",
        "status": _layout_context(settings),
    }
    return _templates(request).TemplateResponse(request, "schedule.html", ctx)


@router.get("/partials/sleep-schedule", response_class=HTMLResponse)
def sleep_schedule_partial(request: Request):
    settings = _settings(request)
    return _templates(request).TemplateResponse(
        request,
        "partials/sleep_schedule.html",
        {"schedule": get_schedule_status(settings.sleep_schedule)},
    )


@router.get("/services", response_class=HTMLResponse)
def services_page(request: Request):
    settings = _settings(request)
    ctx = {
        "page_title": "Services",
        "active_nav": "services",
        "status": _layout_context(settings),
        "service_count": len(settings.services),
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
    detail = request.query_params.get("detail") == "1"
    controls = detail
    ctx: dict = {
        "services": list_services(settings.services),
        "detail": detail,
        "controls": controls,
        "ac": get_azerothcore_status(settings.azerothcore),
    }
    return _templates(request).TemplateResponse(
        request,
        "partials/services_list.html",
        ctx,
    )


@router.get("/partials/service-logs", response_class=HTMLResponse)
def service_logs_partial(request: Request, unit: str):
    settings = _settings(request)
    if unit not in loggable_service_units(settings):
        raise HTTPException(status_code=400, detail="Service logs not enabled")
    return _templates(request).TemplateResponse(
        request,
        "partials/service_logs.html",
        {"log": get_service_logs(unit, settings)},
    )


@router.get("/partials/processes", response_class=HTMLResponse)
def processes_partial(request: Request):
    settings = _settings(request)
    return _templates(request).TemplateResponse(
        request,
        "partials/processes.html",
        {
            "processes": get_top_processes(
                settings.top_processes_limit,
                process_labels=settings.process_labels,
            )
        },
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


def _schedule_action_response(request: Request, ok: bool, message: str):
    if request.headers.get("HX-Request"):
        return _templates(request).TemplateResponse(
            request,
            "partials/action_result.html",
            {"ok": ok, "message": message},
            headers={"HX-Trigger": "refreshSchedule"},
        )
    if not ok:
        raise HTTPException(status_code=500, detail=message)
    return RedirectResponse("/schedule", status_code=303)


@router.post("/actions/update-sleep-schedule")
def action_update_sleep_schedule(
    request: Request,
    sleep_time: str = Form(...),
    wake_time: str = Form(...),
):
    settings = _settings(request)
    ok, message = apply_schedule(
        settings.sleep_schedule,
        sleep_time=sleep_time,
        wake_time=wake_time,
    )
    return _schedule_action_response(request, ok, message)


@router.post("/actions/toggle-sleep-schedule")
def action_toggle_sleep_schedule(request: Request, enabled: str = Form(...)):
    settings = _settings(request)
    ok, message = set_schedule_enabled(
        settings.sleep_schedule,
        enabled=enabled == "true",
    )
    return _schedule_action_response(request, ok, message)


@router.get("/api/health")
def health_check():
    return {"status": "ok", "app": "mini-pc-monitor"}


@router.get("/api/status")
def status_api(request: Request):
    settings = _settings(request)
    return _status_context(settings)
