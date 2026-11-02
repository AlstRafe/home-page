"""Move the sites from this PC to the cloud server, from the Home Page folder:

    py -3 deploy\\migrate.py

1. checks that the server answers over Tailscale SSH (``ssh ubuntu@sites``);
2. sets it up (deploy/setup.sh): packages, the GitHub deploy keys (shown here; it waits while you add
   them on GitHub), the three repositories, the services and Funnel;
   -- asks before going on: from here on this PC changes --
3. turns News Site's hourly collection on this PC off, so nothing is collected here after the copy;
4. packs News Site's data (the databases through SQLite's backup, the settings, the saved articles and
   the API keys from the Windows credential store), sends it over Tailscale and takes it in there;
5. stops this PC's server, its start at logon and its Funnel, and hands this PC's public address
   (https://<this PC>.<tailnet>.ts.net/) to the server, so the links people have keep working: this PC
   is renamed <name>-pc in Tailscale. With --new-address the server keeps its own name instead.

Options: --host sites  --user ubuntu  --new-address  --data-only (steps 3-4)  --address-only (step 5)
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import urllib.request
from pathlib import Path

HOME = Path(__file__).resolve().parent.parent
REMOTE_SETUP = "/srv/sites/Home Page/deploy/setup.sh"
SECRET_SERVICE = "NewsHtmlReader"
SECRET_NAMES = ("azure_api_key", "relay_token", "stdict_api_key")
SKIP = {"collector.lock", "collector-task.json", "server-task.json", "hosted.json"}
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class Stop(Exception):
    """A step that cannot go on: the message says why and what to do."""


# -- the server, over ssh ---------------------------------------------------------------------------


class Server:
    def __init__(self, host: str, user: str):
        self.user = user
        self.target = f"{user}@{host}"

    def pin(self) -> None:
        """Talk to the server by its Tailscale address from now on: its name changes in step 5."""
        done = self.run("tailscale ip -4", capture=True)
        address = (done.stdout or "").strip().splitlines()[:1]
        if done.returncode == 0 and address:
            self.target = f"{self.user}@{address[0]}"

    def command(self, remote: str, *, tty: bool = False) -> list[str]:
        return [
            "ssh",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "ConnectTimeout=30",
            *(["-t"] if tty else []),
            self.target,
            remote,
        ]

    def run(self, remote: str, *, tty: bool = False, stdin=None, capture: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run(
            self.command(remote, tty=tty), stdin=stdin, text=capture if capture else None, capture_output=capture
        )

    def send(self, local: Path, remote_name: str) -> None:
        with local.open("rb") as data:
            if self.run(f"umask 077 && cat > {shlex.quote(remote_name)}", stdin=data).returncode != 0:
                raise Stop(f"{local.name} をサーバーへ送れませんでした。")


def check_ssh(server: Server) -> None:
    if not shutil.which("ssh"):
        raise Stop(
            "ssh がありません。Windows の「設定 → システム → オプション機能」で OpenSSH クライアントを追加してください。"
        )
    print(f"{server.target} につないでいます（初回はブラウザでの確認を求められることがあります）...")
    if server.run("true").returncode != 0:
        raise Stop(
            f"{server.target} に ssh で入れませんでした。VM が Tailscale の管理画面に出ているか、"
            "deploy/README.md の「うまくいかないとき」を見てください。"
        )
    server.pin()


def set_up(server: Server) -> None:
    script = (HOME / "deploy" / "setup.sh").read_bytes().replace(b"\r\n", b"\n")  # even from a CRLF checkout
    if subprocess.run(server.command("umask 077 && cat > sites-setup.sh"), input=script).returncode != 0:
        raise Stop("setup.sh をサーバーへ送れませんでした。")
    while True:
        code = server.run("sudo bash sites-setup.sh", tty=True).returncode
        if code == 0:
            return
        if code != 3:
            raise Stop(
                f"サーバーの準備が途中で止まりました（コード {code}）。上の表示を見て、直したらもう一度実行してください。"
            )
        input("\n上の鍵を GitHub に登録したら Enter を押してください（やめるなら Ctrl+C）: ")


# -- News Site on this PC ---------------------------------------------------------------------------


def news_app() -> Path:
    """News Site's folder: the /news site of sites.toml."""
    data = tomllib.loads((HOME / "sites.toml").read_text(encoding="utf-8"))
    for entry in data.get("site", []):
        if isinstance(entry, dict) and entry.get("mount") == "/news" and isinstance(entry.get("python"), str):
            return (HOME / entry["python"]).resolve()
    raise Stop("sites.toml に /news のサイトが見つかりません。")


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def library_folder(app: Path) -> Path:
    configured = (
        read_json(app / "instance" / "collector.json").get("library_root")
        or read_json(app / "instance" / "settings.json").get("library_dir")
        or ""
    )
    folder = Path(configured).expanduser() if isinstance(configured, str) and configured.strip() else app / "articles"
    return folder if folder.is_dir() else app / "articles"


