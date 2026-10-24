"""Home Page: the front page of this PC's sites. "/" lists them; each site lives under its own path.

What the page lists comes from ``sites.toml`` in the Home Page folder. Edits to it, and to the
page's HTML, CSS and icons, show on the next request, without restarting the server.

A site is either a folder of static files (``folder = ...`` in sites.toml, served by ``StaticFiles``)
or a WSGI app the server provides by name (``app = "news"``). News Site's server builds the whole
thing with ``build(apps=[App(...)], ...)`` and serves it at its address; ``python -m homepage``
serves the folder sites alone, for trying out a change.
"""
from __future__ import annotations

import html
import re
import threading
import time
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

#: The contract with the server that loads this package (News Site's newsreader/portal): ``build`` and ``App``.
API = 1
PACKAGE = Path(__file__).resolve().parent
HOME = PACKAGE.parent
CONFIG = HOME / "sites.toml"
JST = timezone(timedelta(hours=9))
MOUNT = re.compile(r"/[a-z0-9][a-z0-9-]*")
WORD = re.compile(r"[a-z0-9-]+")
ACCENTS = ("red", "blue", "teal", "green", "amber", "purple", "gray")
#: The portal's own addresses: no site may be mounted over them.
OWN = ("/", "/portal.css", "/favicon.svg", "/robots.txt")
#: How often sites.toml is looked at (it is re-read only when it changed).
CHECK_SECONDS = 1.0


@dataclass
class App:
    """A site the server provides: the WSGI ``app`` at ``mount``, listed with these texts unless
    sites.toml says otherwise. ``preview()`` returns what the site has now:
    ``{"title": str, "note": str, "items": [(text, path relative to the site)]}`` (title: the heading
    over the items, "新着" when left out; note: how fresh they are). ``disallow``: paths under the
    mount crawlers should not call. ``legacy``: this site also answers the addresses it had before
    the portal: unknown GET paths are redirected under its mount, paths starting with one of these
    prefixes (and requests that are not GET/HEAD) go to it unchanged."""
    key: str
    mount: str
    app: object
    name: str
    subtitle: str = ""
    description: str = ""
    preview: object = None
    disallow: tuple = ()
    legacy: tuple | None = None


@dataclass
class Site:
    """One entry of the list, as sites.toml (and the server's App) define it."""
    mount: str
    name: str
    app: object
    subtitle: str = ""
    description: str = ""
    icon: str = ""
    accent: str = "gray"
    tags: tuple = ()
    open_label: str = ""
    listed: bool = True
    public: bool = True
    preview: object = None
    files: "StaticFiles | None" = None

    def now(self) -> dict:
        """The site's preview, or {} when it has none or it failed (the index never fails because of it)."""
        try:
            return (self.preview() if self.preview else None) or {}
        except Exception:  # noqa: BLE001
            return {}

    def updated(self) -> datetime | None:
        return self.files.newest() if self.files else None


