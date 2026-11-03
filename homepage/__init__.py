"""Home Page: the front page of this PC's sites. "/" lists them; each site lives under its own path.

What the page lists comes from ``sites.toml`` in the Home Page folder. Edits to it, and to the
page's HTML, CSS and icons, show on the next request, without restarting the server.

A site is either a folder of static files (``folder = ...`` in sites.toml, served by ``StaticFiles``)
or a Python web app (``python = ...``, ``entry = ...``) that the server (homepage.server) loads at
its start and hands over as an ``App``. ``python -m homepage`` serves the folder sites alone (and,
with ``--demo``, a stand-in News Site), for trying out a change.

Every page is shown in the visitor's language (homepage.i18n: Japanese, Korean, British English,
Traditional Chinese); sites.toml's texts are Japanese, with ``[ko]``, ``[en-GB]``, ``[zh-TW]`` tables
(and ``[site.ko]`` ... under a ``[[site]]``) for the other languages.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import html
import inspect
import json
import os
import re
import threading
import time
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urljoin

from homepage import i18n

PACKAGE = Path(__file__).resolve().parent
HOME = PACKAGE.parent
CONFIG = HOME / "sites.toml"
JST = timezone(timedelta(hours=9))
MOUNT = re.compile(r"/[a-z0-9][a-z0-9-]*")
WORD = re.compile(r"[a-z0-9-]+")
ACCENTS = ("red", "blue", "teal", "green", "amber", "purple", "gray")
#: What a language table may say (sites.toml ``[ko]`` and so on, and ``[site.ko]`` under a site).
PAGE_TEXTS = ("title", "lead", "points", "about")
SITE_TEXTS = ("name", "subtitle", "description", "tags", "open")
#: The portal's own addresses: no site may be mounted over them (/owner: 持ち主のログイン, homepage.owner).
OWN = ("/", "/portal.css", "/favicon.svg", "/apple-touch-icon.png", "/og.png", "/robots.txt", "/owner")
#: Set by the server (homepage.server.Public) in the WSGI environ of a request under a public name:
#: VISITOR_KEY True for a visitor's, OWNER_KEY True for the owner's signed-in device. No request can
#: set them, unlike a header; the sites read them (News Site's public.py).
VISITOR_KEY = "homepage.visitor"
OWNER_KEY = "homepage.owner"
#: Files of this package served as they are: address -> (file, type).
FILES = {
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
    # The icon a phone puts on its home screen (iPhones also ask for it at this address by themselves).
    "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
    # The picture shown with a link to the list (LINE, X, Slack, KakaoTalk ...): 1200 x 630.
    "/og.png": ("og.png", "image/png"),
}
#: What every page of the portal says about itself, the same as News Site's pages (newsreader/web/security.py).
SECURITY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "same-origin"),
    ("X-Frame-Options", "DENY"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()"),
)
#: How often sites.toml is looked at (it is re-read only when it changed).
CHECK_SECONDS = 1.0
#: How long a Python site's preview is shown before it is made again (in the background).
PREVIEW_SECONDS = 60.0
#: For a file asked for at its current version (``?v=``): a new version has a new address.
IMMUTABLE = "public, max-age=31536000, immutable"
#: Text answers from this size up are sent gzipped to browsers that take it.
GZIP_MIN = 1024
#: Light or dark: the device's setting until the visitor picks one with the button in the header
#: (automatic -> light -> dark), the same choice News Site and CoreLab read (localStorage "theme": the
#: sites share one origin). Inline in <head>, so the page is painted in it from the start; the CSP
#: allows exactly this script, by its hash. Phone toolbars (theme-color) follow a forced choice too.
#: It also closes the language menu on a click elsewhere or Escape (back on its button), as the sites do.
THEME_SCRIPT = (
    '(function(){var d=document,r=d.documentElement,o=["auto","light","dark"],c={light:"#f6f4ef",dark:"#161513"};'
    'function get(){try{var t=localStorage.getItem("theme");return o.indexOf(t)>0?t:"auto"}'
    'catch(e){return r.getAttribute("data-theme")||"auto"}}'
    'function set(t){if(t==="auto")r.removeAttribute("data-theme");else r.setAttribute("data-theme",t);'
    "d.querySelectorAll('meta[name=\"theme-color\"]').forEach(function(m){"
    'm.content=c[t==="auto"?(m.media.indexOf("dark")<0?"light":"dark"):t]})}'
    "set(get());"
    'd.addEventListener("DOMContentLoaded",function(){var b=d.getElementById("theme");'
    'if(b)b.addEventListener("click",function(){var t=o[(o.indexOf(get())+1)%3];'
    'try{if(t==="auto")localStorage.removeItem("theme");else localStorage.setItem("theme",t)}catch(e){}set(t)});'
    'var l=d.querySelector("details.lang");if(l){d.addEventListener("click",function(e){if(!l.contains(e.target))l.open=false});'
    'l.addEventListener("keydown",function(e){if(e.key==="Escape"&&l.open){l.open=false;l.querySelector("summary").focus()}})}});'
    'addEventListener("storage",function(e){if(e.key==="theme"||e.key===null)set(get())})})();'
)
THEME_HASH = "'sha256-" + base64.b64encode(hashlib.sha256(THEME_SCRIPT.encode()).digest()).decode() + "'"


@dataclass
class App:
    """A site the server provides: the WSGI ``app`` at ``mount``, listed with these texts unless
    sites.toml says otherwise. ``preview(lang)`` (or ``preview()``) returns what the site has now:
    ``{"title": str, "note": str, "items": [(text, path relative to the site)]}`` (title: the heading
    over the items, "新着" when left out; note: how fresh they are). ``disallow``: paths under the
    mount crawlers should not call. ``legacy``: this site also answers the addresses it had before
    the portal: unknown GET paths are redirected under its mount, paths starting with one of these
    prefixes (and requests that are not GET/HEAD) go to it unchanged. ``version()``: what the
    site's code is now; the server restarts into new code when it changes."""

    key: str
    mount: str
    app: object
    name: str
    subtitle: str = ""
    description: str = ""
    preview: object = None
    disallow: tuple = ()
    legacy: tuple | None = None
    version: object = None


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
    files: StaticFiles | None = None
    #: lang -> {"name": ..., "subtitle": ..., "description": ..., "tags": (...), "open": ...} from sites.toml.
    texts: dict = field(default_factory=dict)
    #: Seconds a preview is shown before it is made again (0: made for every request).
    keep: float = 0.0
    _kept: dict = field(default_factory=dict, repr=False, compare=False)
    _making: set = field(default_factory=set, repr=False, compare=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def say(self, lang: str, key: str):
        """This site's ``key`` in ``lang``: sites.toml's translation, else its Japanese."""
        default = {
            "name": self.name,
            "subtitle": self.subtitle,
            "description": self.description,
            "tags": self.tags,
            "open": self.open_label,
        }[key]
        return self.texts.get(lang, {}).get(key, default)

    def now(self, lang: str = i18n.DEFAULT) -> dict:
        """The site's preview, or {} when it has none or it failed (the index never fails because of it).

        With ``keep`` (a Python site's preview reads its database), a preview is made once and shown
        for that many seconds; after that the next visitor still gets it at once while a new one is
        made in the background, so the index never waits for it again."""
        if not self.preview:
            return {}
        if not self.keep:
            return self._make(lang)
        kept = self._kept.get(lang)
        if kept is None:
            return self._make(lang)
        if time.monotonic() - kept[0] >= self.keep:
            with self._lock:
                start = lang not in self._making
                self._making.add(lang)
            if start:
                threading.Thread(
                    target=self._make, args=(lang,), name=f"preview {self.mount} {lang}", daemon=True
                ).start()
        return kept[1]

    def _make(self, lang: str) -> dict:
        try:
            value = (self.preview(lang) if _takes_an_argument(self.preview) else self.preview()) or {}
        except Exception:  # noqa: BLE001
            value = {}
        if self.keep:
            self._kept[lang] = (time.monotonic(), value)
            with self._lock:
                self._making.discard(lang)
        return value

    def updated(self) -> datetime | None:
        return self.files.newest() if self.files else None


class Portal:
    """WSGI: "/" is the index, ``/<site>/...`` goes to that site."""

    def __init__(self, apps=(), allowed_hosts=None, visitor_hosts=None, config: Path = CONFIG, notes=()):
        self.apps = {item.key: item for item in apps}
        #: What the server could not do at its start (a Python site that failed to load), for the owner.
        self.notes = list(notes)
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
        #: lang -> the page's texts in that language (sites.toml [ko] ...).
        self.page_texts: dict = {}
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
                self.problems = [
                    *self.notes,
                    f"sites.toml を読めませんでした（{exc}）。直すまでは前の内容で表示しています。",
                ]
                if first:
                    self.settings, self.sites = {}, self._sites({})[0]
                return
            self.settings = data
            self.sites, self.problems = self._sites(data)
            try:
                self.page_texts = _translations(data, PAGE_TEXTS)
            except ValueError as exc:
                self.page_texts = {}
                self.problems.insert(0, f"sites.toml の言語の表: {exc}")
            self.problems[:0] = self.notes
            if not stamp:
                self.problems.insert(0, f"{self.config} がありません。サーバーが用意するサイトだけを表示しています。")

    def warm(self) -> threading.Thread:
        """Makes the Python sites' previews in every language in the background, so that the first
        visitors after the server starts do not wait for them."""

        def run() -> None:
            for site in list(self.sites):
                if site.keep:
                    for lang in i18n.LANGS:
                        site.now(lang)

        thread = threading.Thread(target=run, name="preview warm-up", daemon=True)
        thread.start()
        return thread

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
                sites.append(
                    Site(
                        item.mount,
                        item.name,
                        item.app,
                        item.subtitle,
                        item.description,
                        preview=item.preview,
                        keep=PREVIEW_SECONDS,
                    )
                )
        return sites, problems

    def _site(self, entry) -> Site | None:
        if not isinstance(entry, dict):
            raise ValueError("書き方が違います。")
        text = {key: _text(entry, key) for key in ("name", "subtitle", "description", "icon", "open", "preview")}
        accent = _text(entry, "accent") or "gray"
        if accent not in ACCENTS:
            raise ValueError(f"accent は {' / '.join(ACCENTS)} のどれかです。")
        if text["icon"] and not WORD.fullmatch(text["icon"]):
            raise ValueError("icon は icons フォルダのファイル名（拡張子なし）です。")
        tags = entry.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ValueError('tags は文字列の並び（["…", "…"]）です。')
        common = dict(
            icon=text["icon"],
            accent=accent,
            tags=tuple(tags),
            open_label=text["open"],
            listed=_flag(entry, "listed"),
            public=_flag(entry, "public"),
            texts=_translations(entry, SITE_TEXTS),
        )
        if "app" in entry or "python" in entry:
            item = self.apps.get(_text(entry, "app") or _text(entry, "mount"))
            if item is None:  # not loaded (the server's note says why) or not provided (python -m homepage)
                return None
            return Site(
                item.mount,
                text["name"] or item.name,
                item.app,
                text["subtitle"] or item.subtitle,
                text["description"] or item.description,
                preview=item.preview,
                keep=PREVIEW_SECONDS,
                **common,
            )
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
        preview = None
        if text["preview"]:
            file = (root / text["preview"]).resolve()
            if file.suffix.lower() != ".json" or not file.is_relative_to(root):
                raise ValueError('preview はそのフォルダの中の .json ファイルです（例: "portal.json"）。')
            preview = lambda lang: _preview_file(file, lang)  # noqa: E731
        files = StaticFiles(root, self.allowed_hosts, home_link=_text(entry, "home_link") != "own")
        return Site(
            mount, text["name"], files, text["subtitle"], text["description"], files=files, preview=preview, **common
        )

    # -- requests -----------------------------------------------------------------------------

    def __call__(self, environ, start_response):
        self.refresh()
        path = environ.get("PATH_INFO", "") or "/"
        method = environ.get("REQUEST_METHOD", "GET")
        visitor = self._visitor(environ)
        asked = i18n.asked(environ)
        if asked:  # ?lang=ko on any address: remembered for every site, and the same address without it
            return _redirect(
                start_response,
                environ.get("SCRIPT_NAME", "") + path,
                dict(environ, QUERY_STRING=asked[1]),
                headers=[i18n.set_cookie(asked[0], environ.get("wsgi.url_scheme") == "https")],
            )
        for site in self.sites:
            if path == site.mount or path.startswith(site.mount + "/"):
                if visitor and not site.public:
                    return _not_found(environ, start_response)
                if path == site.mount:
                    return _redirect(start_response, environ.get("SCRIPT_NAME", "") + site.mount + "/", environ)
                outer = environ.get("SCRIPT_NAME", "")
                environ = dict(
                    environ,
                    SCRIPT_NAME=outer + site.mount,
                    PATH_INFO=path[len(site.mount) :],
                    **{"homepage.home": outer + "/", "homepage.site": site.say(i18n.chosen(environ), "name")},
                )
                return site.app(environ, start_response)
        if path in OWN:
            if self.allowed_hosts is not None and not self.allowed_hosts(environ.get("HTTP_HOST", "")):
                return _plain(start_response, "400 Bad Request", b"Bad Request")
            if method not in ("GET", "HEAD"):
                return _plain(start_response, "405 Method Not Allowed", b"Method Not Allowed")
            if path == "/owner":  # the owner's own names need no login (the server answers it under the public ones)
                return _redirect(start_response, environ.get("SCRIPT_NAME", "") + "/", dict(environ, QUERY_STRING=""))
            if path == "/portal.css":  # the index asks for it at its version (?v=)
                current = environ.get("QUERY_STRING", "") == f"v={_version(PACKAGE / 'portal.css')}"
                return _send(
                    start_response,
                    "text/css; charset=utf-8",
                    _read(PACKAGE / "portal.css"),
                    IMMUTABLE if current else "public, max-age=86400",
                    environ=environ,
                )
            if path in FILES:
                name, kind = FILES[path]
                current = environ.get("QUERY_STRING", "") == f"v={_version(PACKAGE / name)}"
                return _send(
                    start_response, kind, _read(PACKAGE / name), IMMUTABLE if current else "public, max-age=86400"
                )
            if path == "/robots.txt":
                return _send(
                    start_response, "text/plain; charset=utf-8", self.robots().encode(), "public, max-age=86400"
                )
            body = self.index(environ, visitor).encode("utf-8")
            return _send(start_response, "text/html; charset=utf-8", body, "no-cache", vary=True, environ=environ)
        legacy = next((item for item in self.apps.values() if item.legacy is not None), None)
        if legacy is not None:
            if path.startswith(legacy.legacy) or method not in ("GET", "HEAD"):
                return legacy.app(environ, start_response)
            # Not permanent: a browser keeps a permanent redirect for good, so an address that is
            # unknown today (a typo, or a site added later) would keep going to News Site.
            return _redirect(start_response, legacy.mount + path, environ)
        return _not_found(environ, start_response)

    def _visitor(self, environ) -> bool:
        if VISITOR_KEY in environ:  # the server said (a public name, and whether the owner signed in there)
            return environ[VISITOR_KEY] is True
        return self.visitor_hosts is not None and bool(self.visitor_hosts(environ.get("HTTP_HOST", "")))

    def robots(self) -> str:
        """Crawlers may read pages (link previews come from them) but not call the sites' APIs."""
        paths = [item.mount + part for item in self.apps.values() for part in item.disallow]
        paths += [part for item in self.apps.values() for part in (item.legacy or ())]
        return "User-agent: *\n" + "".join(f"Disallow: {part}\n" for part in dict.fromkeys(paths))

    # -- the page -----------------------------------------------------------------------------

    def index(self, environ, visitor: bool) -> str:
        shown = [site for site in self.sites if site.listed and (site.public or not visitor)]
        lang = i18n.chosen(environ)
        settings = {**self.settings, **self.page_texts.get(lang, {})}
        title = _setting(settings, "title", i18n.text(lang, "サイト一覧"))
        lead = _setting(settings, "lead", "")
        points = settings.get("points", [])
        points = [p for p in points if isinstance(p, str)] if isinstance(points, list) else []
        about = _setting(settings, "about", "")
        today = datetime.now(JST)
        scheme = environ.get("wsgi.url_scheme", "http")
        host = environ.get("HTTP_HOST", "") or environ.get("SERVER_NAME", "")
        home = environ.get("SCRIPT_NAME", "") + "/"
        origin = f"{scheme}://{host}" if host else ""
        e = html.escape
        values = {
            "lang": lang,
            "locale": i18n.LOCALES[lang],
            "menu": i18n.menu(lang),
            "theme": _theme_button(lang),
            "theme_script": THEME_SCRIPT,
            "title": e(title),
            "description": e(lead or title),
            "url": e(f"{origin}{quote(home)}") if host else "",
            "image": e(f"{origin}{quote(home)}og.png?v={_version(PACKAGE / 'og.png')}") if host else "",
            "image_alt": e(f"{title}: " + " · ".join(site.say(lang, "name") for site in shown)),
            "css": e(f"{home}portal.css?v={_version(PACKAGE / 'portal.css')}"),
            "icon": e(f"{home}favicon.svg"),
            "touch_icon": e(f"{home}apple-touch-icon.png?v={_version(PACKAGE / 'apple-touch-icon.png')}"),
            "date": e(i18n.date(lang, today)),
            "lead": f'<p class="lead">{e(lead)}</p>' if lead else "",
            "points": ('<ul class="points">' + "".join(f"<li>{e(p)}</li>" for p in points) + "</ul>") if points else "",
            "sites": "\n".join(self._card(site, n, visitor, lang) for n, site in enumerate(shown, 1)),
            "count": e(i18n.text(lang, "サイト {count} 件", count=len(shown))),
            "about": f"<p>{e(about)}</p>" if about else "",
            "owner": "" if visitor else self._owner_note(environ.get(OWNER_KEY) is True),
        }
        page = _read(PACKAGE / "page.html").decode("utf-8")
        return re.sub(r"\{\{ (\w+) \}\}", lambda m: values.get(m.group(1), ""), page)

    def _card(self, site: Site, number: int, visitor: bool, lang: str = i18n.DEFAULT) -> str:
        e = html.escape
        href = e(site.mount + "/")
        name, subtitle, description = site.say(lang, "name"), site.say(lang, "subtitle"), site.say(lang, "description")
        sub = f'<p class="sub">{e(subtitle)}</p>' if subtitle else ""
        description = f'<p class="desc">{e(description)}</p>' if description else ""
        chips = list(site.say(lang, "tags")) + (
            [] if site.public or visitor else [i18n.text(lang, "非公開（このPCからだけ）")]
        )
        tags = (
            (
                f'<ul class="tags" aria-label="{e(i18n.text(lang, "特徴"))}">'
                + "".join(f"<li>{e(t)}</li>" for t in chips)
                + "</ul>"
            )
            if chips
            else ""
        )
        now = site.now(lang)
        items = "".join(
            f'<li><a href="{e(site.mount + path)}">{e(text)}</a></li>' for text, path in now.get("items", [])
        )
        note = now.get("note", "")
        updated = site.updated()
        if not note and updated:
            note = i18n.updated(lang, updated)
        heading = now.get("title") or i18n.text(lang, "新着")
        preview = (
            (
                f'<div class="now"><p class="now-head">{e(heading)}'
                f"{f'<span>{e(note)}</span>' if note else ''}</p><ul>{items}</ul></div>"
            )
            if items
            else ""
        )
        status = f'<span class="status">{e(note)}</span>' if note and not items else ""
        label = site.say(lang, "open") or i18n.text(lang, "{name} を開く", name=name)
        return (
            f'<li class="site accent-{site.accent}">\n<div class="site-head">{self._icon(site)}'
            f'<div class="site-name"><h2><a href="{href}">{e(name)}</a></h2>{sub}</div>'
            f'<span class="no" aria-hidden="true">{number:02d}</span></div>\n'
            f"{description}{tags}{preview}\n"
            f'<p class="go"><a class="open" href="{href}">{e(label)}<span class="arrow" aria-hidden="true">→</span></a>{status}</p>\n</li>'
        )

    @staticmethod
    def _icon(site: Site) -> str:
        svg = _icon_svg(site.icon) if site.icon else ""
        inner = svg or f'<span class="letter">{html.escape(site.name[:1].upper())}</span>'
        return f'<span class="icon" aria-hidden="true">{inner}</span>'

    def _owner_note(self, signed_in: bool = False) -> str:
        """For the owner only (never a visitor): how to add a site, what in sites.toml is wrong, and on
        a device signed in under the public name (homepage.owner), the way to sign out."""
        e = html.escape
        problems = "".join(f"<li>{e(p)}</li>" for p in self.problems)
        problems = f'<ul class="problems" role="status">{problems}</ul>' if problems else ""
        signed = '<p><a href="/owner">持ち主としてログイン中です（ログアウト）</a></p>' if signed_in else ""
        return (
            f'<div class="owner"><h2>このPCの持ち主向け</h2>{problems}{signed}'
            f"<p>サイトを足すには <code>{e(str(self.config))}</code> に <code>[[site]]</code> を1つ書き足して、"
            f"このページを再読み込みします（再起動は要りません）。この欄は訪問者には表示されません。</p></div>"
        )


class StaticFiles:
    """WSGI: one folder's files, read only ("/" is its index.html). Nothing outside the folder,
    no dot files or folders (.git, .claude), only the file types below. ``home_link``: HTML pages
    get a small "← サイト一覧" link back to the index (for sites that have none of their own).

    Every answer carries an ETag, so a browser that has the file asks again with it and gets a
    bodiless 304, and text is sent gzipped to browsers that take it (about a fifth of the bytes for
    scripts). An HTML page's own scripts and styles are addressed with their version (``?v=``), and
    a file asked for at its current version may be kept for a year: the next visit asks for the
    page alone, not again for each of a game's dozens of scripts (each a trip over the Funnel to a
    small server). A changed file gets a new version in the page, so it is fetched at once.

    A page's ``og:image`` and ``og:url`` may be written relative to it (``content="og.png"``): link
    previews need full addresses, so they are completed with the address the visitor used."""

    TYPES = {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".json": "application/json",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".ico": "image/x-icon",
        ".woff2": "font/woff2",
        ".mp3": "audio/mpeg",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".wasm": "application/wasm",
    }
    #: The site's own files only; inline style attributes and data: images are allowed, nothing is fetched elsewhere.
    CSP = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    )
    HOME_LINK = (
        '<a href="{home}" title="{title}" style="position:fixed;left:12px;bottom:12px;z-index:2147483647;'
        "display:inline-flex;align-items:center;gap:6px;min-height:36px;padding:0 14px;border-radius:18px;"
        "background:rgba(28,27,25,.9);color:#fff;font:600 13px/1 system-ui,sans-serif;text-decoration:none;"
        'box-shadow:0 2px 8px rgba(0,0,0,.3)"><span aria-hidden="true">←</span>{label}</a>'
    )
    #: Files looked at for the "更新" date, and how long the date is kept.
    NEWEST_FILES, NEWEST_SECONDS = 2000, 60.0
    #: Types sent gzipped (the rest are compressed already), from this size up.
    GZIP_TYPES = (".html", ".css", ".js", ".json", ".svg", ".wasm")
    #: Compressed answers kept at most (any *.ts.net name reaches the server, so their number has a limit).
    GZIP_KEPT = 512
    #: A page's own scripts and styles: ``<script src="...">`` and ``<link href="...">`` with a relative address.
    ASSET = re.compile(
        rb"""(<(?:script|link)\b[^>]*?\b(?:src|href)\s*=\s*)(["'])([^"'?#:<>\s/][^"'?#:<>\s]*)\2""", re.I
    )
    #: ``<meta property="og:image" content="...">`` (or og:url) with an address that is not a full one.
    SHARE = re.compile(rb"""(<meta\s+property="og:(?:image|url)"\s+content=")(?!https?:)([^"]*)(")""", re.I)

    def __init__(self, root: Path, allowed_hosts=None, home_link: bool = True):
        self.root = Path(root).resolve()
        self.allowed_hosts = allowed_hosts
        self.home_link = home_link
        self._newest: tuple[float, datetime | None] = (0.0, None)
        #: (path, home) -> (what it was made from, gzipped body): compressed once per change of the file.
        self._gzipped: dict[tuple[Path, str], tuple[tuple, bytes]] = {}
        #: HTML path -> (stamp, [(asset, its stamp)], page with versions, the versions in one word).
        self._pages: dict[Path, tuple[tuple, list, bytes, str]] = {}

    def __call__(self, environ, start_response):
        if self.allowed_hosts is not None and not self.allowed_hosts(environ.get("HTTP_HOST", "")):
            return _plain(start_response, "400 Bad Request", b"Bad Request")
        if environ.get("REQUEST_METHOD", "GET") not in ("GET", "HEAD"):
            return _plain(start_response, "405 Method Not Allowed", b"Method Not Allowed")
        parts = [part for part in environ.get("PATH_INFO", "").split("/") if part]
        if not parts or environ.get("PATH_INFO", "").endswith("/"):
            parts.append("index.html")
        file = self._file(parts)
        if file is None:
            return _not_found(environ, start_response, environ.get("homepage.site", ""))
        kind = self.TYPES[file.suffix.lower()]
        stamp = _stamp(file)
        is_page = kind.startswith("text/html")
        page, versions = self._page(file, stamp) if is_page else (None, "")
        # What a page gets on its way out: the way back to the list, in the visitor's language, and
        # its relative share links completed with the address the visitor used.
        back = environ.get("homepage.home", "/") if self.home_link and is_page else ""
        made = (
            back,
            i18n.chosen(environ) if back else "",
            _address(environ) if is_page and self.SHARE.search(page) else "",
        )
        home = "\n".join(made) if any(made) else ""
        packed = (
            file.suffix.lower() in self.GZIP_TYPES
            and stamp[1] >= GZIP_MIN
            and "gzip" in environ.get("HTTP_ACCEPT_ENCODING", "").lower()
        )
        tag = '"' + hashlib.sha1(f"{stamp}{home}{versions}".encode()).hexdigest()[:16] + ('-gz"' if packed else '"')
        current = not is_page and environ.get("QUERY_STRING", "") == f"v={_short(stamp)}"
        headers = [
            ("Content-Type", kind),
            ("Cache-Control", IMMUTABLE if current else "no-cache"),
            ("ETag", tag),
            ("Last-Modified", _http_date(stamp[0])),
            ("Vary", "Accept-Encoding"),
            ("Content-Security-Policy", self.CSP),
            *SECURITY_HEADERS,
        ]
        if back:
            headers[4] = ("Vary", "Accept-Encoding, Cookie, Accept-Language")
        if tag in environ.get("HTTP_IF_NONE_MATCH", ""):
            start_response("304 Not Modified", headers)
            return [b""]
        body = self._gzip(file, (stamp, versions), home, page) if packed else self._body(file, home, page)
        if packed:
            headers.append(("Content-Encoding", "gzip"))
        start_response("200 OK", [*headers, ("Content-Length", str(len(body)))])
        return [body]

    def _file(self, parts: list[str]) -> Path | None:
        """The file these address parts name, or None when it is not one this site serves."""
        file = self.root.joinpath(*parts).resolve()
        # The resolved path is checked too: on Windows a short name (CLAUDE~1) or a link reaches a
        # dot folder that the address never names.
        if (
            any(part.startswith(".") or "\\" in part or ":" in part or "~" in part for part in parts)
            or not file.is_relative_to(self.root)
            or any(part.startswith(".") for part in file.relative_to(self.root).parts)
            or file.suffix.lower() not in self.TYPES
            or not file.is_file()
        ):
            return None
        return file

    def _page(self, file: Path, stamp: tuple) -> tuple[bytes, str]:
        """An HTML page with its own scripts and styles addressed with their versions, and those
        versions in one word (for the page's ETag); made again when the page or one of them changed."""
        kept = self._pages.get(file)
        if kept and kept[0] == stamp and all(_stamp(asset) == was for asset, was in kept[1]):
            return kept[2], kept[3]
        assets: list[tuple[Path, tuple]] = []
        folder = list(file.parent.relative_to(self.root).parts)

        def versioned(match: re.Match) -> bytes:
            address = match.group(3).decode("utf-8", "replace")
            asset = self._file(folder + [part for part in address.split("/") if part not in ("", ".")])
            if asset is None or asset.suffix.lower() == ".html":
                return match.group(0)
            assets.append((asset, _stamp(asset)))
            return match.group(1) + match.group(2) + f"{address}?v={_short(assets[-1][1])}".encode() + match.group(2)

        try:
            body = self.ASSET.sub(versioned, file.read_bytes())
        except OSError:
            return b"", ""
        versions = hashlib.sha1(repr([was for _, was in assets]).encode()).hexdigest()[:16] if assets else ""
        self._pages[file] = (stamp, assets, body, versions)
        return body, versions

    def _body(self, file: Path, home: str, page: bytes | None) -> bytes:
        """``home``: "" for the file as it is, else "<the list's address>\\n<language>\\n<the page's
        address>" (the way back, and the address relative share links are completed with; each may be "")."""
        body = page if page is not None else file.read_bytes()
        if not home:
            return body
        back, lang, address = home.split("\n")
        if address:
            body = self.SHARE.sub(
                lambda m: m.group(1) + html.escape(urljoin(address, m.group(2).decode())).encode() + m.group(3), body
            )
        return self._with_home_link(body, back, lang) if back else body

    def _gzip(self, file: Path, made_from: tuple, home: str, page: bytes | None) -> bytes:
        kept = self._gzipped.get((file, home))
        if kept and kept[0] == made_from:
            return kept[1]
        body = gzip.compress(self._body(file, home, page), compresslevel=6, mtime=0)
        if len(self._gzipped) >= self.GZIP_KEPT:  # a page's copies differ by the name it was asked under
            self._gzipped.clear()
        self._gzipped[(file, home)] = (made_from, body)
        return body

    def _with_home_link(self, body: bytes, home: str, lang: str) -> bytes:
        link = self.HOME_LINK.format(
            home=html.escape(home),
            title=html.escape(i18n.text(lang, "サイト一覧へ戻る")),
            label=html.escape(i18n.text(lang, "サイト一覧")),
        ).encode("utf-8")
        at = body.lower().rfind(b"</body>")
        return body[:at] + link + body[at:] if at >= 0 else body + link

    def newest(self) -> datetime | None:
        """When the site's files last changed (dot folders left out), looked at once a minute."""
        checked, value = self._newest
        if time.monotonic() - checked < self.NEWEST_SECONDS and checked:
            return value
        latest = 0.0
        count = 0
        for folder, folders, names in os.walk(self.root):
            folders[:] = [name for name in folders if not name.startswith(".")]  # never walks .git
            for name in names:
                if name.startswith(".") or os.path.splitext(name)[1].lower() not in self.TYPES:
                    continue
                try:
                    latest = max(latest, os.stat(os.path.join(folder, name)).st_mtime)
                except OSError:
                    continue
                count += 1
                if count >= self.NEWEST_FILES:
                    break
            if count >= self.NEWEST_FILES:
                break
        value = datetime.fromtimestamp(latest, JST) if latest else None
        self._newest = (time.monotonic(), value)
        return value


