"""Fetch recent journal activity for configured services."""

from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.request
from typing import Any

from src.config_loader import AzerothCoreConfig, Settings

_JOURNAL_LINE = re.compile(
    r"^(?P<time>\S+)\s+\S+\s+(?P<unit>\S+?)(?:\[\d+\])?:\s*(?P<message>.*)$"
)
_OLLAMA_GIN = re.compile(
    r"\[GIN\].*- (?P<time>\d{2}:\d{2}:\d{2}) \| (?P<status>\d+) \|.*\| (?P<method>[A-Z]+)\s+\"(?P<path>[^\"]+)\""
)


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _fetch_json(url: str) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, dict) else None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def parse_journal_line(line: str) -> dict[str, str]:
    match = _JOURNAL_LINE.match(line.strip())
    if match:
        time = match.group("time")
        if "T" in time:
            time = time.split("T", 1)[1].split("+")[0].split("-")[0]
        message = match.group("message").strip()
        gin = _OLLAMA_GIN.search(message)
        if gin:
            message = f"{gin.group('method')} {gin.group('path')} → {gin.group('status')}"
            time = gin.group("time") or time
        return {"time": time, "message": message}
    return {"time": "", "message": line.strip()}


def _tmux_entries(session: str, *, lines: int = 12, prefix: str) -> list[dict[str, str]]:
    result = _run(["tmux", "capture-pane", "-t", session, "-p", "-S", f"-{lines}"])
    if result.returncode != 0:
        return [{"time": "", "message": f"[{prefix}] session not available"}]
    rows: list[dict[str, str]] = []
    for line in (result.stdout or "").splitlines():
        text = line.rstrip()
        if not text or text.startswith("sylvester@"):
            continue
        rows.append({"time": "", "message": f"[{prefix}] {text}"})
    captured = rows[-lines:]
    captured.reverse()
    return captured


def _journal_entries(unit: str, *, lines: int = 40) -> tuple[list[dict[str, str]], str | None]:
    result = _run(
        [
            "journalctl",
            "-u",
            unit,
            "-n",
            str(lines),
            "--no-pager",
            "-o",
            "short-iso",
        ]
    )
    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "journalctl failed").strip()
        return [], msg
    entries = [
        parse_journal_line(line)
        for line in (result.stdout or "").splitlines()
        if line.strip()
    ]
    entries.reverse()
    return entries, None


def _systemd_summary(unit: str) -> tuple[list[dict[str, str]], list[str]]:
    result = _run(["systemctl", "is-active", unit])
    active = (result.stdout or "").strip()
    if active == "active":
        badge = {"label": "running", "level": "ok"}
    elif active in ("activating", "reloading"):
        badge = {"label": active, "level": "amber"}
    else:
        badge = {"label": active or "unknown", "level": "warn"}
    return [badge], [f"systemd: {active}"]


def _good_search_summary() -> tuple[list[dict[str, str]], list[str]]:
    health = _fetch_json("http://127.0.0.1:8765/health")
    if not health:
        return [{"label": "unreachable", "level": "warn"}], []
    level = "ok" if health.get("ok") else "warn"
    label = "healthy" if health.get("ok") else "unhealthy"
    lines = [
        f"v{health.get('version', '?')} · {health.get('active', 0)} active browser(s)",
    ]
    return [{"label": label, "level": level}], lines


def _ollama_summary() -> tuple[list[dict[str, str]], list[str]]:
    ps = _fetch_json("http://127.0.0.1:11434/api/ps")
    tags = _fetch_json("http://127.0.0.1:11434/api/tags")
    if ps is None and tags is None:
        return [{"label": "unreachable", "level": "warn"}], []

    loaded = (ps or {}).get("models") or []
    installed = (tags or {}).get("models") or []
    if loaded:
        badge = {"label": "running", "level": "ok"}
        names = ", ".join(str(m.get("name", "?")) for m in loaded)
        detail = f"Loaded: {names}"
    else:
        badge = {"label": "idle", "level": "no_action"}
        detail = f"{len(installed)} model(s) installed · none loaded in memory"
    return [badge], [detail]


def _azerothcore_summary(config: AzerothCoreConfig) -> tuple[list[dict[str, str]], list[str]]:
    from src.azerothcore import get_azerothcore_status

    status = get_azerothcore_status(config)
    if not status:
        return [{"label": "unknown", "level": "warn"}], []

    if status["ready"]:
        badge = {"label": "online", "level": "ok"}
    elif status["overall"] == "amber":
        badge = {"label": "loading", "level": "amber"}
    else:
        badge = {"label": "offline", "level": "warn"}

    lines = [status["summary"]]
    for comp in status["components"][:3]:
        lines.append(f"{comp['label']}: {comp['state']} · {comp['detail']}")
    return [badge], lines


def get_service_logs(unit: str, settings: Settings, *, lines: int = 40) -> dict[str, Any]:
    badges: list[dict[str, str]] = []
    summary_lines: list[str] = []
    entries: list[dict[str, str]] = []
    error: str | None = None

    if unit == "good-search-mcp.service":
        badges, summary_lines = _good_search_summary()
        entries, error = _journal_entries(unit, lines=lines)
    elif unit == "ollama.service":
        badges, summary_lines = _ollama_summary()
        entries, error = _journal_entries(unit, lines=lines)
    elif unit == settings.azerothcore.systemd_unit:
        badges, summary_lines = _azerothcore_summary(settings.azerothcore)
        journal, error = _journal_entries(unit, lines=lines)
        entries.extend(_tmux_entries(settings.azerothcore.auth_tmux_session, prefix="auth"))
        entries.extend(_tmux_entries(settings.azerothcore.world_tmux_session, prefix="world"))
        entries.extend(journal)
    elif unit == "mini-pc-monitor.service":
        badges, summary_lines = _systemd_summary(unit)
        entries, error = _journal_entries(unit, lines=lines)
    else:
        badges, summary_lines = _systemd_summary(unit)
        entries, error = _journal_entries(unit, lines=lines)

    return {
        "unit": unit,
        "badges": badges,
        "summary_lines": summary_lines,
        "entries": entries,
        "error": error,
    }
