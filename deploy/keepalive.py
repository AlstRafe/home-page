"""Keeps an Oracle Cloud Always Free VM from counting as idle (sites-keepalive.service runs it).

Oracle may reclaim an Always Free VM when, over 7 days, its CPU (95th percentile), its network and,
on the Arm (A1) shapes, its memory all stay under 20%. A small site is far under all three, so this
keeps two of them above: it holds a quarter of the memory when there is plenty (4 GB or more), and
works one CPU for 90 seconds in every 10 minutes at the lowest priority (the service runs it with
the idle scheduler).

The idle scheduler alone is not enough on the 1/8-OCPU micro VM: its two CPUs share one small
allowance, so a loop on one CPU halves what the server gets on the other. The loop therefore works
in short slices and sleeps whenever anything else wants a CPU (/proc/loadavg's running count): the
sites, Tailscale and the collector always come first, and their own work counts as busy too.

KEEPALIVE_MEMORY_PERCENT (default 25, 0 = none) and KEEPALIVE_BUSY_SECONDS (default 90 per 600)
change how much.
"""

from __future__ import annotations

import mmap
import os
import time

PERIOD = 600
PAGE = mmap.PAGESIZE
#: Work this long between two looks at whether anything else wants a CPU; otherwise sleep this long.
SLICE, YIELD = 0.01, 0.2


def total_memory() -> int:
    try:
        with open("/proc/meminfo", encoding="ascii") as info:
            for line in info:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def hold_memory(percent: int) -> mmap.mmap | None:
    total = total_memory()
    if percent <= 0 or total < 4 * 1024**3:  # a 1 GB micro VM needs its memory for the sites
        return None
    size = total * percent // 100 // PAGE * PAGE
    block = mmap.mmap(-1, size)
    touch(block)
    print(f"{size // 1024**2} MB を確保しました（全体の {percent}%）", flush=True)
    return block


def touch(block: mmap.mmap) -> None:
    """Write to every page, so the memory is really in use (not only promised)."""
    for offset in range(0, len(block), PAGE):
        block[offset] = (block[offset] + 1) % 256


def others_running() -> bool:
    """Whether anything besides this process is running or waiting for a CPU right now."""
    try:
        with open("/proc/loadavg", encoding="ascii") as load:
            return int(load.read().split()[3].split("/")[0]) > 1
    except (OSError, ValueError, IndexError):
        return False


def busy(seconds: float) -> None:
    """Keep a CPU busy for ``seconds``, yielding it at once to anything else that wants it."""
    end = time.monotonic() + seconds
    n = 0
    while time.monotonic() < end:
        if others_running():
            time.sleep(YIELD)
            continue
        stop = min(end, time.monotonic() + SLICE)
        while time.monotonic() < stop:
            for _ in range(1_000):
                n = (n * 1_103_515_245 + 12_345) % 2_147_483_648


def main() -> None:
    block = hold_memory(int(os.environ.get("KEEPALIVE_MEMORY_PERCENT", "25")))
    seconds = min(float(os.environ.get("KEEPALIVE_BUSY_SECONDS", "90")), PERIOD / 2)
    while True:
        started = time.monotonic()
        busy(seconds)
        if block is not None:
            touch(block)
        time.sleep(max(0.0, PERIOD - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