def build(apps=(), allowed_hosts=None, visitor_hosts=None, config: Path | None = None, notes=()) -> Portal:
    """The portal for a server: ``apps`` are the sites it provides (``App``), the rest comes from sites.toml."""
    return Portal(apps, allowed_hosts=allowed_hosts, visitor_hosts=visitor_hosts, config=config or CONFIG, notes=notes)


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


def _address(environ) -> str:
    """The full address of this request, without its query (``https://name/infra/``)."""
    host = environ.get("HTTP_HOST", "") or environ.get("SERVER_NAME", "")
    path = quote(environ.get("SCRIPT_NAME", "") + environ.get("PATH_INFO", ""))
    return f"{environ.get('wsgi.url_scheme', 'http')}://{host}{path}"


def _http_date(mtime_ns: int) -> str:
    from email.utils import formatdate

    return formatdate(mtime_ns / 1_000_000_000, usegmt=True)


def _preview_file(file: Path, lang: str = i18n.DEFAULT) -> dict:
    """A folder site's preview, from the JSON file sites.toml names (read again when it changes):
    {"title": "見出し", "note": "ひとこと", "items": [["文", "/path/in/the/site"], ...]}. Any text can
    instead be {"ja": "見出し", "ko": "...", "en-GB": "...", "zh-TW": "..."} (Japanese when the language is missing)."""
    data = json.loads(_read(file).decode("utf-8"))

    def say(value):
        if isinstance(value, dict):
            value = value.get(lang, value.get(i18n.DEFAULT, ""))
        return value if isinstance(value, str) else None

    items = [(say(text), path) for text, path in data.get("items", [])]
    items = [(text, path) for text, path in items if text and isinstance(path, str) and path.startswith("/")]
    return {"title": say(data.get("title", "")) or "", "note": say(data.get("note", "")) or "", "items": items[:5]}


