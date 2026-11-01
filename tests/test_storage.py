import unittest

from src.storage import (
    _human_bytes,
    _is_read_only_mount,
    _parse_mdadm_disks,
    _parse_mdstat,
    get_raid_status,
)


class HumanBytesTests(unittest.TestCase):
    def test_formats_hundreds_of_gb(self) -> None:
        # ~880 GiB filesystem
        self.assertEqual(_human_bytes(943_837_974_528), "879.0 GB")

    def test_formats_small_usage(self) -> None:
        self.assertEqual(_human_bytes(2_200_000), "2.1 MB")


class MountOptionsTests(unittest.TestCase):
    def test_emergency_ro_is_read_only(self) -> None:
        self.assertTrue(_is_read_only_mount("rw,noatime,emergency_ro"))

    def test_rw_is_not_read_only(self) -> None:
        self.assertFalse(_is_read_only_mount("rw,noatime"))


class ParseMdadmDisksTests(unittest.TestCase):
    def test_parses_active_sync_disks(self) -> None:
        detail = """
    Number   Major   Minor   RaidDevice State
       0       8       48        0      active sync   /dev/sdd
       1       8       64        1      active sync   /dev/sde
"""
        disks = _parse_mdadm_disks(detail)
        self.assertEqual(len(disks), 2)
        self.assertEqual(disks[0]["device"], "/dev/sdd")
        self.assertEqual(disks[0]["level"], "ok")
        self.assertEqual(disks[0]["dot"], "bull")


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
