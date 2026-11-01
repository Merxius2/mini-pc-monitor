import json
import unittest
from unittest.mock import patch

from src.samba import add_samba_user, list_samba_users, set_samba_user_access
from src.config_loader import SambaConfig


class SambaUserListTests(unittest.TestCase):
    def test_list_json_parsed(self) -> None:
        config = SambaConfig()
        payload = [
            {"username": "alice", "access": "write"},
            {"username": "bob", "access": "read"},
        ]

        def fake_admin(*args: str):
            class Result:
                returncode = 0
                stdout = json.dumps(payload)
                stderr = ""

            return Result()

        with patch("src.samba._admin", fake_admin):
            users, err = list_samba_users(config)

        self.assertIsNone(err)
        self.assertEqual(len(users), 2)
        self.assertEqual(users[1]["access_label"], "Read-only")


class SambaAccessTests(unittest.TestCase):
    def test_set_access_invokes_helper(self) -> None:
        config = SambaConfig()
        seen: list[list[str]] = []

        def fake_admin(_config, *args: str):
            seen.append(list(args))

            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return Result()

        with patch("src.samba._admin", fake_admin):
            ok, msg = set_samba_user_access(config, "alice", "read")

        self.assertTrue(ok)
        self.assertEqual(seen[0], ["set-access", "alice", "read"])
        self.assertIn("read-only", msg.lower())

    def test_add_user_passes_access(self) -> None:
        config = SambaConfig()
        seen: list[list[str]] = []

        def fake_admin(_config, *args: str):
            seen.append(list(args))

            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return Result()

        with patch("src.samba._admin", fake_admin):
            ok, _ = add_samba_user(config, "guest1", "longpassword", access="read")

        self.assertTrue(ok)
        self.assertEqual(seen[0], ["add", "guest1", "longpassword", "read"])


if __name__ == "__main__":
    unittest.main()
