"""The server of this PC's sites: ``python -m homepage.server`` (launcher.py runs it and keeps it running).

It listens on one port (sites.toml ``[server]``): on this PC's Tailscale and LAN addresses and on
loopback, where Tailscale Funnel (or Caddy, setup.sh --direct) hands the public name's requests over
(``listen = "network"``), or on loopback only (``listen = "local"``). It serves the portal with the
folder sites and the Python sites of sites.toml, answers only to this PC's own names and the public
names, and marks requests under a public name (``*.ts.net``, and ``[server] public``: テスト公開)
https, with HSTS, kept out of search results and flagged for the sites (``homepage.visitor``), unless
they come from a device the owner signed in on (``/owner``, homepage.owner: ``homepage.owner``). With
``[server] moved_to`` set, page requests under the other public names are sent on to that one.

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
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, quote

from homepage import CONFIG, MOUNT, OWNER_KEY, PACKAGE, VISITOR_KEY, App, build, owner_page
from homepage.owner import Owner, without_cookie

RESTART_EXIT_CODE = 75
POLL_SECONDS = 15.0
#: Every this many polls (about a minute), look for a network address that came up.
NETWORK_POLL_ROUNDS = 4
THREADS = 16
#: How long a restart waits for the requests being answered.
DRAIN_SECONDS = 20.0
FUNNEL_SUFFIX = ".ts.net"
#: The login form's size at most.
FORM_BYTES = 4096
TAILSCALE = ipaddress.ip_network("100.64.0.0/10")
LOOPBACK = "127.0.0.1"


@dataclass
class Settings:
    port: int = 5000
    listen: str = "network"
    hosts: tuple = ()
    python_sites: list = field(default_factory=list)
    #: Public names this machine serves itself (setup.sh --direct: its DuckDNS name), besides Funnel's.
    public: tuple = ()
    #: The public name the sites live at now: page requests under the others are sent there.
    moved_to: str = ""


def _names(value) -> tuple:
    if not isinstance(value, list):
        return ()
    return tuple(dict.fromkeys(host_without_port(item) for item in value if isinstance(item, str) and item.strip()))


def valid_port(value) -> bool:
    """A TCP port sites.toml may name (``true`` is no number, though Python counts it as 1)."""
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 65535


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
    if not valid_port(port):
        print("[server] port は 1〜65535 の整数です。5000 で起動します。", flush=True)
        port = 5000
    if listen not in ("network", "local"):
        print('[server] listen は "network" か "local" です。"network" で起動します。', flush=True)
        listen = "network"
    hosts = _names(server.get("hosts", []))
    public = _names(server.get("public", []))
    moved_to = server.get("moved_to", "")
    moved_to = host_without_port(moved_to) if isinstance(moved_to, str) else ""
    if moved_to and moved_to not in public:
        print(f"[server] moved_to（{moved_to}）が public にありません。転送しません。", flush=True)
        moved_to = ""
    sites = data.get("site", [])
    python_sites = (
        [entry for entry in sites if isinstance(entry, dict) and "python" in entry] if isinstance(sites, list) else []
    )
    return Settings(port, listen, hosts, python_sites, public, moved_to)


def settings_stamp(config: Path = CONFIG) -> str | None:
    """What of sites.toml the running server depends on (``[server]`` and where the Python sites are),
    or None while the file cannot be read (a half-written file restarts nothing)."""
    try:
        data = tomllib.loads(config.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    sites = data.get("site") if isinstance(data.get("site"), list) else []
    picked = [
        data.get("server"),
        [
            [entry.get(key) for key in ("mount", "python", "entry")]
            for entry in sites
            if isinstance(entry, dict) and "python" in entry
        ],
    ]
    return hashlib.sha256(json.dumps(picked, default=str, sort_keys=True).encode()).hexdigest()


def code_stamp(package: Path = PACKAGE) -> tuple:
    """The Home Page code as it is now: its files' names, times and sizes."""

    def entry(file: Path) -> tuple:
        info = file.stat()
        return str(file.relative_to(package)), info.st_mtime_ns, info.st_size

    try:
        return tuple(sorted(entry(file) for file in package.rglob("*.py") if "__pycache__" not in file.parts))
    except OSError:
        return ()


