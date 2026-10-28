"""The server of this PC's sites: ``python -m homepage.server`` (launcher.py runs it and keeps it running).

It listens on one port (sites.toml ``[server]``): on this PC's Tailscale and LAN addresses and on
loopback, where Tailscale Funnel hands the public name's requests over (``listen = "network"``), or
on loopback only (``listen = "local"``). It serves the portal with the folder sites and the Python
sites of sites.toml, answers only to this PC's own names, and marks requests under the public name
(``*.ts.net``, テスト公開) https, with HSTS and kept out of search results.

A Python site is a folder put on ``sys.path`` and a factory named by ``entry`` ("module:function"),
called once at the start as ``factory(mount=..., host={...})``; it returns a dict with ``app`` (WSGI)
and optionally name, subtitle, description, preview, disallow, legacy and version (see homepage.App).

Supervised (``HOME_SUPERVISED=1``, set by launcher.py) the server restarts itself (exit code 75, after
answering the requests in flight) when what it loaded changed: the Home Page code, the ``[server]``
settings or the Python sites in sites.toml, a Python site's version (News Site writes its VERSION file
when it is deployed), or a network address that came up after the start.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import ipaddress
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from homepage import CONFIG, MOUNT, PACKAGE, App, build

RESTART_EXIT_CODE = 75
POLL_SECONDS = 15.0
#: Every this many polls (about a minute), look for a network address that came up.
NETWORK_POLL_ROUNDS = 4
THREADS = 16
FUNNEL_SUFFIX = ".ts.net"
TAILSCALE = ipaddress.ip_network("100.64.0.0/10")
LOOPBACK = "127.0.0.1"


@dataclass
class Settings:
    port: int = 5000
    listen: str = "network"
    hosts: tuple = ()
    python_sites: list = field(default_factory=list)


def read_settings(config: Path = CONFIG) -> Settings:
    """sites.toml's ``[server]`` and its Python sites (read at the start; a change restarts the server)."""
    try:
        data = tomllib.loads(config.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        print(f"sites.toml を読めませんでした（{exc}）。既定の設定で起動します。", flush=True)
        return Settings()
    server = data.get("server", {}) if isinstance(data.get("server"), dict) else {}
    port = server.get("port", 5000)
    listen = server.get("listen", "network")
    hosts = server.get("hosts", [])
    if not isinstance(port, int) or not 1 <= port <= 65535:
        print("[server] port は 1〜65535 の整数です。5000 で起動します。", flush=True)
        port = 5000
    if listen not in ("network", "local"):
        print('[server] listen は "network" か "local" です。"network" で起動します。', flush=True)
        listen = "network"
    hosts = tuple(item.strip().lower().rstrip(".") for item in hosts if isinstance(item, str) and item.strip()) \
        if isinstance(hosts, list) else ()
    sites = data.get("site", [])
    python_sites = [entry for entry in sites if isinstance(entry, dict) and "python" in entry] if isinstance(sites, list) else []
    return Settings(port, listen, hosts, python_sites)


def settings_stamp(config: Path = CONFIG) -> str | None:
    """What of sites.toml the running server depends on (``[server]`` and where the Python sites are),
    or None while the file cannot be read (a half-written file restarts nothing)."""
    try:
        data = tomllib.loads(config.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    sites = data.get("site") if isinstance(data.get("site"), list) else []
    picked = [data.get("server"), [[entry.get(key) for key in ("mount", "python", "entry")]
                                   for entry in sites if isinstance(entry, dict) and "python" in entry]]
    return hashlib.sha256(json.dumps(picked, default=str, sort_keys=True).encode()).hexdigest()


def code_stamp(package: Path = PACKAGE) -> tuple:
    """The Home Page code as it is now: its files' names, times and sizes."""
    try:
        return tuple(sorted((str(file.relative_to(package)), file.stat().st_mtime_ns, file.stat().st_size)
                            for file in package.rglob("*.py") if "__pycache__" not in file.parts))
    except OSError:
        return ()


# -- this PC's addresses and names ------------------------------------------------------------------

def tailscale() -> tuple[str | None, str | None]:
    """This PC's Tailscale IPv4 address and name (``haruxera.tail1234.ts.net``) right now, or None."""
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    candidates = [shutil.which("tailscale.exe"), shutil.which("tailscale"),
                  os.path.join(program_files, "Tailscale", "tailscale.exe")]
    executable = next((item for item in candidates if item and os.path.isfile(item)), None)
    if executable:
        extra = {"creationflags": 0x08000000} if os.name == "nt" else {}  # CREATE_NO_WINDOW
        try:
            status = json.loads(subprocess.run([executable, "status", "--json"], capture_output=True, text=True,
                                               timeout=4, check=True, **extra).stdout).get("Self") or {}
            address = next((item for item in status.get("TailscaleIPs") or [] if _tailscale_ip(item)), None)
            if address:
                return address, (str(status.get("DNSName") or "").rstrip(".").lower() or None)
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
            pass
    try:
        for result in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            if _tailscale_ip(result[4][0]):
                return result[4][0], None
    except OSError:
        pass
    return None, None


def _tailscale_ip(value: object) -> bool:
    try:
        address = ipaddress.ip_address(str(value))
    except ValueError:
        return False
    return address.version == 4 and address in TAILSCALE


def lan_address() -> str | None:
    """This PC's private LAN IPv4 address right now (the one Windows would route out of), or None."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))  # no packet is sent: this only asks the routing table
            address = ipaddress.ip_address(probe.getsockname()[0])
    except (OSError, ValueError):
        return None
    if address.is_private and not address.is_loopback and address not in TAILSCALE:
        return str(address)
    return None


def addresses(settings: Settings, found=None) -> list[str]:
    """Where to listen: loopback first, then Tailscale's and the LAN's address (``listen = "network"``)."""
    if settings.listen == "local":
        return [LOOPBACK]
    ts_address = (found or tailscale())[0]
    return list(dict.fromkeys(item for item in (LOOPBACK, ts_address, lan_address()) if item))


def host_without_port(raw: str) -> str:
    """``example:5000`` -> ``example``; ``[::1]:5000`` and ``[::1]`` -> ``::1``."""
    raw = raw.strip().lower()
    if raw.startswith("["):
        return raw[1:raw.find("]")] if "]" in raw else raw
    if raw.count(":") == 1:
        raw = raw.split(":", 1)[0]
    return raw.rstrip(".")


class Hosts:
    """The names this server answers to: this PC's own (loopback, its addresses, its computer and
    Tailscale names, ``[server] hosts``), and the public name (``*.ts.net``, テスト公開)."""

    def __init__(self, names):
        self.names = frozenset({"localhost", "127.0.0.1", "::1", *(name.lower() for name in names if name)})

    def allowed(self, host: str) -> bool:
        host = host_without_port(host)
        return host in self.names or host.endswith(FUNNEL_SUFFIX)

    @staticmethod
    def visitor(host: str) -> bool:
        return host_without_port(host).endswith(FUNNEL_SUFFIX)


class Public:
    """WSGI around everything: requests under the public name came through a TLS proxy (Funnel), so they
    are https (share previews need absolute https URLs), and their answers say: https only from now on,
    and no search-engine listing (a test, for the people sent the link)."""

    def __init__(self, app, visitor):
        self.app, self.visitor = app, visitor

    def __call__(self, environ, start_response):
        if not self.visitor(environ.get("HTTP_HOST", "")):
            return self.app(environ, start_response)

        def start(status, headers, exc_info=None):
            return start_response(status, [*headers, ("Strict-Transport-Security", "max-age=31536000"),
                                           ("X-Robots-Tag", "noindex")], exc_info)
        return self.app(dict(environ, **{"wsgi.url_scheme": "https"}), start)


# -- Python sites --------------------------------------------------------------------------------------

def load_python_sites(entries: list, base: Path, host: dict) -> tuple[list[App], list[str]]:
    """Each ``python = ...`` site of sites.toml, as an App (or a note for the owner on why it is missing)."""
    apps: list[App] = []
    notes: list[str] = []
    for entry in entries:
        mount = str(entry.get("mount", ""))
        folder = (base / str(entry.get("python", ""))).resolve()
        target = str(entry.get("entry", ""))
        try:
            if not MOUNT.fullmatch(mount):
                raise ValueError("mount は /news のような、/ と英小文字・数字・ハイフンの名前です")
            if not folder.is_dir():
                raise ValueError(f"フォルダ {folder} がありません")
            if ":" not in target:
                raise ValueError('entry は "モジュール:関数" の形です')
            if str(folder) not in sys.path:
                sys.path.insert(0, str(folder))
            made = _factory(target)(mount=mount, host=host)
            if not isinstance(made, dict) or not callable(made.get("app")):
                raise ValueError(f"{target} が app を返しませんでした")
        except Exception as exc:  # noqa: BLE001 - one broken site never keeps the others down
            note = f"{mount} を読み込めませんでした（{exc}）。直したらサーバーを再起動してください。"
            print(note, flush=True)
            notes.append(note)
            continue
        legacy = made.get("legacy")
        apps.append(App(mount, mount, made["app"], str(made.get("name") or entry.get("name") or mount.strip("/")),
                        str(made.get("subtitle") or ""), str(made.get("description") or ""),
                        preview=made.get("preview"), disallow=tuple(made.get("disallow") or ()),
                        legacy=tuple(legacy) if legacy is not None else None, version=made.get("version")))
    return apps, notes


def _factory(target: str):
    module_name, _, name = target.partition(":")
    return getattr(importlib.import_module(module_name), name)


def _version(app: App) -> str:
    try:
        return str(app.version() or "") if app.version else ""
    except Exception:  # noqa: BLE001
        return ""


# -- serving --------------------------------------------------------------------------------------------

def _bindable(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ipaddress.ip_address(host).version == 6 else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            probe.bind((host, port))
        return True
    except OSError:
        return False


def _listen_spec(hosts: list[str], port: int) -> str:
    return " ".join(f"[{h}]:{port}" if ipaddress.ip_address(h).version == 6 else f"{h}:{port}" for h in hosts)


def serve(app, hosts: list[str], port: int, *, supervised: bool, reason=None, poll_seconds: float = POLL_SECONDS) -> int:
    """Serve until stopped (0) or, supervised, until ``reason(round)`` names a reason to restart (75)."""
    from waitress.server import BaseWSGIServer, create_server

    if not _bindable(LOOPBACK, port) and LOOPBACK in hosts:
        raise OSError(f"ポート {port} はこのPCでほかのプログラムが使っています（もう起動していませんか）。")
    hosts = [item for item in hosts if item == LOOPBACK or _bindable(item, port)]
    server = create_server(app, listen=_listen_spec(hosts, port), threads=THREADS, ident="HomePage")
    listeners = [server] if isinstance(server, BaseWSGIServer) else list(
        {id(item): item for item in server.map.values() if isinstance(item, BaseWSGIServer)}.values())
    restarting = threading.Event()

    def close_listeners() -> None:
        for listener in listeners:
            listener.close()

    def watch() -> None:
        rounds = 0
        while not restarting.wait(poll_seconds):
            rounds += 1
            why = reason(rounds) if reason else None
            if why:
                print(f"{why}。処理中の要求を終えてから再起動します。", flush=True)
                restarting.set()
                # close() must run on the server's own loop thread; the loop then ends once the
                # connections still open have been answered.
                listeners[0].trigger.pull_trigger(close_listeners)
                return

    if supervised:
        threading.Thread(target=watch, name="restart-watch", daemon=True).start()
    for where in _listen_spec(hosts, port).split():
        print(f"サイト一覧: http://{where}/ （終了は Ctrl+C）", flush=True)
    try:
        server.run()
    except KeyboardInterrupt:
        return 0
    finally:
        server.task_dispatcher.shutdown()
    return RESTART_EXIT_CODE if restarting.is_set() else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m homepage.server")
    parser.add_argument("--config", type=Path, default=CONFIG, help="sites.toml の場所")
    parser.add_argument("--port", type=int, help="[server] port の代わり")
    parser.add_argument("--local", action="store_true", help="このPC（127.0.0.1）だけで待ち受ける")
    args = parser.parse_args(argv)
    config = args.config.resolve()
    settings = read_settings(config)
    if args.port:
        settings.port = args.port
    if args.local:
        settings.listen = "local"
    found = tailscale() if settings.listen == "network" else (None, None)
    hosts = addresses(settings, found)
    names = Hosts([*hosts, found[1], socket.gethostname(), *settings.hosts])
    host = {"port": settings.port, "addresses": hosts, "names": sorted(names.names),
            "urls": [f"http://{item}:{settings.port}/" for item in hosts]}
    apps, notes = load_python_sites(settings.python_sites, config.parent, host)
    portal = build(apps, allowed_hosts=names.allowed, visitor_hosts=names.visitor, config=config, notes=notes)
    portal.warm()
    started = {"code": code_stamp(), "settings": settings_stamp(config), **{app.mount: _version(app) for app in apps}}

    def reason(rounds: int) -> str | None:
        if code_stamp() != started["code"]:
            return "Home Page のコードが変わりました"
        stamp = settings_stamp(config)
        if not (args.port or args.local) and stamp is not None and stamp != started["settings"]:
            return "sites.toml のサーバー設定か Python サイトの指定が変わりました"
        for app in apps:
            now = _version(app)
            if now and now != started[app.mount]:
                return f"{app.name} が更新されました（{now}）"
        if settings.listen == "network" and rounds % NETWORK_POLL_ROUNDS == 0:
            new = next((item for item in addresses(settings) if item not in hosts and _bindable(item, settings.port)), None)
            if new:
                return f"新しいアドレス {new} が使えるようになりました"
        return None

    try:
        return serve(Public(portal, names.visitor), hosts, settings.port,
                     supervised=os.environ.get("HOME_SUPERVISED") == "1", reason=reason)
    except OSError as exc:
        print(f"起動できませんでした: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
