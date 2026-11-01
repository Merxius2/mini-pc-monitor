import json
import unittest
from unittest.mock import patch

from src.clamav import _format_scan_message, start_clamav_scan
from src.config_loader import ClamAvConfig


class ClamAvScanMessageTests(unittest.TestCase):
    def test_clean(self) -> None:
        msg = _format_scan_message(
            {"scope": "downloads", "infected": 0, "detail": "clean", "target": "/mnt/storage/shared/Downloads"}
        )
        self.assertIn("clean", msg)

    def test_infected(self) -> None:
        msg = _format_scan_message({"scope": "shared", "infected": 2, "target": "/mnt/storage/shared"})
        self.assertIn("2 infected", msg)


class RunClamAvScanTests(unittest.TestCase):
    def test_invokes_helper(self) -> None:
        config = ClamAvConfig()

        def fake_run(cmd: list[str]):
            class Result:
                returncode = 0
                stdout = json.dumps(
                    {
                        "ok": True,
                        "scope": "downloads",
                        "target": "/mnt/storage/shared/Downloads",
                        "infected": 0,
                        "detail": "Scan started — watch progress on the dashboard",
                    }
                )
                stderr = ""

            return Result()

        with patch("src.clamav._run", fake_run):
            ok, msg = start_clamav_scan(config, "downloads")

        self.assertTrue(ok)
        self.assertIn("started", msg.lower())


if __name__ == "__main__":
    unittest.main()