def _translations(entry: dict, keys: tuple) -> dict:
    """sites.toml's language tables (``[ko]``, ``[site.en-GB]`` ...): lang -> {key: text} with the keys allowed."""
    found = {}
    for lang in i18n.LANGS:
        table = entry.get(lang)
        if table is None:
            continue
        if not isinstance(table, dict):
            raise ValueError(f'[{lang}] は表（[{lang}] の下に key = "…"）です。')
        texts = {}
        for key in keys:
            if key not in table:
                continue
            value = table[key]
            if key in ("tags", "points"):
                if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                    raise ValueError(f'[{lang}] の {key} は文字列の並び（["…", "…"]）です。')
                value = tuple(value) if key == "tags" else value
            elif not isinstance(value, str):
                raise ValueError(f'[{lang}] の {key} は文字列（"…"）です。')
            texts[key] = value
        found[lang] = texts
    return found


def _takes_an_argument(function) -> bool:
    try:
        return any(
            p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.VAR_POSITIONAL)
            for p in inspect.signature(function).parameters.values()
        )
    except (TypeError, ValueError):
        return False


def _version(path: Path) -> str:
    stamp = _stamp(path)
    return _short(stamp) if stamp else "0"


def _short(stamp: tuple) -> str:
    """A file's version for its address (``?v=``): from its modification time and size."""
    return hashlib.sha1(repr(stamp).encode()).hexdigest()[:10]


