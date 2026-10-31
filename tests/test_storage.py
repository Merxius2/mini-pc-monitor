import unittest

from src.storage import _human_bytes, _parse_mdstat, get_raid_status


class HumanBytesTests(unittest.TestCase):
    def test_formats_hundreds_of_gb(self) -> None:
        # ~880 GiB filesystem
        self.assertEqual(_human_bytes(943_837_974_528), "879.0 GB")

    def test_formats_small_usage(self) -> None:
        self.assertEqual(_human_bytes(2_200_000), "2.1 MB")


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
