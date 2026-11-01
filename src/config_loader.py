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
    "orange": {
        "fg": "#fb923c",
        "bg": "rgba(251, 146, 60, 0.18)",
        "border": "rgba(251, 146, 60, 0.45)",
    },
    "teal": {
        "fg": "#2dd4bf",
        "bg": "rgba(45, 212, 191, 0.18)",
        "border": "rgba(45, 212, 191, 0.45)",
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
    cmdline_patterns: list[str] = field(default_factory=list)
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
class HomeAssistantConfig:
    enabled: bool = True
    systemd_unit: str = "homeassistant.service"
    container_name: str = "homeassistant"
    health_url: str = "http://127.0.0.1:8123/"
    dashboard_url: str = "http://192.168.1.30:8123/"
    rflink_device: str = "/dev/serial/by-id/usb-1a86_USB2.0-Serial-if00-port0"


@dataclass
class DomoticzConfig:
    enabled: bool = True
    systemd_unit: str = "domoticz.service"
    container_name: str = "domoticz"
    health_url: str = "http://127.0.0.1:8082/"
    dashboard_url: str = "http://192.168.1.30:8082/"
    rflink_device: str = "/dev/serial/by-id/usb-1a86_USB2.0-Serial-if00-port0"


@dataclass
class StorageConfig:
    enabled: bool = True
    mount: str = "/mnt/storage"
    md_device: str = "/dev/md0"
    array_uuid: str = "df02ddd3:9732589a:79125c92:7f363879"


@dataclass
class SambaConfig:
    enabled: bool = True
    systemd_unit: str = "smbd.service"
    share_name: str = "storage"
    share_path: str = "/mnt/storage/shared"
    unc_path: str = "//192.168.1.30/storage"
    admin_script: str = "/usr/local/sbin/minipc-samba-admin"


@dataclass
class TransmissionConfig:
    enabled: bool = True
    systemd_unit: str = "transmission-daemon.service"
    rpc_url: str = "http://127.0.0.1:9091/transmission/rpc"
    rpc_username: str = "transmission"
    rpc_password: str = ""
    rpc_password_file: str = "/etc/mini-pc-monitor/transmission-rpc-password"
    download_dir: str = "/mnt/storage/shared/Downloads"
    incomplete_dir: str = "/mnt/storage/downloads/incomplete"
    watch_dir: str = "/mnt/storage/torrents/watch"


@dataclass
class SystemUpdatesConfig:
    enabled: bool = True
    helper_script: str = "/usr/local/sbin/minipc-system-update"
    max_packages_shown: int = 12


@dataclass
class VideoDownloadConfig:
    enabled: bool = True
    download_dir: str = "/mnt/storage/shared/Downloads/youtube downloader/videos"
    video_dir: str = ""
    music_dir: str = ""
    allowed_hosts: list[str] = field(
        default_factory=lambda: [
            "youporn.com",
            "www.youporn.com",
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "music.youtube.com",
            "youtu.be",
        ]
    )
    yt_dlp_command: str = ""
    download_timeout_seconds: int = 3600
    delete_after_push_seconds: int = 600

    def __post_init__(self) -> None:
        if not (self.video_dir or "").strip():
            object.__setattr__(self, "video_dir", self.download_dir)
        if not (self.music_dir or "").strip():
            object.__setattr__(
                self,
                "music_dir",
                str(Path(self.video_dir).parent / "music"),
            )


def _default_clamav_schedule_days() -> list[str]:
    return ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@dataclass
class ClamAvScheduleConfig:
    manage: bool = True
    time: str = "03:30"
    scope: str = "shared"
    days: list[str] = field(default_factory=_default_clamav_schedule_days)
    timer_unit: str = "minipc-clamscan-full.timer"
    service_unit: str = "minipc-clamscan-full.service"


@dataclass
class ClamAvConfig:
    enabled: bool = True
    daemon_unit: str = "clamav-daemon.service"
    freshclam_unit: str = "clamav-freshclam.service"
    scan_log: str = "/mnt/storage/logs/clamav-scan.log"
    scan_progress_file: str = "/mnt/storage/logs/clamav-scan.progress.json"
    scan_history_file: str = "/mnt/storage/logs/clamav-scan-history.jsonl"
    max_history_shown: int = 15
    helper_script: str = "/usr/local/sbin/minipc-clamscan-admin"
    schedule: ClamAvScheduleConfig = field(default_factory=ClamAvScheduleConfig)


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
    homeassistant: HomeAssistantConfig = field(default_factory=HomeAssistantConfig)
    domoticz: DomoticzConfig = field(default_factory=DomoticzConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    samba: SambaConfig = field(default_factory=SambaConfig)
    transmission: TransmissionConfig = field(default_factory=TransmissionConfig)
    clamav: ClamAvConfig = field(default_factory=ClamAvConfig)
    system_updates: SystemUpdatesConfig = field(default_factory=SystemUpdatesConfig)
    video_download: VideoDownloadConfig = field(default_factory=VideoDownloadConfig)


def load_settings(path: Path | None = None) -> Settings:
    with (path or CONFIG_DIR / "settings.yaml").open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    services = [ServiceConfig(**s) for s in data.get("services", [])]
    sleep_schedule = SleepScheduleConfig(**data.get("sleep_schedule", {}))
    azerothcore = AzerothCoreConfig(**data.get("azerothcore", {}))
    pricewatch = PricewatchConfig(**data.get("pricewatch", {}))
    homeassistant = HomeAssistantConfig(**data.get("homeassistant", {}))
    domoticz = DomoticzConfig(**data.get("domoticz", {}))
    storage = StorageConfig(**data.get("storage", {}))
    samba = SambaConfig(**data.get("samba", {}))
    transmission = TransmissionConfig(**data.get("transmission", {}))
    clam_raw = data.get("clamav", {}) or {}
    schedule_raw = clam_raw.get("schedule") or {}
    clamav = ClamAvConfig(
        **{k: v for k, v in clam_raw.items() if k != "schedule"},
        schedule=ClamAvScheduleConfig(**schedule_raw),
    )
    system_updates = SystemUpdatesConfig(**data.get("system_updates", {}))
    video_download = VideoDownloadConfig(**data.get("video_download", {}))
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
        homeassistant=homeassistant,
        domoticz=domoticz,
        storage=storage,
        samba=samba,
        transmission=transmission,
        clamav=clamav,
        system_updates=system_updates,
        video_download=video_download,
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
    cmdline: str | None = None,
) -> dict[str, str] | None:
    lower = name.lower()
    cmdline_lower = (cmdline or "").lower()
    for rule in rules:
        if rule.users and (not username or username not in rule.users):
            continue
        name_hit = bool(rule.patterns) and any(
            pattern.lower() in lower for pattern in rule.patterns
        )
        cmd_hit = bool(rule.cmdline_patterns) and bool(cmdline_lower) and any(
            pattern.lower() in cmdline_lower for pattern in rule.cmdline_patterns
        )
        if name_hit or cmd_hit:
            return {
                "label": rule.label,
                "color": rule.color,
                "style": process_service_style(rule.color),
            }
    return None
