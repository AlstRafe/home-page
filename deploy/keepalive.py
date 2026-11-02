"""Keeps an Oracle Cloud Always Free VM from counting as idle (sites-keepalive.service runs it).

Oracle may reclaim an Always Free VM when, over 7 days, its CPU (95th percentile), its network and,
on the Arm (A1) shapes, its memory all stay under 20%. A small site is far under all three, so this
keeps two of them above: it holds a quarter of the memory when there is plenty (4 GB or more), and
keeps the CPUs busy for two hours every night.

Only at night, because on the 1/8-OCPU micro VM any CPU it uses is taken from the sites: the guest's
CPUs share one small allowance, so even a loop that steps aside at once uses up the allowance the
server needs next (measured 2026-11-02: while the old loop ran, 90 seconds of every 10 minutes, the
VM lost 7-26% of its time to the hypervisor). Two hours a night is 8% of the week, more than the 5%
the 95th percentile looks past, and stays so whether Oracle averages over a minute, five or an hour
(90 seconds in 10 minutes did not, for five minutes or an hour). By day it does nothing.

KEEPALIVE_HOURS (UTC hours, default "18-20" = 03:00-05:00 in Japan, "" = never) and
KEEPALIVE_MEMORY_PERCENT (default 25, 0 = none) change it.
"""

from __future__ import annotations

import hashlib
import mmap
import os
import threading
import time

PERIOD = 600
PAGE = mmap.PAGESIZE
#: 03:00-05:00 in Japan, when the sites have no visitors to speak of.
NIGHT = "18-20"
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


def hours(spec: str) -> frozenset[int]:
    """The UTC hours of "start-end" (end not included; "23-1" goes over midnight); none for "" or nonsense."""
    try:
        start, end = (int(part) % 24 for part in spec.split("-"))
    except ValueError:
        return frozenset()
    return frozenset((start + step) % 24 for step in range((end - start) % 24))


def work_seconds(now: float, night: frozenset[int]) -> float:
    """How long from ``now`` (epoch seconds) until the night hours end; 0 outside them."""
    hour = time.gmtime(now).tm_hour
    if hour not in night:
        return 0.0
    left = 3600 - now % 3600
    while (hour := (hour + 1) % 24) in night and left < 24 * 3600:
        left += 3600
    return left


def others_running(own: int = 1) -> bool:
    """Whether anything besides this process's ``own`` workers is running or waiting for a CPU right now."""
    try:
        with open("/proc/loadavg", encoding="ascii") as load:
            return int(load.read().split()[3].split("/")[0]) > own
    except (OSError, ValueError, IndexError):
        return False


def busy(seconds: float, cpus: int = os.cpu_count() or 1) -> None:
    """Keep ``cpus`` CPUs busy for ``seconds``, each stepping aside at once for anything else that wants one."""
    end = time.monotonic() + seconds
    workers = [threading.Thread(target=_work, args=(end, cpus), daemon=True) for _ in range(cpus)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()


def _work(end: float, cpus: int) -> None:
    data = bytes(65536)  # hashing this much lets go of the GIL, so each thread has a CPU to itself
    while time.monotonic() < end:
        if others_running(cpus):
            time.sleep(YIELD)
            continue
        stop = min(end, time.monotonic() + SLICE)
        while time.monotonic() < stop:
            hashlib.sha256(data)


def main() -> None:
    block = hold_memory(int(os.environ.get("KEEPALIVE_MEMORY_PERCENT", "25")))
    night = hours(os.environ.get("KEEPALIVE_HOURS", NIGHT))
    while True:
        started = time.monotonic()
        seconds = min(PERIOD, work_seconds(time.time(), night))
        if seconds > 0:
            busy(seconds)
        if block is not None:
            touch(block)
        time.sleep(max(0.0, PERIOD - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
