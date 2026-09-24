"""Load YAML configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8080


@dataclass
class ServiceConfig:
    unit: str
    label: str
    manage: bool = False
    logs: bool = False
    dashboard_url: str | None = None


@dataclass
class AzerothCoreConfig:
    enabled: bool = True
    label: str = "AzerothCore WoW Server"
    systemd_unit: str = "azerothcore.service"
    manage: bool = True
    mysql_unit: str = "mysql.service"
    mysql_port: int = 3306
    auth_process: str = "authserver"
    auth_port: int = 3724
    world_process: str = "worldserver"
    world_port: int = 8085
    auth_tmux_session: str = "auth-session"
    world_tmux_session: str = "world-session"


PROCESS_SERVICE_COLORS: dict[str, dict[str, str]] = {
    "cyan": {
        "fg": "#22d3ee",
        "bg": "rgba(34, 211, 238, 0.18)",
        "border": "rgba(34, 211, 238, 0.45)",
    },
    "amber": {
        "fg": "#f59e0b",
        "bg": "rgba(245, 158, 11, 0.18)",
        "border": "rgba(245, 158, 11, 0.45)",
    },
    "green": {
        "fg": "#22c55e",
        "bg": "rgba(34, 197, 94, 0.18)",
        "border": "rgba(34, 197, 94, 0.45)",
    },
    "purple": {
        "fg": "#a78bfa",
        "bg": "rgba(167, 139, 250, 0.18)",
        "border": "rgba(167, 139, 250, 0.45)",
    },
    "blue": {
        "fg": "#3b82f6",
        "bg": "rgba(59, 130, 246, 0.18)",
        "border": "rgba(59, 130, 246, 0.45)",
    },
    "red": {
        "fg": "#ef4444",
        "bg": "rgba(239, 68, 68, 0.18)",
        "border": "rgba(239, 68, 68, 0.45)",
    },
}


@dataclass
class ProcessLabelRule:
    label: str
    patterns: list[str] = field(default_factory=list)
    color: str = "cyan"
    users: list[str] = field(default_factory=list)


@dataclass
class PricewatchConfig:
    enabled: bool = True
    systemd_unit: str = "pricewatch.service"
    health_url: str = "http://127.0.0.1:8081/health"
    stats_url: str = "http://127.0.0.1:8081/api/stats"
    dashboard_url: str = "http://192.168.1.30:8081/"


@dataclass
class SleepScheduleConfig:
    nightly_off_timer: str = "minipc-nightly-off.timer"
    nightly_off_service: str = "minipc-nightly-off.service"
    keep_awake_timer: str = "minipc-keep-awake.timer"
    keep_awake_service: str = "minipc-keep-awake.service"
    suspend_script: str = "/usr/local/sbin/minipc-poweroff-until-morning.sh"
    manage: bool = True


@dataclass
class Settings:
    server: ServerConfig = field(default_factory=ServerConfig)
    hostname_label: str | None = None
    services: list[ServiceConfig] = field(default_factory=list)
    top_processes_limit: int = 8
    process_labels: list[ProcessLabelRule] = field(default_factory=list)
    sleep_schedule: SleepScheduleConfig = field(default_factory=SleepScheduleConfig)
    azerothcore: AzerothCoreConfig = field(default_factory=AzerothCoreConfig)
    pricewatch: PricewatchConfig = field(default_factory=PricewatchConfig)


def load_settings(path: Path | None = None) -> Settings:
    with (path or CONFIG_DIR / "settings.yaml").open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    services = [ServiceConfig(**s) for s in data.get("services", [])]
    sleep_schedule = SleepScheduleConfig(**data.get("sleep_schedule", {}))
    azerothcore = AzerothCoreConfig(**data.get("azerothcore", {}))
    pricewatch = PricewatchConfig(**data.get("pricewatch", {}))
    process_labels = [ProcessLabelRule(**r) for r in data.get("process_labels", [])]
    return Settings(
        server=ServerConfig(**data.get("server", {})),
        hostname_label=data.get("hostname_label"),
        services=services,
        top_processes_limit=int(data.get("top_processes_limit", 8)),
        process_labels=process_labels,
        sleep_schedule=sleep_schedule,
        azerothcore=azerothcore,
        pricewatch=pricewatch,
    )


def allowed_service_units(settings: Settings) -> set[str]:
    return {s.unit for s in settings.services}


def manageable_service_units(settings: Settings) -> set[str]:
    return {s.unit for s in settings.services if s.manage}


def loggable_service_units(settings: Settings) -> set[str]:
    return {s.unit for s in settings.services if s.logs}


def process_service_style(color: str) -> str:
    palette = PROCESS_SERVICE_COLORS.get(color, PROCESS_SERVICE_COLORS["cyan"])
    return (
        f"color: {palette['fg']}; "
        f"background-color: {palette['bg']}; "
        f"border: 1px solid {palette['border']};"
    )


def service_match_for_process(
    name: str,
    rules: list[ProcessLabelRule],
    *,
    username: str | None = None,
) -> dict[str, str] | None:
    lower = name.lower()
    for rule in rules:
        if rule.users and (not username or username not in rule.users):
            continue
        if any(pattern.lower() in lower for pattern in rule.patterns):
            return {
                "label": rule.label,
                "color": rule.color,
                "style": process_service_style(rule.color),
            }
    return None