def _icon_svg(name: str) -> str:
    body = _read(PACKAGE / "icons" / f"{name}.svg").decode("utf-8", "replace").strip()
    return body if body.startswith("<svg") else ""


def _text(entry: dict, key: str) -> str:
    value = entry.get(key, "")
    if not isinstance(value, str):
        raise ValueError(f'{key} は文字列（"…"）です。')
    return value.strip()


def _flag(entry: dict, key: str) -> bool:
    value = entry.get(key, True)
    if not isinstance(value, bool):
        raise ValueError(f"{key} は true か false です。")
    return value


def _setting(settings: dict, key: str, default: str) -> str:
    value = settings.get(key, default)
    return value.strip() if isinstance(value, str) else default


def _theme_button(lang: str) -> str:
    """The header's light/dark button (THEME_SCRIPT makes it work): the words and icon of each
    state are all here, and the stylesheet shows the current one (<html data-theme>), so the
    page is right from its first paint."""
    icons = {
        "auto": '<circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor"/>',
        "light": '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.5M12 19v2.5M4.6 4.6l1.8 1.8M17.6 17.6l1.8 1.8'
        'M2.5 12H5M19 12h2.5M4.6 19.4l1.8-1.8M17.6 6.4l1.8-1.8"/>',
        "dark": '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
    }
    states = {"auto": "自動", "light": "オフ", "dark": "オン"}
    e = html.escape
    spans = "".join(
        f'<span class="t-{key}"><svg viewBox="0 0 24 24" aria-hidden="true">{icons[key]}</svg>'
        f'<span class="words">{e(i18n.text(lang, "ダークモード {state}", state=i18n.text(lang, state)))}</span></span>'
        for key, state in states.items()
    )
    return f'<button type="button" class="theme" id="theme" title="{e(i18n.text(lang, "ダークモード: 自動 → オフ → オン"))}">{spans}</button>'


