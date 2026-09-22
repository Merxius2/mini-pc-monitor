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


@dataclass
class Settings:
    server: ServerConfig = field(default_factory=ServerConfig)
    hostname_label: str | None = None
    services: list[ServiceConfig] = field(default_factory=list)
    top_processes_limit: int = 8


def load_settings(path: Path | None = None) -> Settings:
    with (path or CONFIG_DIR / "settings.yaml").open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    services = [ServiceConfig(**s) for s in data.get("services", [])]
    return Settings(
        server=ServerConfig(**data.get("server", {})),
        hostname_label=data.get("hostname_label"),
        services=services,
        top_processes_limit=int(data.get("top_processes_limit", 8)),
    )


def allowed_service_units(settings: Settings) -> set[str]:
    return {s.unit for s in settings.services}


def manageable_service_units(settings: Settings) -> set[str]:
    return {s.unit for s in settings.services if s.manage}
