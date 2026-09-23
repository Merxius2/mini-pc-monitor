import unittest

from src.metrics import get_host_metrics, normalize_process_cpu, sparkline_points


class HostMetricsTests(unittest.TestCase):
    def test_returns_expected_keys(self) -> None:
        metrics = get_host_metrics(sample_cpu=False)
        self.assertIn("cpu_percent", metrics)
        self.assertIn("memory_used_gb", metrics)
        self.assertIn("uptime_seconds", metrics)
        self.assertGreater(metrics["memory_total_gb"], 0)

    def test_sparkline_points(self) -> None:
        pts = sparkline_points([10.0, 20.0, 15.0, 30.0])
        self.assertIn(",", pts)
        self.assertEqual("", sparkline_points([1.0]))

    def test_normalize_process_cpu(self) -> None:
        self.assertEqual(normalize_process_cpu(40.0, cores=4), 10.0)
        self.assertEqual(normalize_process_cpu(100.0, cores=1), 100.0)


if __name__ == "__main__":
    unittest.main()