class Portal:
    """WSGI: "/" is the index, ``/<site>/...`` goes to that site."""

    def __init__(self, apps=(), allowed_hosts=None, visitor_hosts=None, config: Path = CONFIG):
        self.apps = {item.key: item for item in apps}
        #: callable(host) -> bool for the portal's own pages and the folder sites, or None for any.
        self.allowed_hosts = allowed_hosts
        #: callable(host) -> bool: names the public reaches (テスト公開). Visitors see neither the
        #: owner's notes nor the sites marked ``public = false``.
        self.visitor_hosts = visitor_hosts
        self.config = Path(config)
        self._lock = threading.Lock()
        self._checked = 0.0
        self._stamp: tuple | None = None  # None: not read yet
        self.settings: dict = {}
        self.sites: list[Site] = []
        self.problems: list[str] = []
        self.refresh()

    # -- sites.toml ---------------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-read sites.toml when it changed. A broken file keeps the last good list (the owner sees why)."""
        now = time.monotonic()
        if self._stamp is not None and now - self._checked < CHECK_SECONDS:
            return
        with self._lock:
            self._checked = now
            stamp = _stamp(self.config)
            if stamp == self._stamp:
                return
            first = self._stamp is None
            self._stamp = stamp
            try:
                data = tomllib.loads(self.config.read_text(encoding="utf-8")) if stamp else {}
            except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
                self.problems = [f"sites.toml を読めませんでした（{exc}）。直すまでは前の内容で表示しています。"]
                if first:
                    self.settings, self.sites = {}, self._sites({})[0]
                return
            self.settings = data
            self.sites, self.problems = self._sites(data)
            if not stamp:
                self.problems.insert(0, f"{self.config} がありません。サーバーが用意するサイトだけを表示しています。")

    def _sites(self, data: dict) -> tuple[list[Site], list[str]]:
        sites: list[Site] = []
        problems: list[str] = []
        used: set[str] = set()
        entries = data.get("site", [])
        if not isinstance(entries, list):
            entries, problems = [], ["[[site]] の書き方が違います。"]
        for number, entry in enumerate(entries, 1):
            try:
                site = self._site(entry)
            except ValueError as exc:
                problems.append(f"{number} 番目のサイト: {exc}")
                continue
            if site is None:
                continue
            if site.mount in used or site.mount in OWN or any(site.mount.startswith(m + "/") for m in used):
                problems.append(f"{number} 番目のサイト: {site.mount} はほかと重なっています。")
                continue
            used.add(site.mount)
            sites.append(site)
        for item in self.apps.values():  # an app sites.toml does not mention is still served (and listed)
            if item.mount not in used:
                used.add(item.mount)
                sites.append(Site(item.mount, item.name, item.app, item.subtitle, item.description,
                                  preview=item.preview))
        return sites, problems

    def _site(self, entry) -> Site | None:
        if not isinstance(entry, dict):
            raise ValueError("書き方が違います。")
        text = {key: _text(entry, key) for key in ("name", "subtitle", "description", "icon", "open")}
        accent = _text(entry, "accent") or "gray"
        if accent not in ACCENTS:
            raise ValueError(f"accent は {' / '.join(ACCENTS)} のどれかです。")
        if text["icon"] and not WORD.fullmatch(text["icon"]):
            raise ValueError("icon は icons フォルダのファイル名（拡張子なし）です。")
        tags = entry.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ValueError("tags は文字列の並び（[\"…\", \"…\"]）です。")
        common = dict(icon=text["icon"], accent=accent, tags=tuple(tags), open_label=text["open"],
                      listed=_flag(entry, "listed"), public=_flag(entry, "public"))
        if "app" in entry:
            item = self.apps.get(_text(entry, "app"))
            if item is None:  # this server does not provide it (Home Page run on its own)
                return None
            return Site(item.mount, text["name"] or item.name, item.app, text["subtitle"] or item.subtitle,
                        text["description"] or item.description, preview=item.preview, **common)
        mount, folder = _text(entry, "mount"), _text(entry, "folder")
        if not MOUNT.fullmatch(mount):
            raise ValueError("mount は /infra のような、/ と英小文字・数字・ハイフンの名前です。")
        if not folder:
            raise ValueError("folder（配信するフォルダ）か app がありません。")
        if mount in {item.mount for item in self.apps.values()}:
            raise ValueError(f"{mount} はサーバーが用意するサイトが使っています。")
        if not text["name"]:
            raise ValueError("name（表示名）がありません。")
        root = (self.config.parent / folder).resolve()
        if not (root / "index.html").is_file():
            raise ValueError(f"{root} に index.html がありません（このPCにないサイトは表示しません）。")
        files = StaticFiles(root, self.allowed_hosts, home_link=_text(entry, "home_link") != "own")
        return Site(mount, text["name"], files, text["subtitle"], text["description"], files=files, **common)

    # -- requests -----------------------------------------------------------------------------

    def __call__(self, environ, start_response):
        self.refresh()
        path = environ.get("PATH_INFO", "") or "/"
        method = environ.get("REQUEST_METHOD", "GET")
        visitor = self._visitor(environ)
        for site in self.sites:
            if path == site.mount or path.startswith(site.mount + "/"):
                if visitor and not site.public:
                    return _plain(start_response, "404 Not Found", b"Not Found")
                if path == site.mount:
                    return _redirect(start_response, environ.get("SCRIPT_NAME", "") + site.mount + "/", environ)
                outer = environ.get("SCRIPT_NAME", "")
                environ = dict(environ, SCRIPT_NAME=outer + site.mount, PATH_INFO=path[len(site.mount):],
                               **{"homepage.home": outer + "/"})
                return site.app(environ, start_response)
        if path in OWN:
            if self.allowed_hosts is not None and not self.allowed_hosts(environ.get("HTTP_HOST", "")):
                return _plain(start_response, "400 Bad Request", b"Bad Request")
            if method not in ("GET", "HEAD"):
                return _plain(start_response, "405 Method Not Allowed", b"Method Not Allowed")
            if path == "/portal.css":
                return _send(start_response, "text/css; charset=utf-8", _read(PACKAGE / "portal.css"), "public, max-age=86400")
            if path == "/favicon.svg":
                return _send(start_response, "image/svg+xml", _read(PACKAGE / "favicon.svg"), "public, max-age=86400")
            if path == "/robots.txt":
                return _send(start_response, "text/plain; charset=utf-8", self.robots().encode(), "public, max-age=86400")
            body = self.index(environ, visitor).encode("utf-8")
            return _send(start_response, "text/html; charset=utf-8", body, "no-cache")
        legacy = next((item for item in self.apps.values() if item.legacy is not None), None)
        if legacy is not None:
            if path.startswith(legacy.legacy) or method not in ("GET", "HEAD"):
                return legacy.app(environ, start_response)
            return _redirect(start_response, legacy.mount + path, environ, permanent=True)
        return _plain(start_response, "404 Not Found", b"Not Found")

    def _visitor(self, environ) -> bool:
        return self.visitor_hosts is not None and bool(self.visitor_hosts(environ.get("HTTP_HOST", "")))

    def robots(self) -> str:
        """Crawlers may read pages (link previews come from them) but not call the sites' APIs."""
        paths = [item.mount + part for item in self.apps.values() for part in item.disallow]
        paths += [part for item in self.apps.values() for part in (item.legacy or ())]
        return "User-agent: *\n" + "".join(f"Disallow: {part}\n" for part in dict.fromkeys(paths))

    # -- the page -----------------------------------------------------------------------------

    def index(self, environ, visitor: bool) -> str:
        shown = [site for site in self.sites if site.listed and (site.public or not visitor)]
        settings = self.settings
        title = _setting(settings, "title", "サイト一覧")
        lead = _setting(settings, "lead", "")
        points = settings.get("points", [])
        points = [p for p in points if isinstance(p, str)] if isinstance(points, list) else []
        about = _setting(settings, "about", "")
        today = datetime.now(JST)
        scheme = environ.get("wsgi.url_scheme", "http")
        host = environ.get("HTTP_HOST", "") or environ.get("SERVER_NAME", "")
        home = environ.get("SCRIPT_NAME", "") + "/"
        e = html.escape
        values = {
            "title": e(title),
            "description": e(lead or title),
            "url": e(f"{scheme}://{host}{quote(home)}") if host else "",
            "css": e(f"{home}portal.css?v={_version(PACKAGE / 'portal.css')}"),
            "icon": e(f"{home}favicon.svg"),
            "date": f"{today.year}年{today.month}月{today.day}日（{'月火水木金土日'[today.weekday()]}）",
            "lead": f'<p class="lead">{e(lead)}</p>' if lead else "",
            "points": ('<ul class="points">' + "".join(f"<li>{e(p)}</li>" for p in points) + "</ul>") if points else "",
            "sites": "\n".join(self._card(site, n, visitor) for n, site in enumerate(shown, 1)),
            "count": str(len(shown)),
            "about": f"<p>{e(about)}</p>" if about else "",
            "owner": "" if visitor else self._owner_note(),
        }
        page = _read(PACKAGE / "page.html").decode("utf-8")
        return re.sub(r"\{\{ (\w+) \}\}", lambda m: values.get(m.group(1), ""), page)

    def _card(self, site: Site, number: int, visitor: bool) -> str:
        e = html.escape
        href = e(site.mount + "/")
        sub = f'<p class="sub">{e(site.subtitle)}</p>' if site.subtitle else ""
        description = f'<p class="desc">{e(site.description)}</p>' if site.description else ""
        chips = list(site.tags) + ([] if site.public or visitor else ["非公開（このPCからだけ）"])
        tags = ('<ul class="tags" aria-label="特徴">' + "".join(f"<li>{e(t)}</li>" for t in chips) + "</ul>") if chips else ""
        now = site.now()
        items = "".join(f'<li><a href="{e(site.mount + path)}">{e(text)}</a></li>' for text, path in now.get("items", []))
        note = now.get("note", "")
        updated = site.updated()
        if not note and updated:
            note = f"更新 {updated.month}月{updated.day}日"
        heading = now.get("title") or "新着"
        preview = (f'<div class="now"><p class="now-head">{e(heading)}'
                   f'{f"<span>{e(note)}</span>" if note else ""}</p><ul>{items}</ul></div>') if items else ""
        status = f'<span class="status">{e(note)}</span>' if note and not items else ""
        label = site.open_label or f"{site.name} を開く"
        return (f'<li class="site accent-{site.accent}">\n<div class="site-head">{self._icon(site)}'
                f'<div class="site-name"><h2><a href="{href}">{e(site.name)}</a></h2>{sub}</div>'
                f'<span class="no" aria-hidden="true">{number:02d}</span></div>\n'
                f'{description}{tags}{preview}\n'
                f'<p class="go"><a class="open" href="{href}">{e(label)}<span class="arrow" aria-hidden="true">→</span></a>{status}</p>\n</li>')

    @staticmethod
    def _icon(site: Site) -> str:
        svg = _icon_svg(site.icon) if site.icon else ""
        inner = svg or f'<span class="letter">{html.escape(site.name[:1].upper())}</span>'
        return f'<span class="icon" aria-hidden="true">{inner}</span>'

    def _owner_note(self) -> str:
        """For the owner only (not the public name): how to add a site, and what in sites.toml is wrong."""
        e = html.escape
        problems = "".join(f"<li>{e(p)}</li>" for p in self.problems)
        problems = f'<ul class="problems" role="status">{problems}</ul>' if problems else ""
        return (f'<aside class="owner"><h2>このPCの持ち主向け</h2>{problems}'
                f'<p>サイトを足すには <code>{e(str(self.config))}</code> に <code>[[site]]</code> を1つ書き足して、'
                f'このページを再読み込みします（再起動は要りません）。この欄はテスト公開の名前では表示されません。</p></aside>')


