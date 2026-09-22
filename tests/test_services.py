import unittest

from src.services import _batch_service_states


class BatchServiceStatesTests(unittest.TestCase):
    def test_parses_systemctl_show_blocks(self) -> None:
        output = """ActiveState=active
UnitFileState=enabled

ActiveState=inactive
UnitFileState=disabled"""
        units = ["alpha.service", "beta.service"]
        original_run = __import__("src.services", fromlist=["services"])._run

        def fake_run(cmd: list[str]):
            class Result:
                stdout = output
                stderr = ""
                returncode = 0

            return Result()

        import src.services as services_mod

        services_mod._run = fake_run  # type: ignore[method-assign]
        try:
            states = _batch_service_states(units)
        finally:
            services_mod._run = original_run  # type: ignore[method-assign]

        self.assertEqual(states["alpha.service"]["active"], "active")
        self.assertEqual(states["alpha.service"]["enabled"], "enabled")
        self.assertEqual(states["beta.service"]["active"], "inactive")


if __name__ == "__main__":
    unittest.main()
