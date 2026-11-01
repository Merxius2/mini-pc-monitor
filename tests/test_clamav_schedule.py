import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.clamav import list_scan_history
from src.clamav_schedule import apply_clamav_schedule, get_clamav_schedule_status
from src.config_loader import ClamAvConfig, ClamAvScheduleConfig


class ClamAvScheduleTests(unittest.TestCase):
    def test_apply_rejects_bad_time(self) -> None:
        config = ClamAvConfig()
        ok, msg = apply_clamav_schedule(config, time_str="25:99", scope="shared")
        self.assertFalse(ok)
        self.assertIn("24-hour", msg)

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
            with patch("src.clamav_schedule._read_drop_in") as drop_in:
                drop_in.return_value = ("04:15", None)
                with patch("src.clamav_schedule._read_service_scope") as scope:
                    scope.return_value = "downloads"
                    status = get_clamav_schedule_status(config)
        self.assertTrue(status["enabled"])
        self.assertEqual(status["time"], "04:15")
        self.assertEqual(status["scope"], "downloads")


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
