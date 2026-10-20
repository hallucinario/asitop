# asitop

Performance monitoring CLI tool for Apple Silicon, maintained by Hallucinario.
This fork preserves the terminal dashboard while bounding measurement memory
and eliminating growing capture files.

![](images/asitop.png)

## What is `asitop`

A Python-based `nvtop`-inspired command line tool for Apple Silicon (aka M1) Macs.

* Utilization info:
  * CPU (E-cluster and P-cluster), GPU
  * Frequency and utilization
  * ANE utilization (measured by power)
* Memory info:
  * RAM and swap, size and usage
  * (Apple removed memory bandwidth from `powermetrics`)
* Power info:
  * CPU power, GPU power (Apple removed package power from `powermetrics`)
  * Chart for CPU/GPU power
  * Peak power, rolling average display

`asitop` uses the built-in [`powermetrics`](https://www.unix.com/man-page/osx/1/powermetrics/) utility on macOS, which allows access to a variety of hardware performance counters. Note that it requires `sudo` to run due to `powermetrics` needing root access to run. `asitop` is lightweight and has minimal performance impact.

**`asitop` requires an Apple Silicon Mac with macOS `powermetrics` support.**

## Installation and Usage

`asitop` requires Python 3.12 or newer. From a
[hallucinario/dot-files](https://github.com/hallucinario/dot-files) checkout,
install the reviewed revision and its frozen dependencies with Ansible:

```shell
task ansible:local -- --tags uv,asitop
asitop --version
# asitop 0.0.25+hlc.1
```

For a standalone source installation, check out the release and use its lockfile:

```shell
git clone --branch 'v0.0.25+hlc.1' --single-branch https://github.com/hallucinario/asitop.git
cd asitop
uv sync --frozen --no-dev --no-editable --python 3.14.7
uv run --frozen --no-sync asitop
```

```shell
# Run from Terminal; powermetrics may prompt for administrator authorization.
asitop

# Existing root-launched mode is also supported.
sudo asitop

# Options
asitop [-h] [--interval INTERVAL] [--color COLOR] [--avg AVG]
optional arguments:
  -h, --help           show this help message and exit
  --version            show the fork version and exit
  --interval INTERVAL  Display interval and sampling interval for powermetrics (seconds)
  --color COLOR        Choose display color (0~8)
  --avg AVG            Interval for averaged values (seconds)
  --show_cores         Show per-core CPU gauges
```

The fork reads NUL-delimited plist samples directly from `powermetrics` stdout.
It discards superseded complete frames before XML deserialization and reclaims
the parser's reference cycles after each consumed sample. This also bounds
transient parser allocations on Python 3.14.0-3.14.4's incremental GC.
It does not create or reread a growing capture file. `--max_count` was removed
because the streaming producer is managed for the lifetime of the CLI.

## Development and verification

The project uses a frozen `uv.lock`; the resolver excludes package releases newer than 30 days. Run the local checks from a checkout:

```shell
uv sync --locked
uv run --frozen python -m unittest discover -s tests -v
uv build --no-sources
uv run --frozen asitop --version
uv run --frozen python scripts/ui_smoke.py
uv run --frozen python scripts/measure_memory.py --duration 60 --warmup 10
```

The UI smoke injects generated synthetic samples and does not run `powermetrics` or `sudo`. The synthetic memory measurement exercises the real collector with a continuous fake producer.

For a native 30-minute observation on an Apple Silicon Mac, after 5 minutes of warmup:

```shell
uv run --frozen python scripts/measure_memory.py \
  --native --duration 1800 --warmup 300 --max-growth-mib 16
```

The native measurement launches the existing privileged `powermetrics` command. It is intentionally not run in CI or by synthetic verification. Record the result as unverified until run on target hardware.

## How it works

`powermetrics` is used to measure the following:

* CPU/GPU utilization via active residency
* CPU/GPU frequency
* Package/CPU/GPU/ANE energy consumption
* CPU/GPU/Media Total memory bandwidth via the DCS (DRAM Command Scheduler)

[`psutil`](https://github.com/giampaolo/psutil) is used to measure the following:

* memory and swap usage

[`sysctl`](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man3/sysctl.3.html) is used to measure the following:

* CPU name
* CPU core counts

[`system_profiler`](https://ss64.com/osx/system_profiler.html) is used to measure the following:

* GPU core count

Some information is guesstimate and hardcoded as there doesn't seem to be a official source for it on the system:

* CPU/GPU TDP
* CPU/GPU maximum memory bandwidth
* ANE max power
* Media engine max bandwidth

## Why

Because I didn't find something like this online. Also, just curious about stuff.

## Disclaimers

I did this randomly don't blame me if it fried your new MacBook or something.