def _headers(content_type: str, length: int, cache: str, form: bool = False) -> list[tuple[str, str]]:
    """``form``: the page sends a form to its own address (the owner's login)."""
    action = "'self'" if form else "'none'"
    return [
        ("Content-Type", content_type),
        ("Content-Length", str(length)),
        ("Cache-Control", cache),
        (
            "Content-Security-Policy",
            f"default-src 'none'; script-src {THEME_HASH}; style-src 'self'; img-src 'self'; "
            f"base-uri 'none'; form-action {action}; frame-ancestors 'none'",
        ),
        *SECURITY_HEADERS,
    ]


def _send(
    start_response,
    content_type: str,
    body: bytes,
    cache: str,
    vary: bool = False,
    status: str = "200 OK",
    environ=None,
    headers=(),
    form: bool = False,
):
    """``vary``: the page is in the visitor's language. ``environ``: gzipped when the browser takes it
    (a page that fits the first packets of a new connection arrives a round trip sooner)."""
    packed = environ is not None and len(body) >= GZIP_MIN and "gzip" in environ.get("HTTP_ACCEPT_ENCODING", "").lower()
    if packed:
        body = gzip.compress(body, compresslevel=6, mtime=0)
    extra, headers = list(headers), _headers(content_type, len(body), cache, form)
    if packed:
        headers.append(("Content-Encoding", "gzip"))
    if vary or environ is not None:
        headers.append(
            (
                "Vary",
                ", ".join(
                    [
                        *(["Accept-Encoding"] if environ is not None else []),
                        *(["Cookie", "Accept-Language"] if vary else []),
                    ]
                ),
            )
        )
    start_response(status, [*headers, *extra])
    return [body]


