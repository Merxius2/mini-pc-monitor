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


@dataclass
class SleepScheduleConfig:
    nightly_off_timer: str = "minipc-nightly-off.timer"
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
    sleep_schedule: SleepScheduleConfig = field(default_factory=SleepScheduleConfig)
    azerothcore: AzerothCoreConfig = field(default_factory=AzerothCoreConfig)


def load_settings(path: Path | None = None) -> Settings:
    with (path or CONFIG_DIR / "settings.yaml").open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    services = [ServiceConfig(**s) for s in data.get("services", [])]
    sleep_schedule = SleepScheduleConfig(**data.get("sleep_schedule", {}))
    azerothcore = AzerothCoreConfig(**data.get("azerothcore", {}))
    return Settings(
        server=ServerConfig(**data.get("server", {})),
        hostname_label=data.get("hostname_label"),
        services=services,
        top_processes_limit=int(data.get("top_processes_limit", 8)),
        sleep_schedule=sleep_schedule,
        azerothcore=azerothcore,
    )


def allowed_service_units(settings: Settings) -> set[str]:
    return {s.unit for s in settings.services}


def manageable_service_units(settings: Settings) -> set[str]:
    return {s.unit for s in settings.services if s.manage}


def loggable_service_units(settings: Settings) -> set[str]:
    return {s.unit for s in settings.services if s.logs}