# -- this PC's addresses and names ------------------------------------------------------------------


def tailscale() -> tuple[str | None, str | None]:
    """This PC's Tailscale IPv4 address and name (``haruxera.tail1234.ts.net``) right now, or None."""
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    candidates = [
        shutil.which("tailscale.exe"),
        shutil.which("tailscale"),
        os.path.join(program_files, "Tailscale", "tailscale.exe"),
    ]
    executable = next((item for item in candidates if item and os.path.isfile(item)), None)
    if executable:
        extra = {"creationflags": 0x08000000} if os.name == "nt" else {}  # CREATE_NO_WINDOW
        try:
            status = (
                json.loads(
                    subprocess.run(
                        [executable, "status", "--json"], capture_output=True, text=True, timeout=4, check=True, **extra
                    ).stdout
                ).get("Self")
                or {}
            )
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
        return raw[1 : raw.find("]")] if "]" in raw else raw
    if raw.count(":") == 1:
        raw = raw.split(":", 1)[0]
    return raw.rstrip(".")


class Hosts:
    """The names this server answers to: this PC's own (loopback, its addresses, its computer and
    Tailscale names, ``[server] hosts``), and the public names (``*.ts.net`` and ``public``, テスト公開).
    Only the own names are the owner's: they are what the sites are told to trust (``names``)."""

    def __init__(self, names, public=()):
        self.names = frozenset({"localhost", "127.0.0.1", "::1", *(name.lower() for name in names if name)})
        self.public = frozenset(host_without_port(name) for name in public if name) - self.names

    def allowed(self, host: str) -> bool:
        return host_without_port(host) in self.names or self.visitor(host)

    def visitor(self, host: str) -> bool:
        host = host_without_port(host)
        return host in self.public or host.endswith(FUNNEL_SUFFIX)


class Public:
    """WSGI around everything: requests under a public name came through a TLS proxy (Funnel or Caddy),
    so they are https (share previews need absolute https URLs), the sites are told they are a visitor's
    (``VISITOR_KEY``), and their answers say: https only from now on, and no search-engine listing (a
    test, for the people sent the link).

    ``moved_to`` (``[server] moved_to``): the public name the sites live at now. A page asked for under
    another public name (the old Funnel address in links people have) is sent there, the same path;
    other methods are answered where they are (the relay's clients would not follow with their token).
    The redirect is temporary (307), so going back to the old name needs no cache to expire.

    ``owner`` (homepage.owner.Owner): a request with the owner's cookie is the owner's (``OWNER_KEY``),
    with everything, as on the owner's own names; ``/owner`` is where a device signs in and out.
    The cookie is taken off the requests the sites get: they need only the flag."""

    HEADERS = (("Strict-Transport-Security", "max-age=31536000"), ("X-Robots-Tag", "noindex"))

    def __init__(self, app, visitor, moved_to: str = "", owner: Owner | None = None):
        self.app, self.visitor, self.moved_to = app, visitor, host_without_port(moved_to)
        self.owner = owner

    def __call__(self, environ, start_response):
        host = environ.get("HTTP_HOST", "")
        if not self.visitor(host):
            return self.app(environ, start_response)
        if (
            self.moved_to
            and host_without_port(host) != self.moved_to
            and environ.get("REQUEST_METHOD", "GET") in ("GET", "HEAD")
        ):
            path = quote(environ.get("SCRIPT_NAME", "") + environ.get("PATH_INFO", ""), safe="/;=,", encoding="latin-1")
            query = environ.get("QUERY_STRING", "")
            location = f"https://{self.moved_to}{path or '/'}" + (f"?{query}" if query else "")
            start_response(
                "307 Temporary Redirect",
                [("Location", location), ("Content-Length", "0"), ("Cache-Control", "no-store"), *self.HEADERS],
            )
            return [b""]

        def start(status, headers, exc_info=None):
            return start_response(status, [*headers, *self.HEADERS], exc_info)

        signed_in = self.owner is not None and self.owner.signed_in(environ)
        if environ.get("SCRIPT_NAME", "") + environ.get("PATH_INFO", "") == "/owner":
            return self._sign_in(dict(environ, **{"wsgi.url_scheme": "https"}), start, signed_in)
        environ = dict(environ, **{"wsgi.url_scheme": "https", VISITOR_KEY: not signed_in, OWNER_KEY: signed_in})
        if "HTTP_COOKIE" in environ:
            environ["HTTP_COOKIE"] = without_cookie(environ["HTTP_COOKIE"])
        return self.app(environ, start)

    def _sign_in(self, environ, start_response, signed_in: bool):
        """``/owner``: the login page (GET), a password or a sign-out sent from it (POST)."""
        owner = self.owner if self.owner is not None and self.owner.ready else None
        state = "in" if signed_in else "form" if owner else "off"
        method = environ.get("REQUEST_METHOD", "GET")
        if method in ("GET", "HEAD"):
            return owner_page(environ, start_response, state)
        if method != "POST":
            return _answer(start_response, "405 Method Not Allowed", [("Allow", "GET, HEAD, POST")])
        # Only this page may send it (a page elsewhere cannot sign a device in or out).
        origin = environ.get("HTTP_ORIGIN")
        if environ.get("HTTP_SEC_FETCH_SITE", "same-origin") not in ("same-origin", "none") or (
            origin is not None and origin != f"https://{environ.get('HTTP_HOST', '')}"
        ):
            return _answer(start_response, "403 Forbidden")
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= FORM_BYTES:
            return _answer(start_response, "413 Content Too Large")
        form = parse_qs(environ["wsgi.input"].read(length).decode("utf-8", "replace")) if length else {}
        if form.get("do") == ["logout"]:
            return _answer(start_response, "303 See Other", [("Location", "/owner"), Owner.forget()])
        if owner is None:
            return owner_page(environ, start_response, "off", "off")
        result = owner.login((form.get("password") or [""])[0])
        if result != "ok":
            return owner_page(environ, start_response, "form", result)
        return _answer(start_response, "303 See Other", [("Location", "/"), owner.cookie()])