#: What the login page says after a try (homepage.owner.Owner.login), and its status.
SIGN_IN_PROBLEMS = {
    "wrong": ("401 Unauthorized", "パスワードが違います。"),
    "busy": ("429 Too Many Requests", "試した回数が多すぎます。少し待ってからもう一度どうぞ。"),
    "off": ("403 Forbidden", "ログインはまだ設定されていません。"),
}


def owner_page(environ, start_response, state: str, problem: str = "", headers=()):
    """持ち主のログイン (``/owner`` under a public name, answered by homepage.server.Public): ``state``
    "form" (the password), "in" (this device is the owner's: sign out) or "off" (no password set);
    ``problem``: a SIGN_IN_PROBLEMS key, after a try."""
    lang = i18n.chosen(environ)
    e = html.escape
    say = lambda ja: e(i18n.text(lang, ja))  # noqa: E731
    status, message = SIGN_IN_PROBLEMS.get(problem, ("200 OK", ""))
    if state == "off":
        message = SIGN_IN_PROBLEMS["off"][1]
    alert = f'<p class="problem" role="alert">{say(message)}</p>' if message else ""
    if state == "in":
        lead = say("この端末は持ち主としてログインしています。公開中のページでも、すべての機能が使えます。")
        form = (
            '<form method="post" action="/owner"><input type="hidden" name="do" value="logout">'
            f'<button class="open" type="submit">{say("ログアウト")}</button></form>'
        )
    elif state == "form":
        lead = say("このサイトの持ち主だけが使うページです。ログインすると、この端末ではすべての機能が使えます。")
        form = (
            '<form method="post" action="/owner" class="signin">'
            '<input type="hidden" name="username" value="owner" autocomplete="username">'
            f'<label for="password">{say("パスワード")}</label>'
            '<input id="password" name="password" type="password" autocomplete="current-password" required autofocus>'
            f'<button class="open" type="submit">{say("ログイン")}</button></form>'
        )
    else:
        lead, form = "", ""
    lead = f'<p class="lead">{lead}</p>' if lead else ""
    heading = say("持ち主のログイン")
    body = (
        f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
        f'<title>{heading}</title><script>{THEME_SCRIPT}</script><link rel="icon" href="/favicon.svg" type="image/svg+xml">'
        f'<link rel="stylesheet" href="/portal.css?v={_version(PACKAGE / "portal.css")}"></head>'
        f'<body class="missing"><main><h1>{heading}</h1>'
        f"{lead}{alert}{form}"
        f'<p class="go"><a class="back" href="/"><span class="arrow-back" aria-hidden="true">←</span>{say("サイト一覧")}</a></p>'
        f"</main></body></html>"
    ).encode()
    return _send(
        start_response,
        "text/html; charset=utf-8",
        body,
        "no-store",
        vary=True,
        status=status,
        environ=environ,
        headers=headers,
        form=True,
    )


