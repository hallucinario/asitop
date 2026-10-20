"""Complete XML errors and already-exited producers keep useful diagnostics."""
import pathlib
import sys
import unittest
import contextlib
import io
from unittest import mock

from asitop.collector import PowermetricsCollector, PowermetricsError, ProducerError
from asitop import asitop as cli

PRODUCER = str(pathlib.Path(__file__).with_name('startup_failure_producer.py'))


class ProducerStartupRegressions(unittest.TestCase):
    def test_cli_launch_error_returns_failure_and_restores_cursor(self):
        output = io.StringIO()
        errors = io.StringIO()
        with mock.patch.object(cli, 'PowermetricsCollector',
                               side_effect=FileNotFoundError('producer not available')):
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                self.assertEqual(cli.main([]), 1)
        self.assertIn('producer not available', errors.getvalue())
        self.assertIn('\033[?25h', output.getvalue())

    def test_malformed_xml_reports_collector_error(self):
        with PowermetricsCollector(command=[sys.executable, PRODUCER, 'invalid-xml']) as collector:
            with self.assertRaises(PowermetricsError):
                collector.next_sample()

    def test_fast_failure_keeps_cause(self):
        with PowermetricsCollector(command=[sys.executable, PRODUCER, 'fast-failure']) as collector:
            collector.process.wait(timeout=2)
            with self.assertRaises(ProducerError) as raised:
                collector.next_sample()
            self.assertIn('distinct producer startup failure', str(raised.exception))


if __name__ == '__main__':
    unittest.main()