def collector_idle(lock: Path) -> bool:
    if not lock.is_file():
        return True
    with lock.open("a+b") as handle:
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            return False
    return True


def stop_collection(app: Path) -> None:
    name = read_json(app / "instance" / "collector-task.json").get("task_name")
    if os.name == "nt" and name:
        done = subprocess.run(
            ["schtasks", "/Change", "/TN", name, "/DISABLE"],
            capture_output=True,
            text=True,
            errors="replace",
            creationflags=NO_WINDOW,
        )
        print(
            f"このPCの毎時の収集（{name}）を止めました。"
            if done.returncode == 0
            else f"このPCの毎時の収集（{name}）を止められませんでした: {done.stderr.strip()}"
        )
    deadline = time.monotonic() + 30 * 60
    while not collector_idle(app / "instance" / "collector.lock"):
        if time.monotonic() > deadline:
            raise Stop("収集が30分たっても終わりません。終わってからもう一度実行してください。")
        print("収集の途中です。終わるのを待っています...")
        time.sleep(15)


def python_with_keyring(app: Path) -> list[str]:
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    found = [sys.executable]
    for pattern in ("HomePage/venvs/*/Scripts/python.exe", "NewsHtmlReader/venvs/*/Scripts/python.exe"):
        found += [str(path) for path in local.glob(pattern)]
    found += [str(app / ".venv" / "Scripts" / "python.exe"), str(app / ".venv" / "bin" / "python")]
    return [item for item in dict.fromkeys(found) if Path(item).is_file()]


def read_secrets(app: Path) -> dict:
    """The API keys News Site keeps in the Windows credential store (through keyring, like News Site)."""
    code = "import json, keyring; print(json.dumps({n: keyring.get_password(%r, n) or '' for n in %r}))" % (
        SECRET_SERVICE,
        SECRET_NAMES,
    )
    for python in python_with_keyring(app):
        try:
            out = subprocess.run(
                [python, "-c", code], capture_output=True, text=True, timeout=60, check=True, creationflags=NO_WINDOW
            ).stdout
            secrets = json.loads(out.strip().splitlines()[-1])
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            continue
        return {name: value for name, value in secrets.items() if value}
    print("警告: API キーを読めませんでした。サーバーの News Site の設定画面で入れ直してください。")
    return {}


def pack(app: Path, target: Path) -> None:
    instance = app / "instance"
    articles = library_folder(app)
    secrets = read_secrets(app)
    with (
        tempfile.TemporaryDirectory() as temporary,
        tarfile.open(target, "w:gz", compresslevel=6, format=tarfile.PAX_FORMAT) as tar,
    ):
        for path in sorted(instance.iterdir()):
            if not path.is_file() or path.name in SKIP or path.name.endswith(("-wal", "-shm", "-journal")):
                continue
            if path.suffix == ".sqlite3":  # a consistent copy even while the site writes to it
                copy = Path(temporary) / path.name
                source, dest = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True), sqlite3.connect(copy)
                try:
                    source.backup(dest)
                finally:
                    source.close()
                    dest.close()
                tar.add(copy, arcname=f"instance/{path.name}")
            else:
                tar.add(path, arcname=f"instance/{path.name}")
        print(f"記事を詰めています: {articles}")
        tar.add(articles, arcname="articles")
        if secrets:
            keys = Path(temporary) / "secrets.json"
            keys.write_text(json.dumps(secrets), encoding="utf-8")
            tar.add(keys, arcname="secrets.json")
    print(f"詰めました: {target.stat().st_size / 1024**2:.0f} MB（キー {', '.join(secrets) or 'なし'}）")


def move_data(server: Server) -> None:
    app = news_app()
    stop_collection(app)
    with tempfile.TemporaryDirectory() as temporary:
        archive = Path(temporary) / "news-data.tar.gz"
        pack(app, archive)
        print("サーバーへ送っています（数分かかります）...")
        server.send(archive, "news-data.tar.gz")
    if server.run(f"sudo bash {shlex.quote(REMOTE_SETUP)} --import news-data.tar.gz", tty=True).returncode != 0:
        raise Stop("サーバーでの取り込みに失敗しました。上の表示を見てください。")


# -- this PC's server and its address ---------------------------------------------------------------


def tailscale_cli() -> str | None:
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    for item in (shutil.which("tailscale"), os.path.join(program_files, "Tailscale", "tailscale.exe")):
        if item and os.path.isfile(item):
            return item
    return None


def tailscale(*args: str) -> subprocess.CompletedProcess:
    cli = tailscale_cli()
    if not cli:
        raise Stop("このPCに tailscale のコマンドが見つかりません。")
    return subprocess.run([cli, *args], capture_output=True, text=True, errors="replace", creationflags=NO_WINDOW)


def own_name() -> str:
    """This PC's name in the tailnet now (the first label of its MagicDNS name)."""
    try:
        status = json.loads(tailscale("status", "--json").stdout).get("Self") or {}
    except ValueError:
        status = {}
    return str(status.get("DNSName") or "").split(".")[0].lower()


