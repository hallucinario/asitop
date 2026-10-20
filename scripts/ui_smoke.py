import contextlib
import io
from unittest import mock

from asitop import asitop as cli


def sample(timestamp):
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


class SyntheticCollector:
    def __init__(self, *args, **kwargs):
        self.samples = [sample(1), sample(2)]
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.closed = True
        return False

    def next_sample(self, timeout=None):
        if self.samples:
            return self.samples.pop(0)
        raise KeyboardInterrupt


def main():
    collector = SyntheticCollector()
    soc_info = {
        "name": "Apple M2 (synthetic)",
        "core_count": 2,
        "e_core_count": 1,
        "p_core_count": 1,
        "gpu_core_count": 1,
        "cpu_max_power": 20,
        "gpu_max_power": 20,
        "cpu_max_bw": 70,
        "gpu_max_bw": 70,
    }
    ram_metrics = {
        "total_GB": 16.0,
        "free_GB": 8.0,
        "used_GB": 8.0,
        "free_percent": 50,
        "swap_total_GB": 0.0,
        "swap_used_GB": 0.0,
        "swap_free_GB": 0.0,
        "swap_free_percent": None,
    }
    output = io.StringIO()

    with (
        mock.patch.object(cli, "PowermetricsCollector", return_value=collector),
        mock.patch.object(cli, "get_soc_info", return_value=soc_info),
        mock.patch.object(cli, "get_ram_metrics_dict", return_value=ram_metrics),
        mock.patch.object(cli, "clear_console"),
        contextlib.redirect_stdout(output),
    ):
        status = cli.main(["--interval", "1", "--avg", "2", "--color", "0"])

    rendered = output.getvalue()
    if status != 0 or not collector.closed:
        raise SystemExit("synthetic UI smoke failed: CLI status or cleanup was incorrect")
    if "CPU+GPU+ANE Power" not in rendered:
        raise SystemExit("synthetic UI smoke failed: the terminal UI did not render")

    print(
        "Synthetic UI smoke passed: main() rendered generated samples; "
        "powermetrics and sudo were not executed."
    )


if __name__ == "__main__":
    main()
