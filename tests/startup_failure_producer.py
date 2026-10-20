"""A finite producer for startup-error integration regressions."""
import sys

if sys.argv[1] == 'invalid-xml':
    sys.stdout.buffer.write(b'<?xml version="1.0"?><plist><dict></plist>\0')
    sys.stdout.buffer.flush()
else:
    sys.stderr.write('distinct producer startup failure\n')
    sys.stderr.flush()
    raise SystemExit(7)
