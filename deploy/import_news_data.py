"""Take News Site's data from the PC into this server's copy (setup.sh --import runs it as the sites account):

    python import_news_data.py DATA.tar.gz APP_FOLDER BACKUP_FOLDER

DATA.tar.gz is what migrate.py packed on the PC: ``instance/`` (the databases, settings, the session
key), ``articles/`` (the saved pages) and ``secrets.json`` (the API keys from the Windows credential
store). What APP_FOLDER had before is moved under BACKUP_FOLDER, never deleted. The PC's own
folders in the settings are dropped (the articles live beside the app here), Windows-only records
are left out, and the keys go into this server's credential store (keyrings.alt, a file only the
sites account can read).
"""

from __future__ import annotations

import json
import shutil
import sys
import tarfile
from datetime import datetime
from pathlib import Path

#: Written by News Site on Windows for its own start, its scheduled task or the PC's host server.
WINDOWS_ONLY = {"collector-task.json", "server-task.json", "hosted.json", "collector.lock"}
SERVICE_NAME = "NewsHtmlReader"
SECRET_NAMES = {"azure_api_key", "stdict_api_key", "relay_token"}


def extract(archive: Path, into: Path) -> None:
    with tarfile.open(archive) as tar:
        members = [member for member in tar.getmembers() if member.isfile() or member.isdir()]
        if hasattr(tarfile, "data_filter"):
            tar.extractall(into, members=members, filter="data")
        else:  # Python before 3.11.4: refuse anything leaving the folder ourselves
            for member in members:
                target = (into / member.name).resolve()
                if into.resolve() not in target.parents and target != into.resolve():
                    raise ValueError(f"unsafe path in the archive: {member.name}")
            tar.extractall(into, members=members)


def edit_json(path: Path, change) -> None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        value = {}
    if not isinstance(value, dict):
        value = {}
    change(value)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def store_secrets(path: Path) -> list[str]:
    if not path.is_file():
        return []
    import keyring

    secrets = json.loads(path.read_text(encoding="utf-8"))
    stored = []
    for name, value in secrets.items():
        if name in SECRET_NAMES and isinstance(value, str) and value.strip():
            keyring.set_password(SERVICE_NAME, name, value.strip())
            stored.append(name)
    return stored


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    archive, app, backup = Path(argv[0]), Path(argv[1]).resolve(), Path(argv[2])
    staging = app / ".import"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(mode=0o700)
    try:
        extract(archive, staging)
        if not (staging / "instance").is_dir():
            print("instance/ が入っていません。migrate.py で作ったファイルですか？", file=sys.stderr)
            return 1
        for name in WINDOWS_ONLY:
            (staging / "instance" / name).unlink(missing_ok=True)
        articles = app / "articles"
        # The articles beside the app: no folder of the PC's in the settings, the collector's too.
        edit_json(
            staging / "instance" / "settings.json", lambda value: value.update(library_dir="", start_at_logon=False)
        )
        edit_json(staging / "instance" / "collector.json", lambda value: value.update(library_root=str(articles)))
        stored = store_secrets(staging / "secrets.json")

        kept = backup / f"before-import-{datetime.now():%Y%m%d-%H%M%S}"
        for name in ("instance", "articles"):
            if (app / name).exists():
                kept.mkdir(parents=True, exist_ok=True)
                shutil.move(str(app / name), str(kept / name))
            source = staging / name
            if source.is_dir():
                shutil.move(str(source), str(app / name))
            else:
                (app / name).mkdir()
        (app / "instance").chmod(0o700)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    count = sum(1 for path in (app / "articles").rglob("*") if path.is_file())
    print(
        f"取り込みました: 記事 {count} ファイル、instance/ {len(list((app / 'instance').iterdir()))} 個、"
        f"キー {', '.join(stored) or 'なし'}"
    )
    if kept.exists():
        print(f"それまでの instance/ と articles/ は {kept} に移しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
