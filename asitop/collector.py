import os
import plistlib
import selectors
import subprocess
import time


MAX_READ_BYTES = 64 * 1024
MAX_PENDING_BYTES = 2 * 1024 * 1024
MAX_STDERR_BYTES = 16 * 1024


class PowermetricsError(RuntimeError):
    """Base class for collector and producer failures."""


class MalformedSampleError(PowermetricsError):
    """The producer emitted a complete record that is not a valid plist sample."""


class OversizedSampleError(PowermetricsError):
    """The producer emitted a sample larger than the configured pending limit."""


class SampleTimeout(PowermetricsError):
    """The producer did not provide a first or subsequent sample in time."""


class ProducerError(PowermetricsError):
    """powermetrics exited unsuccessfully."""


class ProducerExited(PowermetricsError):
    """The producer exited successfully and has no more samples."""


def build_powermetrics_command(interval_ms, nice=10):
    return [
        "sudo",
        "nice",
        "-n",
        str(nice),
        "powermetrics",
        "--samplers",
        "cpu_power,gpu_power,thermal",
        "-f",
        "plist",
        "-b",
        "0",
        "-i",
        str(interval_ms),
    ]


class PowermetricsCollector:
    """Read NUL-delimited plist records from a bounded subprocess stream."""

    def __init__(
        self,
        interval_seconds=1,
        nice=10,
        command=None,
        idle_timeout=None,
        popen_factory=subprocess.Popen,
        clock=time.monotonic,
    ):
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")

        self.interval_seconds = interval_seconds
        self.idle_timeout = (
            max(30.0, interval_seconds * 3)
            if idle_timeout is None
            else float(idle_timeout)
        )
        if self.idle_timeout <= 0:
            raise ValueError("idle_timeout must be positive")

        interval_ms = int(interval_seconds * 1000)
        self.command = list(command or build_powermetrics_command(interval_ms, nice))
        self._popen = popen_factory
        self._clock = clock
        self._selector = selectors.DefaultSelector()
        self.process = None
        self._pending = bytearray()
        self._stderr_tail = bytearray()
        self._latest_sample = None
        self._sample_ready = False
        self._has_sample = False
        self._started_at = None
        self._last_sample_at = None
        self._stdout_eof = False
        self._stderr_eof = False
        self._closed = False

    @property
    def pending_size(self):
        return len(self._pending)

    @property
    def stderr_tail(self):
        return bytes(self._stderr_tail)

    def __enter__(self):
        if self.process is not None:
            raise RuntimeError("collector has already been started")
        if self._closed:
            raise RuntimeError("collector is closed")

        try:
            self.process = self._popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
            if self.process.stdin is not None:
                self.process.stdin.close()

            for stream, name in (
                (self.process.stdout, "stdout"),
                (self.process.stderr, "stderr"),
            ):
                os.set_blocking(stream.fileno(), False)
                self._selector.register(stream, selectors.EVENT_READ, name)

            self._started_at = self._clock()
            self._last_sample_at = self._started_at
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

    def close(self):
        if self._closed:
            return
        self._closed = True

        process = self.process
        try:
            self._selector.close()
        finally:
            if process is not None:
                if process.poll() is None:
                    try:
                        process.terminate()
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        try:
                            process.kill()
                        except ProcessLookupError:
                            pass
                        process.wait()

                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None and not stream.closed:
                        stream.close()

    def next_sample(self, timeout=None):
        if self.process is None:
            raise RuntimeError("collector has not been started")
        if self._closed:
            raise RuntimeError("collector is closed")

        call_deadline = None if timeout is None else self._clock() + max(0, timeout)
        while True:
            self._raise_for_process_failure()

            if self._sample_ready:
                return_code = self.process.poll()
                if not (
                    return_code is not None
                    and return_code != 0
                    and not (self._stdout_eof and self._stderr_eof)
                ):
                    sample = self._latest_sample
                    self._latest_sample = None
                    self._sample_ready = False
                    return sample

            now = self._clock()
            hard_deadline = self._last_sample_at + self.idle_timeout
            hard_remaining = hard_deadline - now
            if hard_remaining <= 0:
                phase = "sample stream" if self._has_sample else "first sample"
                raise SampleTimeout(
                    f"powermetrics {phase} deadline exceeded "
                    f"({self.idle_timeout:g} seconds)"
                )

            if call_deadline is not None:
                call_remaining = call_deadline - now
                if call_remaining <= 0:
                    return None
                wait_timeout = min(hard_remaining, call_remaining)
            else:
                wait_timeout = hard_remaining

            try:
                ready = self._selector.select(wait_timeout)
            except InterruptedError:
                continue

            if not ready:
                self._raise_for_process_failure()
                now = self._clock()
                if now >= hard_deadline:
                    phase = "sample stream" if self._has_sample else "first sample"
                    raise SampleTimeout(
                        f"powermetrics {phase} deadline exceeded "
                        f"({self.idle_timeout:g} seconds)"
                    )
                if call_deadline is not None and now >= call_deadline:
                    return None
                continue

            for key, _ in ready:
                self._read_ready_stream(key.fileobj, key.data)

    def _read_ready_stream(self, stream, name):
        try:
            chunk = os.read(stream.fileno(), MAX_READ_BYTES)
        except BlockingIOError:
            return
        except OSError as error:
            if self._closed:
                return
            raise PowermetricsError(f"could not read powermetrics {name}: {error}") from error

        if not chunk:
            try:
                self._selector.unregister(stream)
            except (KeyError, ValueError):
                pass
            if name == "stdout":
                self._stdout_eof = True
                self._finish_stdout()
            else:
                self._stderr_eof = True
            return

        if name == "stdout":
            self._consume_stdout(chunk)
        else:
            self._consume_stderr(chunk)

    def _consume_stdout(self, chunk):
        start = 0
        while True:
            separator = chunk.find(b"\0", start)
            if separator < 0:
                remaining = chunk[start:]
                if len(self._pending) + len(remaining) > MAX_PENDING_BYTES:
                    raise OversizedSampleError(
                        f"powermetrics sample exceeds {MAX_PENDING_BYTES} bytes"
                    )
                self._pending.extend(remaining)
                return

            fragment = chunk[start:separator]
            if len(self._pending) + len(fragment) > MAX_PENDING_BYTES:
                raise OversizedSampleError(
                    f"powermetrics sample exceeds {MAX_PENDING_BYTES} bytes"
                )
            if fragment:
                self._pending.extend(fragment)
            record = bytes(self._pending)
            self._pending.clear()
            if record.strip():
                self._parse_record(record)
            start = separator + 1

    def _finish_stdout(self):
        if self._pending.strip():
            record = bytes(self._pending)
            self._pending.clear()
            self._parse_record(record)
        else:
            self._pending.clear()

    def _parse_record(self, record):
        try:
            sample = plistlib.loads(record)
        except Exception as error:
            raise MalformedSampleError(
                f"powermetrics emitted a malformed plist sample: {error}"
            ) from error

        if not isinstance(sample, dict) or "timestamp" not in sample:
            raise MalformedSampleError(
                "powermetrics plist sample must be a dictionary with a timestamp"
            )

        self._latest_sample = sample
        self._sample_ready = True
        self._has_sample = True
        self._last_sample_at = self._clock()

    def _consume_stderr(self, chunk):
        self._stderr_tail.extend(chunk)
        if len(self._stderr_tail) > MAX_STDERR_BYTES:
            del self._stderr_tail[:-MAX_STDERR_BYTES]

    def _raise_for_process_failure(self):
        return_code = self.process.poll()
        if (
            return_code is not None
            and return_code != 0
            and self._stdout_eof
            and self._stderr_eof
        ):
            diagnostic = self.stderr_tail.decode("utf-8", errors="replace").strip()
            message = f"powermetrics exited with status {return_code}"
            if diagnostic:
                message = f"{message}: {diagnostic}"
            raise ProducerError(message)

        if (
            return_code == 0
            and self._stdout_eof
            and self._stderr_eof
            and not self._sample_ready
        ):
            raise ProducerExited("powermetrics exited successfully")
