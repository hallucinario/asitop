import contextlib
import io
import signal
import unittest
from unittest import mock

from asitop import asitop as cli


def synthetic_sample(timestamp=1):
    return {
        "timestamp": timestamp,
        "thermal_pressure": "Nominal",
        "processor": {
            "clusters": [
                {
                    "name": "E-Cluster",
                    "freq_hz": 1_000_000_000,
                    "idle_ratio": 0.5,
                    "cpus": [
                        {"cpu": 0, "freq_hz": 1_000_000_000, "idle_ratio": 0.5}
                    ],
                },
                {
                    "name": "P-Cluster",
                    "freq_hz": 2_000_000_000,
                    "idle_ratio": 0.25,
                    "cpus": [
                        {"cpu": 0, "freq_hz": 2_000_000_000, "idle_ratio": 0.25}
                    ],
                },
            ],
            "ane_energy": 1000,
            "cpu_energy": 5000,
            "gpu_energy": 3000,
            "combined_power": 9000,
        },
        "gpu": {"freq_hz": 1200, "idle_ratio": 0.5},
    }


def synthetic_soc_info():
    return {
        "name": "Apple M2",
        "core_count": 2,
        "e_core_count": 1,
        "p_core_count": 1,
        "gpu_core_count": 1,
        "cpu_max_power": 20,
        "gpu_max_power": 20,
        "cpu_max_bw": 70,
        "gpu_max_bw": 70,
    }


def synthetic_ram_metrics():
    return {
        "total_GB": 16.0,
        "free_GB": 8.0,
        "used_GB": 8.0,
        "free_percent": 50,
        "swap_total_GB": 0.0,
        "swap_used_GB": 0.0,
        "swap_free_GB": 0.0,
        "swap_free_percent": None,
    }


class SyntheticCollector:
    def __init__(self, *args, **kwargs):
        self.entered = False
        self.closed = False
        self._sample_count = 0

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.closed = True
        return False

    def next_sample(self, timeout=None):
        if self._sample_count < 2:
            self._sample_count += 1
            return synthetic_sample(self._sample_count)
        raise KeyboardInterrupt


class TerminatingCollector(SyntheticCollector):
    def next_sample(self, timeout=None):
        signal.raise_signal(signal.SIGTERM)


class CLICollectorLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.patches = [
            mock.patch.object(cli, "get_soc_info", return_value=synthetic_soc_info()),
            mock.patch.object(
                cli, "get_ram_metrics_dict", return_value=synthetic_ram_metrics()
            ),
            mock.patch.object(cli, "clear_console"),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_main_renders_one_synthetic_sample_and_restores_cursor(self):
        collector = SyntheticCollector()
        output = io.StringIO()

        with (
            mock.patch.object(cli, "PowermetricsCollector", return_value=collector),
            contextlib.redirect_stdout(output),
            mock.patch.dict("os.environ", {"COLUMNS": "120", "LINES": "40"}),
        ):
            status = cli.main(["--interval", "1", "--avg", "2", "--color", "0"])

        self.assertEqual(status, 0)
        self.assertTrue(collector.entered)
        self.assertTrue(collector.closed)
        self.assertIn("\033[?25h", output.getvalue())
        self.assertIn("CPU+GPU+ANE Power", output.getvalue())

    def test_max_count_option_is_removed(self):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            with self.assertRaises(SystemExit) as raised:
                cli.main(["--max_count", "1"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("unrecognized arguments", errors.getvalue())

    def test_sigterm_returns_status_and_closes_collector(self):
        collector = TerminatingCollector()
        output = io.StringIO()
        original_handler = signal.getsignal(signal.SIGTERM)

        with (
            mock.patch.object(cli, "PowermetricsCollector", return_value=collector),
            contextlib.redirect_stdout(output),
        ):
            status = cli.main(["--interval", "1", "--avg", "2"])

        self.assertEqual(status, 128 + signal.SIGTERM)
        self.assertTrue(collector.closed)
        self.assertIs(signal.getsignal(signal.SIGTERM), original_handler)
        self.assertIn("\033[?25h", output.getvalue())


if __name__ == "__main__":
    unittest.main()
