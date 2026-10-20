import argparse
import sys
import time
from pathlib import Path

import psutil

from asitop.collector import PowermetricsCollector, PowermetricsError


def build_parser():
    parser = argparse.ArgumentParser(
        description="Measure asitop collector RSS using synthetic or native samples."
    )
    parser.add_argument(
        "--native",
        action="store_true",
        help="Run the real powermetrics producer; this invokes the configured sudo launcher.",
    )
    parser.add_argument("--duration", type=float, default=60, help="Total run time in seconds")
    parser.add_argument("--warmup", type=float, default=5, help="Warmup time in seconds")
    parser.add_argument(
        "--interval", type=float, default=1, help="Native sample interval in seconds"
    )
    parser.add_argument(
        "--max-growth-mib",
        type=float,
        default=16,
        help="Maximum allowed peak RSS growth after warmup.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.duration <= 0 or args.warmup < 0 or args.duration <= args.warmup:
        print("--duration must be greater than --warmup, and both must be valid", file=sys.stderr)
        return 2
    if args.interval <= 0 or args.max_growth_mib < 0:
        print("--interval must be positive and --max-growth-mib nonnegative", file=sys.stderr)
        return 2

    command = None
    mode = "native"
    if not args.native:
        mode = "synthetic"
        producer_path = Path(__file__).resolve().parents[1] / "tests" / "fake_producer.py"
        command = [sys.executable, str(producer_path), "continuous"]

    collector = PowermetricsCollector(
        interval_seconds=args.interval,
        command=command,
    )
    process_memory = psutil.Process()
    start = time.monotonic()
    warmup_rss = None
    peak_rss = None
    sample_count = 0

    try:
        with collector:
            collector.next_sample()
            sample_count += 1

            while True:
                elapsed = time.monotonic() - start
                current_rss = process_memory.memory_info().rss
                if elapsed >= args.warmup:
                    if warmup_rss is None:
                        warmup_rss = current_rss
                        peak_rss = current_rss
                    else:
                        peak_rss = max(peak_rss, current_rss)

                if elapsed >= args.duration:
                    break

                sample = collector.next_sample(
                    timeout=min(args.interval, 1.0)
                )
                if sample is not None:
                    sample_count += 1
    except (PowermetricsError, KeyboardInterrupt) as error:
        print(f"{mode} measurement did not complete: {error}", file=sys.stderr)
        return 1

    if warmup_rss is None or peak_rss is None:
        print("RSS observation window did not reach the warmup boundary", file=sys.stderr)
        return 1

    growth_mib = (peak_rss - warmup_rss) / (1024 * 1024)
    result = "PASS" if growth_mib <= args.max_growth_mib else "FAIL"
    print(
        f"{result} mode={mode} duration_s={args.duration:g} warmup_s={args.warmup:g} "
        f"samples={sample_count} warmup_rss_mib={warmup_rss / (1024 * 1024):.2f} "
        f"peak_rss_mib={peak_rss / (1024 * 1024):.2f} "
        f"growth_mib={growth_mib:.2f} limit_mib={args.max_growth_mib:g}"
    )
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
