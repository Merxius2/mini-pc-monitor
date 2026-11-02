import unittest
from unittest.mock import patch

from src.config_loader import StorageConfig
from src.storage_repair import get_raid_status_with_repair, raid_needs_repair, repair_raid


class RaidNeedsRepairTests(unittest.TestCase):
    def test_degraded(self) -> None:
        self.assertTrue(raid_needs_repair({"degraded": True, "mount": {"mounted": True}}))

    def test_healthy_uu(self) -> None:
        self.assertFalse(
            raid_needs_repair(
                {
                    "degraded": False,
                    "read_only": False,
                    "mount": {"mounted": True},
                    "array": {"state": "active", "sync": "UU"},
                }
            )
        )


class RepairRaidTests(unittest.TestCase):
    def test_cooldown_skips(self) -> None:
        config = StorageConfig(repair_cooldown_seconds=3600)
        with patch("src.storage_repair.Path.is_file", return_value=True), patch(
            "src.storage_repair._cooldown_active", return_value=True
        ):
            ok, msg, skipped = repair_raid(config)
        self.assertFalse(ok)
        self.assertTrue(skipped)

    def test_runs_script(self) -> None:
        config = StorageConfig(auto_repair=True)

        def fake_run(cmd, **kwargs):
            class R:
                returncode = 0
                stdout = ""
                stderr = ""

            return R()

        with patch("src.storage_repair.Path.is_file", return_value=True), patch(
            "src.storage_repair._cooldown_active", return_value=False
        ), patch("src.storage_repair._mark_repair_run"), patch(
            "src.storage_repair.subprocess.run", side_effect=fake_run
        ) as mock_run:
            ok, _, skipped = repair_raid(config, force=True)
        self.assertTrue(ok)
        self.assertFalse(skipped)
        self.assertIn("ensure-storage", mock_run.call_args[0][0][2])


class GetRaidWithRepairTests(unittest.TestCase):
    def test_skips_when_healthy(self) -> None:
        config = StorageConfig()
        healthy = {
            "degraded": False,
            "read_only": False,
            "mount": {"mounted": True},
            "array": {"sync": "UU"},
        }
        with patch("src.storage_repair.get_raid_status", return_value=healthy):
            status = get_raid_status_with_repair(config)
        self.assertNotIn("repair", status)


if __name__ == "__main__":
    unittest.main()
