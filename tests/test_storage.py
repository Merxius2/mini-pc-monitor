import unittest

from src.storage import _parse_mdstat, get_raid_status


class ParseMdstatTests(unittest.TestCase):
    def test_parses_active_raid1(self) -> None:
        text = """Personalities : [raid1]
md0 : active raid1 sda[0] sdb[1]
      937560384 blocks super 1.2 [2/2] [UU]
"""
        parsed = _parse_mdstat(text)
        self.assertEqual(len(parsed["arrays"]), 1)
        arr = parsed["arrays"][0]
        self.assertEqual(arr["device"], "/dev/md0")
        self.assertEqual(arr["level"], "raid1")
        self.assertEqual(arr["sync"], "UU")
        self.assertEqual(arr["members"], ["sda", "sdb"])


class RaidStatusTests(unittest.TestCase):
    def test_mount_usage_when_not_mounted(self) -> None:
        from unittest.mock import patch

        with patch("src.storage.Path.is_mount", return_value=False), patch(
            "src.storage._run",
            return_value=type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})(),
        ):
            status = get_raid_status(mount="/mnt/storage")
        self.assertFalse(status["mount"]["mounted"])
        self.assertEqual(status["overall"], "warn")


if __name__ == "__main__":
    unittest.main()