def _answer(start_response, status: str, headers=()):
    start_response(status, [("Content-Length", "0"), ("Cache-Control", "no-store"), *headers])
    return [b""]


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
        except Exception as exc:  # one broken site never keeps the others down
            note = f"{mount} を読み込めませんでした（{exc}）。直したらサーバーを再起動してください。"
            print(note, flush=True)
            notes.append(note)
            continue
        legacy = made.get("legacy")
        apps.append(
            App(
                mount,
                mount,
                made["app"],
                str(made.get("name") or entry.get("name") or mount.strip("/")),
                str(made.get("subtitle") or ""),
                str(made.get("description") or ""),
                preview=made.get("preview"),
                disallow=tuple(made.get("disallow") or ()),
                legacy=tuple(legacy) if legacy is not None else None,
                version=made.get("version"),
                folder=folder,
            )
        )
    return apps, notes


def _factory(target: str):
    module_name, _, name = target.partition(":")
    return getattr(importlib.import_module(module_name), name)


def _version(app: App) -> str:
    try:
        return str(app.version() or "") if app.version else ""
    except Exception:  # a broken version() is no new version
        return ""


# -- serving --------------------------------------------------------------------------------------------


def _bindable(host: str, port: int) -> bool:
    """Whether waitress could listen there. Like waitress, ignore connections the last run closed
    (TIME_WAIT, a minute on Linux): without SO_REUSEADDR every restart failed "port in use" for that
    minute and the sites were down (2026-11-28). Not on Windows, where it would let us share a live port."""
    family = socket.AF_INET6 if ipaddress.ip_address(host).version == 6 else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            if os.name != "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((host, port))
        return True
    except OSError:
        return False


def _listen_spec(hosts: list[str], port: int) -> str:
    return " ".join(f"[{h}]:{port}" if ipaddress.ip_address(h).version == 6 else f"{h}:{port}" for h in hosts)


