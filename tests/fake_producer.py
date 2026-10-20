import plistlib
import sys
import time


def record(sequence):
    return plistlib.dumps(
        {"timestamp": sequence, "sequence": sequence},
        fmt=plistlib.FMT_XML,
    )


def write(data):
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def main():
    mode = sys.argv[1]

    if mode == "fragmented":
        payload = record(7) + b"\0"
        for offset in range(0, len(payload), 7):
            write(payload[offset:offset + 7])
            time.sleep(0.001)
    elif mode == "batch":
        count = int(sys.argv[2])
        write(b"\0".join(record(sequence) for sequence in range(count)) + b"\0")
    elif mode == "eof":
        write(record(11))
    elif mode == "malformed":
        write(b"not a plist\0")
        time.sleep(60)
    elif mode == "oversized":
        remaining = 2 * 1024 * 1024 + 1
        while remaining:
            chunk = b"x" * min(8192, remaining)
            write(chunk)
            remaining -= len(chunk)
        time.sleep(60)
    elif mode == "stderr-failure":
        sys.stderr.buffer.write(b"A" * (20 * 1024) + b"TAIL")
        sys.stderr.buffer.flush()
        raise SystemExit(7)
    elif mode == "stall":
        time.sleep(60)
    elif mode == "sample-stall":
        write(record(1) + b"\0")
        time.sleep(60)
    elif mode == "continuous":
        sequence = 0
        while True:
            write(record(sequence) + b"\0")
            sequence += 1
            time.sleep(0.002)
    else:
        raise SystemExit(f"unknown fake producer mode: {mode}")


if __name__ == "__main__":
    main()