class StaticFiles:
    """WSGI: one folder's files, read only ("/" is its index.html). Nothing outside the folder,
    no dot files or folders (.git, .claude), only the file types below. ``home_link``: HTML pages
    get a small "← サイト一覧" link back to the index (for sites that have none of their own)."""

    TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
             ".js": "text/javascript; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml",
             ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
             ".webp": "image/webp", ".ico": "image/x-icon", ".woff2": "font/woff2",
             ".mp3": "audio/mpeg", ".mp4": "video/mp4", ".webm": "video/webm", ".wasm": "application/wasm"}
    #: The site's own files only; inline style attributes and data: images are allowed, nothing is fetched elsewhere.
    CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
           "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
    HOME_LINK = ('<a href="{home}" title="サイト一覧へ戻る" style="position:fixed;left:12px;bottom:12px;z-index:2147483647;'
                 'display:inline-flex;align-items:center;gap:6px;min-height:36px;padding:0 14px;border-radius:18px;'
                 'background:rgba(28,27,25,.9);color:#fff;font:600 13px/1 system-ui,sans-serif;text-decoration:none;'
                 'box-shadow:0 2px 8px rgba(0,0,0,.3)"><span aria-hidden="true">←</span>サイト一覧</a>')
    #: Files looked at for the "更新" date, and how long the date is kept.
    NEWEST_FILES, NEWEST_SECONDS = 2000, 60.0

    def __init__(self, root: Path, allowed_hosts=None, home_link: bool = True):
        self.root = Path(root).resolve()
        self.allowed_hosts = allowed_hosts
        self.home_link = home_link
        self._newest: tuple[float, datetime | None] = (0.0, None)

    def __call__(self, environ, start_response):
        if self.allowed_hosts is not None and not self.allowed_hosts(environ.get("HTTP_HOST", "")):
            return _plain(start_response, "400 Bad Request", b"Bad Request")
        if environ.get("REQUEST_METHOD", "GET") not in ("GET", "HEAD"):
            return _plain(start_response, "405 Method Not Allowed", b"Method Not Allowed")
        parts = [part for part in environ.get("PATH_INFO", "").split("/") if part]
        if not parts or environ.get("PATH_INFO", "").endswith("/"):
            parts.append("index.html")
        file = self.root.joinpath(*parts).resolve()
        # The resolved path is checked too: on Windows a short name (CLAUDE~1) or a link reaches a
        # dot folder that the address never names.
        if (any(part.startswith(".") or "\\" in part or ":" in part or "~" in part for part in parts)
                or not file.is_relative_to(self.root)
                or any(part.startswith(".") for part in file.relative_to(self.root).parts)
                or file.suffix.lower() not in self.TYPES or not file.is_file()):
            return _plain(start_response, "404 Not Found", b"Not Found")
        body = file.read_bytes()
        kind = self.TYPES[file.suffix.lower()]
        if self.home_link and kind.startswith("text/html"):
            body = self._with_home_link(body, environ.get("homepage.home", "/"))
        start_response("200 OK", [("Content-Type", kind), ("Content-Length", str(len(body))),
                                  ("Cache-Control", "no-cache"), ("Content-Security-Policy", self.CSP),
                                  ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "same-origin")])
        return [body]

    def _with_home_link(self, body: bytes, home: str) -> bytes:
        link = self.HOME_LINK.format(home=html.escape(home)).encode("utf-8")
        at = body.lower().rfind(b"</body>")
        return body[:at] + link + body[at:] if at >= 0 else body + link

    def newest(self) -> datetime | None:
        """When the site's files last changed (dot folders left out), looked at once a minute."""
        checked, value = self._newest
        if time.monotonic() - checked < self.NEWEST_SECONDS and checked:
            return value
        latest = 0.0
        count = 0
        try:
            for file in self.root.rglob("*"):
                if any(part.startswith(".") for part in file.relative_to(self.root).parts):
                    continue
                if file.suffix.lower() in self.TYPES and file.is_file():
                    latest = max(latest, file.stat().st_mtime)
                    count += 1
                    if count >= self.NEWEST_FILES:
                        break
        except OSError:
            pass
        value = datetime.fromtimestamp(latest, JST) if latest else None
        self._newest = (time.monotonic(), value)
        return value