def serve(
    app,
    hosts: list[str],
    port: int,
    *,
    supervised: bool,
    reason=None,
    poll_seconds: float = POLL_SECONDS,
    drain_seconds: float = DRAIN_SECONDS,
) -> int:
    """Serve until stopped (0) or, supervised, until ``reason(round)`` names a reason to restart (75).

    A restart first stops taking connections, lets the requests being answered finish (at most
    ``drain_seconds``), then closes the rest (idle keep-alive connections: Caddy and Funnel open new
    ones) and returns. Each listener's trigger, which a finished request pulls to have its answer
    sent, stays open until then: waitress's own listener close() shuts it too, and the answers in
    flight were never sent (Errno 9), so the old server kept its connections, and the port stayed
    closed, until every client gave up (9 minutes on 2026-11-03)."""
    from waitress import wasyncore
    from waitress.channel import HTTPChannel
    from waitress.server import BaseWSGIServer, create_server

    if not _bindable(LOOPBACK, port) and LOOPBACK in hosts:
        raise OSError(f"ポート {port} はこのPCでほかのプログラムが使っています（もう起動していませんか）。")
    hosts = [item for item in hosts if item == LOOPBACK or _bindable(item, port)]
    server = create_server(app, listen=_listen_spec(hosts, port), threads=THREADS, ident="HomePage")
    single = isinstance(server, BaseWSGIServer)
    everything = server._map if single else server.map  # listeners, their triggers, the connections
    listeners = (
        [server]
        if single
        else list({id(item): item for item in everything.values() if isinstance(item, BaseWSGIServer)}.values())
    )
    restarting = threading.Event()

    def stop_taking() -> None:  # on the loop thread, like every change to the connections
        for listener in listeners:
            wasyncore.dispatcher.close(listener)  # the socket only: not BaseWSGIServer.close(), which shuts the trigger

    def busy() -> bool:
        return any(
            item.requests or item.total_outbufs_len
            for item in list(everything.values())
            if isinstance(item, HTTPChannel)
        )

    def finish() -> None:  # on the loop thread: an empty map ends the loop
        wasyncore.close_all(everything)

    def watch() -> None:
        rounds = 0
        while not restarting.wait(poll_seconds):
            rounds += 1
            why = reason(rounds) if reason else None
            if why:
                print(f"{why}。処理中の要求を終えてから再起動します。", flush=True)
                restarting.set()
                listeners[0].trigger.pull_trigger(stop_taking)
                until = time.monotonic() + drain_seconds
                while time.monotonic() < until and busy():
                    time.sleep(0.05)
                listeners[0].trigger.pull_trigger(finish)
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
    names = Hosts([*hosts, found[1], socket.gethostname(), *settings.hosts], settings.public)
    host = {
        "port": settings.port,
        "addresses": hosts,
        "names": sorted(names.names),
        "urls": [f"http://{item}:{settings.port}/" for item in hosts],
    }
    apps, notes = load_python_sites(settings.python_sites, config.parent, host)
    portal = build(apps, allowed_hosts=names.allowed, visitor_hosts=names.visitor, config=config, notes=notes)
    portal.warm()
    started = {"code": code_stamp(), "settings": settings_stamp(config), **{app.mount: _version(app) for app in apps}}

    def changed() -> str | None:
        """Why the code that runs is not the code there is now, or None."""
        if code_stamp() != started["code"]:
            return "Home Page のコードが変わりました"
        stamp = settings_stamp(config)
        if not (args.port or args.local) and stamp is not None and stamp != started["settings"]:
            return "sites.toml のサーバー設定か Python サイトの指定が変わりました"
        for app in apps:
            now = _version(app)
            if now and now != started[app.mount]:
                return f"{app.name} が更新されました（{now}）"
        return None

    portal.restart_pending = lambda: changed() is not None

    def reason(rounds: int) -> str | None:
        why = changed()
        if why:
            return why
        if settings.listen == "network" and rounds % NETWORK_POLL_ROUNDS == 0:
            new = next(
                (item for item in addresses(settings) if item not in hosts and _bindable(item, settings.port)), None
            )
            if new:
                return f"新しいアドレス {new} が使えるようになりました"
        return None

    try:
        return serve(
            Public(portal, names.visitor, settings.moved_to, Owner()),
            hosts,
            settings.port,
            supervised=os.environ.get("HOME_SUPERVISED") == "1",
            reason=reason,
        )
    except OSError as exc:
        print(f"起動できませんでした: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
