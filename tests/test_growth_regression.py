import sys
import tracemalloc
import unittest
from pathlib import Path

from asitop.collector import MAX_PENDING_BYTES, PowermetricsCollector, ProducerExited


FAKE_PRODUCER = Path(__file__).with_name("fake_producer.py")


def collector_for(mode, *arguments, idle_timeout=2.0):
    return PowermetricsCollector(
        command=[sys.executable, str(FAKE_PRODUCER), mode, *map(str, arguments)],
        interval_seconds=1,
        idle_timeout=idle_timeout,
    )


class BoundedMemoryRegressionTests(unittest.TestCase):
    def test_large_sample_history_retains_only_latest_sample(self):
        sample_count = 50000
        latest = None
        warmup_bytes = None

        tracemalloc.start()
        try:
            with collector_for("batch", sample_count) as collector:
                while True:
                    try:
                        sample = collector.next_sample(timeout=1)
                    except ProducerExited:
                        break
                    if sample is not None:
                        latest = sample
                        if sample["sequence"] >= 1000 and warmup_bytes is None:
                            warmup_bytes = tracemalloc.get_traced_memory()[0]
                    self.assertLessEqual(collector.pending_size, MAX_PENDING_BYTES)

                self.assertLessEqual(collector.pending_size, MAX_PENDING_BYTES)
            _, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        self.assertEqual(latest["sequence"], sample_count - 1)
        self.assertIsNotNone(warmup_bytes)
        self.assertLessEqual(peak_bytes - warmup_bytes, MAX_PENDING_BYTES)


if __name__ == "__main__":
    unittest.main()