def build(apps=(), allowed_hosts=None, visitor_hosts=None, config: Path | None = None) -> Portal:
    """The portal for a server: ``apps`` are the sites it provides (``App``), the rest comes from sites.toml."""
    return Portal(apps, allowed_hosts=allowed_hosts, visitor_hosts=visitor_hosts, config=config or CONFIG)


# -- helpers --------------------------------------------------------------------------------------

_files: dict[Path, tuple[tuple, bytes]] = {}


def _stamp(path: Path) -> tuple:
    try:
        info = path.stat()
    except OSError:
        return ()
    return (info.st_mtime_ns, info.st_size)


def _read(path: Path) -> bytes:
    """A file of this package, read again only when it changed (so design edits show without a restart)."""
    stamp = _stamp(path)
    cached = _files.get(path)
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        body = path.read_bytes()
    except OSError:
        body = b""
    _files[path] = (stamp, body)
    return body


def _version(path: Path) -> str:
    stamp = _stamp(path)
    return f"{stamp[0] // 1_000_000_000:x}" if stamp else "0"


def _icon_svg(name: str) -> str:
    body = _read(PACKAGE / "icons" / f"{name}.svg").decode("utf-8", "replace").strip()
    return body if body.startswith("<svg") else ""


def _text(entry: dict, key: str) -> str:
    value = entry.get(key, "")
    if not isinstance(value, str):
        raise ValueError(f"{key} は文字列（\"…\"）です。")
    return value.strip()


