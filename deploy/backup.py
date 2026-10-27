"""A copy of News Site's instance/ (databases, settings, session key) as one dated file:

    python backup.py INSTANCE_FOLDER BACKUP_FOLDER [KEEP]

The databases are copied through SQLite's backup (consistent even while the site writes to them);
the newest KEEP copies (default 14) stay. The saved articles are not in it (they are big, and the
collector keeps adding to them); the boot volume they are on stays with the VM.
"""
from __future__ import annotations

import sqlite3
import sys
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

SKIP = {"collector.lock"}


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    instance, folder = Path(argv[0]), Path(argv[1])
    keep = int(argv[2]) if len(argv) == 3 else 14
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"news-instance-{datetime.now():%Y%m%d-%H%M%S}.tar.gz"
    with tempfile.TemporaryDirectory(dir=folder) as temporary, \
            tarfile.open(target.with_suffix(".part"), "w:gz") as tar:
        for path in sorted(instance.iterdir()):
            if not path.is_file() or path.name in SKIP or path.name.endswith(("-wal", "-shm", "-journal")):
                continue
            if path.suffix == ".sqlite3":
                copy = Path(temporary) / path.name
                source, dest = sqlite3.connect(f"file:{path}?mode=ro", uri=True), sqlite3.connect(copy)
                try:
                    source.backup(dest)
                finally:
                    source.close()
                    dest.close()
                tar.add(copy, arcname=f"instance/{path.name}")
            else:
                tar.add(path, arcname=f"instance/{path.name}")
    target.with_suffix(".part").rename(target)
    target.chmod(0o600)
    old = sorted(folder.glob("news-instance-*.tar.gz"))[:-keep]
    for path in old:
        path.unlink()
    print(f"{target.name}（{target.stat().st_size // 1024} KB）、古いもの {len(old)} 個を削除")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