def stop_pc_server() -> None:
    sys.path.insert(0, str(HOME))
    import launcher

    launcher.ensure_logon_task(False)
    if os.name == "nt":
        listing = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                'Get-CimInstance Win32_Process | ForEach-Object { "$($_.ProcessId)`t$($_.CommandLine)" }',
            ],
            capture_output=True,
            text=True,
            errors="replace",
            creationflags=NO_WINDOW,
        ).stdout
        marks = [f"{str(HOME).casefold()}\\launcher.py", str(launcher.RUNTIME).casefold()]
        pids = [
            int(pid)
            for pid, _, command in (line.partition("\t") for line in listing.splitlines())
            if pid.isdecimal() and int(pid) != os.getpid() and any(mark in command.casefold() for mark in marks)
        ]
        for pid in pids + launcher.python_site_servers():
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
        print(f"このPCのサーバーを止めました（{len(pids)} 個のプロセス）。ログオン時の自動起動も外しました。")
    tailscale("funnel", "reset")
    print("このPCの Funnel（公開）を止めました。")


def hand_over_address(server: Server, new_address: bool) -> str:
    """Publish the server, under this PC's public name unless ``new_address``: this PC becomes <name>-pc
    (a rerun after renaming this PC by hand picks the name up from there)."""
    funnel = f"sudo bash {shlex.quote(REMOTE_SETUP)} --funnel"
    name = own_name()
    if new_address or not name:
        remote = funnel
    else:
        original = name.removesuffix("-pc")
        if name == original:
            tailscale("set", f"--hostname={original}-pc")
            deadline = time.monotonic() + 60
            while own_name() == original and time.monotonic() < deadline:
                time.sleep(3)
            if own_name() == original:
                raise Stop(
                    f"このPCの Tailscale での名前を {original}-pc に変えられませんでした。管理画面（Machines → このPC → "
                    f"Edit machine name）で変えてから、--address-only を付けてもう一度実行してください。"
                )
            print(f"このPCの Tailscale での名前を {original}-pc にしました。")
        quoted = shlex.quote(original)
        remote = f"sudo tailscale set --hostname={quoted} && sudo hostnamectl set-hostname {quoted} && {funnel}"
    if server.run(remote, tty=True).returncode != 0:
        raise Stop("サーバーの公開に失敗しました。上の表示を見てください。")
    done = server.run("tailscale status --json", capture=True)
    try:
        dns = str((json.loads(done.stdout).get("Self") or {}).get("DNSName") or "").rstrip(".")
    except ValueError:
        dns = ""
    return f"https://{dns}/" if dns else ""


def wait_for(address: str) -> None:
    if not address.startswith("https://"):
        return
    deadline = time.monotonic() + 180  # the first request waits for the certificate
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(address, timeout=30) as answer:
                if answer.status == 200:
                    print(
                        f"公開アドレスが答えています: {address}（Funnel で外にも公開済み。スマホのモバイル回線でも確かめてください）"
                    )
                    return
        except OSError:
            pass
        time.sleep(5)
    print(f"{address} がまだ答えません。数分後にブラウザで開いてみてください。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="py -3 deploy\\migrate.py", description="このPCのサイトをクラウドのサーバーへ移す"
    )
    parser.add_argument("--host", default="sites", help="サーバーの Tailscale での名前（既定: sites）")
    parser.add_argument("--user", default="ubuntu")
    parser.add_argument(
        "--new-address", action="store_true", help="このPCのアドレスを引き継がず、サーバー自身の名前で公開する"
    )
    parser.add_argument("--data-only", action="store_true", help="News Site のデータだけをもう一度送る")
    parser.add_argument("--address-only", action="store_true", help="このPCのサーバーを止めてアドレスを渡す手順だけ")
    args = parser.parse_args(argv)
    server = Server(args.host, args.user)
    try:
        check_ssh(server)
        if not (args.data_only or args.address_only):
            set_up(server)
            print(
                "\nサーバーの準備ができました。ここからこのPCを変えます:\n"
                "  ・News Site の毎時の収集を止め、記事・DB・設定・API キーをサーバーへ送る\n"
                "  ・このPCのサーバーと自動起動、Funnel を止め、"
                + ("サーバーをサーバー自身の名前で公開する" if args.new_address else "今の公開アドレスをサーバーへ渡す")
            )
            if input("続けますか？ [y/N]: ").strip().lower() not in ("y", "yes"):
                print("ここでやめました。続きは同じコマンドでいつでもできます。")
                return 0
        if not args.address_only:
            move_data(server)
        if not args.data_only:
            stop_pc_server()
            wait_for(hand_over_address(server, args.new_address))
    except Stop as stop:
        print(f"\n{stop}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nやめました。", file=sys.stderr)
        return 1
    print("\n移行しました。これからは GitHub に push すると1分以内にサーバーへ反映されます。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