def _flag(entry: dict, key: str) -> bool:
    value = entry.get(key, True)
    if not isinstance(value, bool):
        raise ValueError(f"{key} は true か false です。")
    return value


def _setting(settings: dict, key: str, default: str) -> str:
    value = settings.get(key, default)
    return value.strip() if isinstance(value, str) else default


def _headers(content_type: str, length: int, cache: str) -> list[tuple[str, str]]:
    return [("Content-Type", content_type), ("Content-Length", str(length)), ("Cache-Control", cache),
            ("Content-Security-Policy", "default-src 'none'; style-src 'self'; img-src 'self'; "
                                        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"),
            ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "same-origin")]


def _send(start_response, content_type: str, body: bytes, cache: str):
    start_response("200 OK", _headers(content_type, len(body), cache))
    return [body]


def _plain(start_response, status: str, body: bytes):
    start_response(status, [("Content-Type", "text/plain; charset=utf-8"), ("Content-Length", str(len(body))),
                            ("X-Content-Type-Options", "nosniff")])
    return [body]


def _redirect(start_response, target: str, environ, permanent: bool = False):
    query = environ.get("QUERY_STRING", "")
    location = quote(target, safe="/%:@!$&'()*+,;=-._~") + (f"?{query}" if query else "")
    start_response("308 Permanent Redirect" if permanent else "302 Found",
                   [("Location", location), ("Content-Length", "0")])
    return [b""]
