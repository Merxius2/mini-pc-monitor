import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.clamav import list_scan_history
from src.clamav_schedule import (
    apply_clamav_schedule,
    format_days_label,
    get_clamav_schedule_status,
    parse_timer_dropin,
    timer_dropin_content,
)
from src.config_loader import ClamAvConfig, ClamAvScheduleConfig


class ClamAvScheduleTests(unittest.TestCase):
    def test_apply_rejects_bad_time(self) -> None:
        config = ClamAvConfig()
        ok, msg = apply_clamav_schedule(
            config, time_str="25:99", scope="shared", days=["mon"]
        )
        self.assertFalse(ok)
        self.assertIn("24-hour", msg)

    def test_apply_requires_days(self) -> None:
        config = ClamAvConfig()
        ok, msg = apply_clamav_schedule(config, time_str="03:30", scope="shared", days=[])
        self.assertFalse(ok)
        self.assertIn("at least one day", msg.lower())

    def test_timer_dropin_weekdays(self) -> None:
        content = timer_dropin_content("04:00", ["mon", "wed", "fri"])
        self.assertIn("OnCalendar=Mon *-*-* 04:00:00", content)
        self.assertIn("OnCalendar=Wed *-*-* 04:00:00", content)
        self.assertNotIn("Tue", content)

    def test_timer_dropin_every_day(self) -> None:
        content = timer_dropin_content("03:30", ["mon", "tue", "wed", "thu", "fri", "sat", "sun"])
        self.assertIn("OnCalendar=*-*-* 03:30:00", content)

    def test_parse_timer_dropin(self) -> None:
        text = (
            "[Timer]\n"
            "OnCalendar=\n"
            "OnCalendar=Mon *-*-* 04:15:00\n"
            "OnCalendar=Fri *-*-* 04:15:00\n"
        )
        time_str, days = parse_timer_dropin(text)
        self.assertEqual(time_str, "04:15")
        self.assertEqual(days, ["mon", "fri"])

    def test_format_days_label(self) -> None:
        self.assertEqual(format_days_label(["mon", "tue", "wed", "thu", "fri", "sat", "sun"]), "Every day")
        self.assertEqual(format_days_label(["sat", "sun"]), "Sat, Sun")

    def test_status_reads_drop_in(self) -> None:
        config = ClamAvConfig(
            schedule=ClamAvScheduleConfig(
                timer_unit="minipc-clamscan-full.timer",
                service_unit="minipc-clamscan-full.service",
            )
        )
        with patch("src.clamav_schedule._timer_props") as props:
            props.return_value = {
                "UnitFileState": "enabled",
                "NextElapseUSecRealtime": "Mon 2026-11-02 03:30:00 CET",
            }
            with patch("src.clamav_schedule._read_timer_drop_in") as drop_in:
                drop_in.return_value = ("04:15", ["mon", "wed"])
                with patch("src.clamav_schedule._read_service_scope") as scope:
                    scope.return_value = "downloads"
                    status = get_clamav_schedule_status(config)
        self.assertTrue(status["enabled"])
        self.assertEqual(status["time"], "04:15")
        self.assertEqual(status["scope"], "downloads")
        self.assertEqual(status["days"], ["mon", "wed"])


class ClamAvHistoryTests(unittest.TestCase):
    def test_list_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            rows = [
                {"finished_at": "2026-11-01T10:00:00+00:00", "scope": "shared", "state": "done", "trigger": "manual"},
                {"finished_at": "2026-11-02T10:00:00+00:00", "scope": "downloads", "state": "done", "trigger": "scheduled"},
            ]
            path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
            config = ClamAvConfig(scan_history_file=str(path), max_history_shown=10)
            history = list_scan_history(config)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["trigger"], "scheduled")
        self.assertEqual(history[1]["scope_label"], "Shared folder")


if __name__ == "__main__":
    unittest.main()
