"""Host CPU and memory metrics for the dashboard."""

from __future__ import annotations

import time
from collections import deque
from typing import Any

import psutil

from src.config_loader import ProcessLabelRule, service_match_for_process

_HISTORY: deque[dict[str, float]] = deque(maxlen=24)


def _load_1m() -> float | None:
    try:
        return float(psutil.getloadavg()[0])
    except (AttributeError, OSError):
        return None


def _ollama_rss_bytes() -> int | None:
    total = 0
    found = False
    for proc in psutil.process_iter(["name", "memory_info"]):
        name = (proc.info.get("name") or "").lower()
        if "ollama" not in name and "llama-server" not in name:
            continue
        mem = proc.info.get("memory_info")
        if mem is not None:
            total += mem.rss
            found = True
    return total if found else None


def sparkline_points(values: list[float], width: int = 200, height: int = 28) -> str:
    if len(values) < 2:
        return ""
    lo = min(values)
    hi = max(values)
    span = hi - lo or 1.0
    step = width / (len(values) - 1)
    pts: list[str] = []
    for i, value in enumerate(values):
        x = round(i * step, 1)
        y = round(height - 2 - ((value - lo) / span) * (height - 4), 1)
        pts.append(f"{x},{y}")
    return " ".join(pts)


def get_host_metrics(*, sample_cpu: bool = True, include_ollama: bool = True) -> dict[str, Any]:
    mem = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.1 if sample_cpu else None)
    load = _load_1m()
    ollama_rss = _ollama_rss_bytes() if include_ollama else None

    cpu_level = "ok"
    if cpu >= 85 or (load is not None and load >= psutil.cpu_count() * 0.9):
        cpu_level = "warn"
    elif cpu >= 60 or (load is not None and load >= psutil.cpu_count() * 0.6):
        cpu_level = "amber"

    mem_level = "ok"
    if mem.percent >= 90:
        mem_level = "warn"
    elif mem.percent >= 75:
        mem_level = "amber"

    cores = psutil.cpu_count() or 1
    load_pct = None
    if load is not None:
        load_pct = round(min(100.0, (load / cores) * 100), 1)

    cpu_pct = round(cpu, 1)
    mem_pct = round(mem.percent, 1)
    _HISTORY.append({"cpu": cpu_pct, "mem": mem_pct})
    cpu_hist = [p["cpu"] for p in _HISTORY]
    mem_hist = [p["mem"] for p in _HISTORY]

    uptime_sec = time.time() - psutil.boot_time()

    return {
        "cpu_percent": cpu_pct,
        "load_1m": round(load, 2) if load is not None else None,
        "load_percent": load_pct,
        "cpu_cores": cores,
        "cpu_level": cpu_level,
        "memory_used_gb": round(mem.used / (1024**3), 1),
        "memory_total_gb": round(mem.total / (1024**3), 1),
        "memory_percent": mem_pct,
        "memory_level": mem_level,
        "ollama_memory_gb": round(ollama_rss / (1024**3), 2) if ollama_rss else None,
        "cpu_sparkline": sparkline_points(cpu_hist),
        "mem_sparkline": sparkline_points(mem_hist),
        "history_len": len(cpu_hist),
        "uptime_seconds": int(uptime_sec),
    }


def normalize_process_cpu(raw_cpu: float, *, cores: int | None = None) -> float:
    """Convert psutil per-core process CPU to system-wide % (0-100 scale)."""
    cpu_cores = cores or psutil.cpu_count() or 1
    return round(raw_cpu / cpu_cores, 1)


def get_top_processes(
    limit: int = 8,
    *,
    process_labels: list[ProcessLabelRule] | None = None,
) -> dict[str, Any]:
    cores = psutil.cpu_count() or 1
    psutil.cpu_percent(interval=0.1)
    rules = process_labels or []
    rows: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name", "username"]):
        try:
            cpu = proc.cpu_percent(interval=0.0)
            mem = proc.memory_percent()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        name = proc.info.get("name") or "?"
        match = service_match_for_process(name, rules)
        rows.append(
            {
                "pid": proc.pid,
                "name": name,
                "user": proc.info.get("username") or "?",
                "cpu_percent": normalize_process_cpu(cpu, cores=cores),
                "memory_percent": round(mem, 1),
                "service_label": match["label"] if match else None,
                "service_color": match["color"] if match else None,
                "service_label_style": match["style"] if match else None,
            }
        )
    rows.sort(key=lambda r: (r["cpu_percent"], r["memory_percent"]), reverse=True)
    top = rows[:limit]
    return {
        "processes": top,
        "cpu_cores": cores,
        "top_cpu_sum": round(sum(row["cpu_percent"] for row in top), 1),
    }
