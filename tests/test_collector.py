import sys
import time
import unittest
from pathlib import Path

from asitop.collector import (
    MAX_PENDING_BYTES,
    MAX_READ_BYTES,
    MAX_STDERR_BYTES,
    MalformedSampleError,
    OversizedSampleError,
    PowermetricsCollector,
    ProducerError,
    ProducerExited,
    SampleTimeout,
    build_powermetrics_command,
)


FAKE_PRODUCER = Path(__file__).with_name("fake_producer.py")


def collector_for(mode, *arguments, idle_timeout=2.0):
    return PowermetricsCollector(
        command=[sys.executable, str(FAKE_PRODUCER), mode, *map(str, arguments)],
        interval_seconds=1,
        idle_timeout=idle_timeout,
    )


class PowermetricsCollectorTests(unittest.TestCase):
    def test_command_uses_nul_plist_stdout_and_no_capture_file(self):
        command = build_powermetrics_command(interval_ms=1250, nice=10)

        self.assertIn("sudo", command)
        self.assertIn("powermetrics", command)
        self.assertIn("--samplers", command)
        self.assertIn("cpu_power,gpu_power,thermal", command)
        self.assertEqual(command[command.index("-f") + 1], "plist")
        self.assertEqual(command[command.index("-b") + 1], "0")
        self.assertEqual(command[command.index("-i") + 1], "1250")
        self.assertNotIn("-o", command)

    def test_default_idle_deadline_is_finite_and_at_least_thirty_seconds(self):
        collector = PowermetricsCollector(
            command=[sys.executable, str(FAKE_PRODUCER), "stall"],
            interval_seconds=12,
        )
        self.assertEqual(collector.idle_timeout, 36)
        collector.close()

        short_interval = PowermetricsCollector(
            command=[sys.executable, str(FAKE_PRODUCER), "stall"],
            interval_seconds=1,
        )
        self.assertEqual(short_interval.idle_timeout, 30)
        short_interval.close()

    def test_fragmented_plist_record_is_reassembled(self):
        with collector_for("fragmented") as collector:
            sample = collector.next_sample(timeout=1)

        self.assertEqual(sample["sequence"], 7)

    def test_batch_returns_latest_complete_sample(self):
        with collector_for("batch", 20) as collector:
            sample = collector.next_sample(timeout=1)

        self.assertEqual(sample["sequence"], 19)

    def test_valid_final_record_without_nul_is_accepted_at_eof(self):
        with collector_for("eof") as collector:
            sample = collector.next_sample(timeout=1)

        self.assertEqual(sample["sequence"], 11)

    def test_malformed_complete_record_is_rejected(self):
        collector = collector_for("malformed")
        with self.assertRaises(MalformedSampleError):
            with collector:
                collector.next_sample(timeout=1)
        self.assertIsNotNone(collector.process.poll())

    def test_oversized_sample_is_rejected_without_growing_pending_buffer(self):
        collector = collector_for("oversized")
        with self.assertRaises(OversizedSampleError):
            with collector:
                collector.next_sample(timeout=2)

        self.assertLessEqual(collector.pending_size, MAX_PENDING_BYTES)
        self.assertIsNotNone(collector.process.poll())

    def test_failed_producer_and_stderr_flood_are_reported_with_bounded_tail(self):
        collector = collector_for("stderr-failure")
        with self.assertRaises(ProducerError) as raised:
            with collector:
                collector.next_sample(timeout=2)

        self.assertLessEqual(len(collector.stderr_tail), MAX_STDERR_BYTES)
        self.assertIn(b"TAIL", collector.stderr_tail)
        self.assertIn("7", str(raised.exception))

    def test_first_sample_deadline_terminates_stalled_child(self):
        collector = collector_for("stall", idle_timeout=0.05)
        with self.assertRaises(SampleTimeout):
            with collector:
                collector.next_sample()

        self.assertIsNotNone(collector.process.poll())

    def test_stall_deadline_resets_only_after_complete_sample(self):
        collector = collector_for("sample-stall", idle_timeout=0.05)
        with self.assertRaises(SampleTimeout):
            with collector:
                self.assertEqual(collector.next_sample(timeout=1)["sequence"], 1)
                collector.next_sample()

        self.assertIsNotNone(collector.process.poll())

    def test_context_manager_closes_child_when_consumer_raises(self):
        collector = collector_for("stall")
        with self.assertRaisesRegex(RuntimeError, "consumer failed"):
            with collector:
                process = collector.process
                raise RuntimeError("consumer failed")

        self.assertIsNotNone(process.poll())

    def test_continuous_producer_does_not_starve_consumer_after_a_pause(self):
        collector = collector_for("continuous", idle_timeout=0.5)
        with collector:
            first = collector.next_sample(timeout=1)
            time.sleep(0.03)
            second = collector.next_sample(timeout=0.5)

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertGreaterEqual(second["sequence"], first["sequence"])
        self.assertLessEqual(collector.pending_size, MAX_PENDING_BYTES)
        self.assertLessEqual(MAX_READ_BYTES, 64 * 1024)


if __name__ == "__main__":
    unittest.main()