def _not_found(environ, start_response, site: str = ""):
    """404: a page in the visitor's language with the way back for browsers, two words for the rest."""
    if "text/html" not in environ.get("HTTP_ACCEPT", ""):
        return _plain(start_response, "404 Not Found", b"Not Found")
    lang = i18n.chosen(environ)
    e = html.escape
    home = environ.get("homepage.home", environ.get("SCRIPT_NAME", "") + "/")
    links = f'<a class="open" href="{e(home)}"><span class="arrow-back" aria-hidden="true">←</span>{e(i18n.text(lang, "サイト一覧"))}</a>'
    if site:
        links = (
            f'<a class="open" href="{e(environ.get("SCRIPT_NAME", "") + "/")}">{e(i18n.text(lang, "{name} のトップへ", name=site))}</a>'
            + links.replace('class="open"', 'class="back"')
        )
    heading = e(i18n.text(lang, "ページが見つかりません"))
    body = (
        f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
        f'<title>{heading}</title><script>{THEME_SCRIPT}</script><link rel="icon" href="{e(home)}favicon.svg" type="image/svg+xml">'
        f'<link rel="stylesheet" href="{e(home)}portal.css"></head><body class="missing"><main>'
        f'<p class="date">{e(i18n.text(lang, "エラー {status}", status=404))}</p><h1>{heading}</h1>'
        f'<p class="lead">{e(i18n.text(lang, "アドレスが変わったか、なくなった可能性があります。"))}</p>'
        f'<p class="go">{links}</p></main></body></html>'
    ).encode()
    return _send(
        start_response, "text/html; charset=utf-8", body, "no-cache", vary=True, status="404 Not Found", environ=environ
    )


def _plain(start_response, status: str, body: bytes):
    start_response(
        status,
        [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("X-Content-Type-Options", "nosniff"),
        ],
    )
    return [body]


def _redirect(start_response, target: str, environ, headers=()):
    query = environ.get("QUERY_STRING", "")
    location = quote(target, safe="/%:@!$&'()*+,;=-._~") + (f"?{query}" if query else "")
    start_response(
        "302 Found",
        [("Location", location), ("Content-Length", "0"), *headers],
    )
    return [b""]
