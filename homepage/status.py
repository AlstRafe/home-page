"""What is running: each site's version (the git commit the VM checked out) and how the machine is doing.

``/version.json`` tells anyone which commit of each site is live (deploy/livecheck.py waits for the
commit a push made before it checks the pages); the owner's box at the bottom of the index shows the
same with when each arrived, and the machine's load, memory and disk (the VM has 1 GB and 1/8 of a CPU).
Everything is read from files (``.git``, ``/proc``): no program is started for it.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))


def git_head(folder: Path) -> tuple[str, datetime | None]:
    """The commit checked out in ``folder`` and when the branch last moved there (the VM's update.sh
    resets master to GitHub's), or ("", None) when it is no git clone. The files are read as they are,
    so it costs no git process (VAL Tracker's paths.deployed_version does the same)."""
    git = Path(folder) / ".git"
    try:
        if git.is_file():  # a worktree: "gitdir: <path>"
            git = (git.parent / git.read_text(encoding="utf-8").strip().removeprefix("gitdir: ")).resolve()
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            return head, _changed(git / "HEAD")
        ref = head[5:]
        loose = git / ref
        if loose.is_file():
            return loose.read_text(encoding="utf-8").strip(), _changed(loose)
        packed = git / "packed-refs"
        for line in packed.read_text(encoding="utf-8").splitlines():
            if line.endswith(" " + ref):
                return line.split(" ", 1)[0], _changed(packed)
    except (OSError, UnicodeDecodeError):
        pass
    return "", None


def _changed(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, JST)
    except OSError:
        return None


def machine(folder: Path) -> dict:
    """The machine now: ``load`` (1 minute), ``memory`` and ``swap`` (used, total bytes), ``disk``
    (free, total bytes where ``folder`` is), ``process`` (this server's resident bytes). What a
    system does not tell (Windows has no /proc) is left out."""
    found: dict = {}
    try:
        found["load"] = os.getloadavg()[0]
    except (AttributeError, OSError):
        pass
    info = _proc_numbers("/proc/meminfo")
    if "MemTotal" in info and "MemAvailable" in info:
        found["memory"] = (info["MemTotal"] - info["MemAvailable"], info["MemTotal"])
    if info.get("SwapTotal"):
        found["swap"] = (info["SwapTotal"] - info.get("SwapFree", 0), info["SwapTotal"])
    own = _proc_numbers("/proc/self/status")
    if "VmRSS" in own:
        found["process"] = own["VmRSS"]
    try:
        usage = shutil.disk_usage(folder)
        found["disk"] = (usage.free, usage.total)
    except OSError:
        pass
    return found


def _proc_numbers(path: str) -> dict[str, int]:
    """``Name:   123 kB`` lines of a /proc file, in bytes."""
    numbers: dict[str, int] = {}
    try:
        with open(path, encoding="ascii", errors="replace") as file:
            for line in file:
                name, _, rest = line.partition(":")
                parts = rest.split()
                if parts and parts[0].isdigit():
                    numbers[name] = int(parts[0]) * (1024 if parts[1:2] == ["kB"] else 1)
    except OSError:
        pass
    return numbers


def size(value: float) -> str:
    """Bytes for people: 954 MB, 1.9 GB."""
    for unit, scale in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if value >= scale:
            amount = value / scale
            return f"{amount:.1f} {unit}" if amount < 10 else f"{amount:.0f} {unit}"
    return f"{value:.0f} B"
