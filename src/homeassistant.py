"""Home Assistant (Docker) runtime status."""

from __future__ import annotations

import re
import subprocess
import urllib.error
import urllib.request
from typing import Any

from src.config_loader import HomeAssistantConfig

_RFLINK_GATEWAY = re.compile(r"RFLink Gateway", re.I)


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _http_reachable(url: str) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.status in (200, 302, 303, 307, 308)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def _container_state(name: str) -> str:
    result = _run(
        [
            "docker",
            "inspect",
            "-f",
            "{{.State.Status}}",
            name,
        ]
    )
    if result.returncode != 0:
        return "missing"
    return (result.stdout or "").strip() or "unknown"


def _systemd_active(unit: str) -> str:
    result = _run(["systemctl", "is-active", unit])
    return (result.stdout or "").strip() or "unknown"


def _rflink_from_logs(container: str, *, lines: int = 80) -> bool | None:
    result = _run(["docker", "logs", "--tail", str(lines), container])
    if result.returncode != 0:
        return None
    return bool(_RFLINK_GATEWAY.search(result.stdout or result.stderr or ""))


def get_homeassistant_status(config: HomeAssistantConfig) -> dict[str, Any] | None:
    if not config.enabled:
        return None

    systemd = _systemd_active(config.systemd_unit)
    container = _container_state(config.container_name)
    http_ok = _http_reachable(config.health_url)
    rflink = _rflink_from_logs(config.container_name) if container == "running" else None

    ready = container == "running" and http_ok

    if ready and rflink:
        overall = "ok"
    elif container == "running" and http_ok:
        overall = "amber"
    elif container == "running":
        overall = "amber"
    elif systemd == "active":
        overall = "warn"
    else:
        overall = "warn"

    rflink_state = "unknown"
    rflink_detail = "Start container to check gateway logs"
    rflink_level = "no_action"
    if container != "running":
        rflink_detail = "Container not running"
        rflink_state = "offline"
        rflink_level = "warn"
    elif rflink is True:
        rflink_state = "connected"
        rflink_detail = "433 MHz RFLink gateway seen in logs"
        rflink_level = "ok"
    elif rflink is False:
        rflink_state = "not seen"
        rflink_detail = "No RFLink banner in recent container logs"
        rflink_level = "amber"

    components = [
        {
            "label": "Docker",
            "state": container,
            "detail": config.container_name,
            "level": "ok" if container == "running" else "warn",
        },
        {
            "label": "Web UI",
            "state": "reachable" if http_ok else "unreachable",
            "detail": config.health_url,
            "level": "ok" if http_ok else "warn",
        },
        {
            "label": "RFLink",
            "state": rflink_state,
            "detail": rflink_detail,
            "level": rflink_level,
        },
    ]

    if ready and rflink:
        summary = "Home Assistant online · RFLink gateway connected"
    elif ready:
        summary = "Home Assistant online · check RFLink USB if 433 MHz devices fail"
    elif container == "running":
        summary = "Container running · web UI not responding yet"
    elif systemd == "active":
        summary = "systemd unit active · Docker container not running"
    else:
        summary = "Home Assistant stopped"

    return {
        "unit": config.systemd_unit,
        "overall": overall,
        "ready": ready,
        "systemd_active": systemd,
        "container": container,
        "http_reachable": http_ok,
        "rflink_connected": rflink,
        "summary": summary,
        "components": components,
    }


def docker_log_entries(container: str, *, lines: int = 40) -> tuple[list[dict[str, str]], str | None]:
    result = _run(["docker", "logs", "--tail", str(lines), "--timestamps", container])
    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "docker logs failed").strip()
        return [], msg
    entries: list[dict[str, str]] = []
    for line in (result.stdout or "").splitlines():
        text = line.strip()
        if not text:
            continue
        time = ""
        message = text
        if text.startswith("20") and " " in text:
            ts, _, rest = text.partition(" ")
            if "T" in ts or ts.count("-") >= 2:
                time = ts.split("T")[-1].split("+")[0].split("Z")[0][:8]
                message = rest.strip()
        entries.append({"time": time, "message": message})
    entries.reverse()
    return entries, None
