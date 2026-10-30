"""Dashboard HTTP routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from src.azerothcore import get_azerothcore_status
from src.clamav import get_clamav_status
from src.domoticz import get_domoticz_status
from src.homeassistant import get_homeassistant_status
from src.qr import qr_png_bytes
from src.samba import add_samba_user, get_samba_status, remove_samba_user, smb_connect_url
from src.storage import get_raid_status
from src.transmission import get_transmission_status, transmission_client
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
from src.sleep_schedule import apply_schedule, get_schedule_status, set_schedule_enabled, suspend_now

router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


def _settings(request: Request):
    return request.app.state.settings


def _layout_context(settings) -> dict:
    host = get_host_metrics(sample_cpu=True, include_ollama=False)
    return {
        "hostname": get_hostname_label(settings.hostname_label),
        "host": host,
        "uptime": format_uptime(host["uptime_seconds"]),
        "now_str": datetime.now().strftime("%A %d %b %Y · %H:%M"),
    }


def _processes_context(settings) -> dict[str, Any]:
    view = get_top_processes(
        settings.top_processes_limit,
        process_labels=settings.process_labels,
    )
    host = get_host_metrics(sample_cpu=True)
    return {
        "processes": view["processes"],
        "processes_meta": view,
        "host_cpu_percent": host["cpu_percent"],
    }


def _status_context(settings) -> dict:
    host = get_host_metrics(sample_cpu=True)
    processes = _processes_context(settings)
    return {
        "hostname": get_hostname_label(settings.hostname_label),
        "host": host,
        "uptime": format_uptime(host["uptime_seconds"]),
        "now_str": datetime.now().strftime("%A %d %b %Y · %H:%M"),
        "services": list_services(
            settings.services,
            homeassistant=get_homeassistant_status(settings.homeassistant),
            domoticz=get_domoticz_status(settings.domoticz),
        ),
        "schedule": get_schedule_status(settings.sleep_schedule),
        **processes,
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


@router.get("/management", response_class=HTMLResponse)
def management_page(request: Request):
    settings = _settings(request)
    status = _layout_context(settings)
    status["schedule"] = get_schedule_status(settings.sleep_schedule)
    ctx = {
        "page_title": "Mini-PC management",
        "active_nav": "management",
        "status": status,
    }
    return _templates(request).TemplateResponse(request, "management.html", ctx)


@router.get("/schedule", response_class=HTMLResponse)
def schedule_page_redirect(request: Request):
    return RedirectResponse("/management", status_code=301)


@router.get("/partials/sleep-schedule", response_class=HTMLResponse)
def sleep_schedule_partial(request: Request):
    settings = _settings(request)
    return _templates(request).TemplateResponse(
        request,
        "partials/sleep_schedule.html",
        {"schedule": get_schedule_status(settings.sleep_schedule)},
    )


def _storage_context(settings) -> dict:
    return {
        "raid": get_raid_status(
            md_device=settings.storage.md_device,
            mount=settings.storage.mount,
        ),
        "samba": get_samba_status(settings.samba),
        "transmission": get_transmission_status(settings.transmission),
        "clamav": get_clamav_status(settings.clamav),
    }


@router.get("/storage", response_class=HTMLResponse)
def storage_page(request: Request):
    settings = _settings(request)
    storage_ctx = _storage_context(settings)
    ctx = {
        "page_title": "RAID storage",
        "active_nav": "storage",
        "status": _layout_context(settings),
        "storage": storage_ctx,
        **storage_ctx,
    }
    return _templates(request).TemplateResponse(request, "storage.html", ctx)


@router.get("/partials/storage-overview", response_class=HTMLResponse)
def storage_overview_partial(request: Request):
    settings = _settings(request)
    return _templates(request).TemplateResponse(
        request,
        "partials/storage_overview.html",
        _storage_context(settings),
    )


@router.get("/storage/samba-qr.png")
def samba_qr_png(request: Request):
    settings = _settings(request)
    url = smb_connect_url(settings.samba.unc_path)
    return Response(
        content=qr_png_bytes(url),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
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


@router.get("/partials/dashboard-metrics", response_class=HTMLResponse)
def dashboard_metrics_partial(request: Request):
    settings = _settings(request)
    host = get_host_metrics(sample_cpu=True)
    return _templates(request).TemplateResponse(
        request,
        "partials/dashboard_metrics.html",
        {
            "host": host,
            "services": list_services(
                settings.services,
                homeassistant=get_homeassistant_status(settings.homeassistant),
                domoticz=get_domoticz_status(settings.domoticz),
            ),
            "hostname": get_hostname_label(settings.hostname_label),
        },
    )


@router.get("/partials/services", response_class=HTMLResponse)
def services_partial(request: Request):
    settings = _settings(request)
    detail = request.query_params.get("detail") == "1"
    controls = detail
    ctx: dict = {
        "services": list_services(
            settings.services,
            homeassistant=get_homeassistant_status(settings.homeassistant),
            domoticz=get_domoticz_status(settings.domoticz),
        ),
        "detail": detail,
        "controls": controls,
        "ac": get_azerothcore_status(settings.azerothcore),
        "ha": get_homeassistant_status(settings.homeassistant),
        "dz": get_domoticz_status(settings.domoticz),
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
        _processes_context(settings),
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
    return RedirectResponse("/management", status_code=303)


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


def _power_action_response(request: Request, ok: bool, message: str):
    if request.headers.get("HX-Request"):
        return _templates(request).TemplateResponse(
            request,
            "partials/action_result.html",
            {"ok": ok, "message": message},
        )
    if not ok:
        raise HTTPException(status_code=500, detail=message)
    return RedirectResponse("/", status_code=303)


@router.post("/actions/suspend-now")
def action_suspend_now(request: Request):
    settings = _settings(request)
    ok, message = suspend_now(settings.sleep_schedule)
    return _power_action_response(request, ok, message)


def _storage_action_response(request: Request, ok: bool, message: str):
    if request.headers.get("HX-Request"):
        return _templates(request).TemplateResponse(
            request,
            "partials/action_result.html",
            {"ok": ok, "message": message},
            headers={"HX-Trigger": "refreshStorage"},
        )
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return RedirectResponse("/storage", status_code=303)


@router.post("/actions/samba-add-user")
def action_samba_add_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    settings = _settings(request)
    ok, message = add_samba_user(settings.samba, username, password)
    return _storage_action_response(request, ok, message)


@router.post("/actions/samba-remove-user")
def action_samba_remove_user(request: Request, username: str = Form(...)):
    settings = _settings(request)
    ok, message = remove_samba_user(settings.samba, username)
    return _storage_action_response(request, ok, message)


@router.post("/actions/torrent-upload")
async def action_torrent_upload(
    request: Request,
    torrent_file: UploadFile = File(...),
):
    settings = _settings(request)
    name = (torrent_file.filename or "").lower()
    if not name.endswith(".torrent"):
        return _storage_action_response(request, False, "Upload a .torrent file")
    data = await torrent_file.read()
    if not data:
        return _storage_action_response(request, False, "Empty file")
    try:
        client = transmission_client(settings.transmission)
        client.add_torrent_bytes(data, settings.transmission.download_dir)
    except Exception as exc:  # noqa: BLE001
        return _storage_action_response(request, False, str(exc))
    return _storage_action_response(request, True, f"Added torrent {torrent_file.filename}")


@router.post("/actions/torrent-add-magnet")
def action_torrent_add_magnet(request: Request, magnet: str = Form(...)):
    settings = _settings(request)
    if not magnet.strip().startswith("magnet:"):
        return _storage_action_response(request, False, "Paste a magnet: link")
    try:
        transmission_client(settings.transmission).add_torrent_magnet(magnet)
    except Exception as exc:  # noqa: BLE001
        return _storage_action_response(request, False, str(exc))
    return _storage_action_response(request, True, "Magnet link added")


@router.post("/actions/torrent-remove")
def action_torrent_remove(
    request: Request,
    torrent_id: int = Form(...),
    delete_data: str = Form("false"),
):
    settings = _settings(request)
    try:
        transmission_client(settings.transmission).remove_torrent(
            torrent_id,
            delete_data=delete_data == "true",
        )
    except Exception as exc:  # noqa: BLE001
        return _storage_action_response(request, False, str(exc))
    return _storage_action_response(request, True, "Torrent removed")


@router.post("/actions/torrent-start")
def action_torrent_start(request: Request, torrent_id: int = Form(...)):
    settings = _settings(request)
    try:
        transmission_client(settings.transmission).start_torrent(torrent_id)
    except Exception as exc:  # noqa: BLE001
        return _storage_action_response(request, False, str(exc))
    return _storage_action_response(request, True, "Torrent started")


@router.post("/actions/torrent-stop")
def action_torrent_stop(request: Request, torrent_id: int = Form(...)):
    settings = _settings(request)
    try:
        transmission_client(settings.transmission).stop_torrent(torrent_id)
    except Exception as exc:  # noqa: BLE001
        return _storage_action_response(request, False, str(exc))
    return _storage_action_response(request, True, "Torrent stopped")


@router.get("/api/health")
def health_check():
    return {"status": "ok", "app": "mini-pc-monitor"}


@router.get("/api/status")
def status_api(request: Request):
    settings = _settings(request)
    return _status_context(settings)
