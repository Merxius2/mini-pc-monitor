import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config_loader import SleepScheduleConfig
from src.sleep_schedule import (
    _next_occurrence,
    _nightly_off_service,
    _parse_calendar,
    _phase,
    _read_wake_time,
    validate_time,
)


class SleepScheduleTests(unittest.TestCase):
    def test_validate_time(self) -> None:
        self.assertTrue(validate_time("09:00"))
        self.assertTrue(validate_time("21:00"))
        self.assertFalse(validate_time("9:00"))
        self.assertFalse(validate_time("25:00"))

    def test_parse_calendar(self) -> None:
        self.assertEqual(
            _parse_calendar("{ OnCalendar=*-*-* 21:00:00 ; next_elapse=... }"),
            "21:00",
        )

    def test_next_occurrence_tomorrow(self) -> None:
        now = datetime(2026, 9, 22, 19, 30, tzinfo=ZoneInfo("Europe/Amsterdam"))
        nxt = _next_occurrence("21:00", now=now)
        self.assertEqual(nxt.hour, 21)
        self.assertEqual(nxt.day, 22)

    def test_phase_daytime_when_keep_awake_active(self) -> None:
        self.assertEqual(
            _phase(
                enabled=True,
                keep_awake_active=True,
                sleep_time="21:00",
                wake_time="09:00",
            ),
            "daytime",
        )

    def test_nightly_off_service_name(self) -> None:
        config = SleepScheduleConfig(nightly_off_timer="minipc-nightly-off.timer")
        self.assertEqual(_nightly_off_service(config), "minipc-nightly-off.service")

    def test_read_wake_time_after_shebang(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as handle:
            handle.write('#!/bin/bash\nset -euo pipefail\nWAKE="09:00"\n')
            path = Path(handle.name)
        try:
            self.assertEqual(_read_wake_time(path), "09:00")
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
