"""Home Page: the front page of this PC's sites. "/" lists them; each site lives under its own path.

What the page lists comes from ``sites.toml`` in the Home Page folder. Edits to it, and to the
page's HTML, CSS and icons, show on the next request, without restarting the server.

A site is either a folder of static files (``folder = ...`` in sites.toml, served by
``homepage.static.StaticFiles``) or a Python web app (``python = ...``, ``entry = ...``) that the
server (homepage.server) loads at its start and hands over as an ``App``. ``python -m homepage``
serves the folder sites alone (and, with ``--demo``, a stand-in News Site), for trying out a change.

Every page is shown in the visitor's language (homepage.i18n: Japanese, Korean, British English,
Traditional Chinese); sites.toml's texts are Japanese, with ``[ko]``, ``[en-GB]``, ``[zh-TW]`` tables
(and ``[site.ko]`` ... under a ``[[site]]``) for the other languages.

Besides the index the portal answers ``/search`` (a card's search box: on to that site's own search),
``/version.json`` (which commit of each site is live), ``/portal.webmanifest`` (the list as an app on a
phone's home screen) and its own files (FILES).
"""

from __future__ import annotations

import html
import inspect
import json
import re
import threading
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qsl, quote

from homepage import i18n, status, web
from homepage.pages import THEME_HASH, THEME_SCRIPT, not_found, owner_page, send, theme_button
from homepage.phrases import mark
from homepage.static import StaticFiles
from homepage.status import JST
from homepage.web import PACKAGE

__all__ = [
    "CONFIG",
    "JST",
    "MOUNT",
    "OWNER_KEY",
    "PACKAGE",
    "THEME_HASH",
    "THEME_SCRIPT",
    "VISITOR_KEY",
    "App",
    "Portal",
    "Site",
    "StaticFiles",
    "build",
    "owner_page",
]

HOME = PACKAGE.parent
CONFIG = HOME / "sites.toml"
MOUNT = re.compile(r"/[a-z0-9][a-z0-9-]*")
WORD = re.compile(r"[a-z0-9-]+")
#: A card's search address in its site (``search = "/search?q={q}"``): printable ASCII, the words go in {q}.
SEARCH = re.compile(r"/[!#$%&'()*+,\-./0-9:;=?@A-Z\[\]_a-z{}~]*")
ACCENTS = ("red", "orange", "blue", "teal", "green", "amber", "purple", "gray")
#: What a language table may say (sites.toml ``[ko]`` and so on, and ``[site.ko]`` under a site).
PAGE_TEXTS = ("title", "headline", "lead", "points", "about")
SITE_TEXTS = ("name", "subtitle", "headline", "description", "facts", "tags", "open", "search_hint", "links")
#: Files of this package served as they are: address -> (file, type).
FILES = {
    # The index asks for it at its version (?v=); sent gzipped to browsers that take it.
    "/portal.css": ("portal.css", "text/css; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
    # The icon a phone puts on its home screen (iPhones also ask for it at this address by themselves).
    "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
    # The picture shown with a link to the list (LINE, X, Slack, KakaoTalk ...): 1200 x 630.
    "/og.png": ("og.png", "image/png"),
    # The app icons of the manifest (Android): plain, and with room around it for any mask shape.
    "/icon-192.png": ("icon-192.png", "image/png"),
    "/icon-512.png": ("icon-512.png", "image/png"),
    "/icon-maskable.png": ("icon-maskable.png", "image/png"),
}
#: The portal's own addresses: no site may be mounted over them (/owner: 持ち主のログイン, homepage.owner).
OWN = (
    "/",
    *FILES,
    "/robots.txt",
    "/owner",
    "/search",
    "/version.json",
    "/portal.webmanifest",
)
#: Set by the server (homepage.server.Public) in the WSGI environ of a request under a public name:
#: VISITOR_KEY True for a visitor's, OWNER_KEY True for the owner's signed-in device. No request can
#: set them, unlike a header; the sites read them (News Site's public.py).
VISITOR_KEY = "homepage.visitor"
OWNER_KEY = "homepage.owner"
#: How often sites.toml is looked at (it is re-read only when it changed).
CHECK_SECONDS = 1.0
#: How long a Python site's preview is shown before it is made again (in the background).
PREVIEW_SECONDS = 60.0
#: The words a card's search box sends at most.
SEARCH_CHARACTERS = 200
#: How many of sites.toml's [[change]] lines the opening shows
CHANGES_SHOWN = 6
#: The page colour (portal.css --paper), for the phone's bar and the app's splash screen.
PAPER = "#fbfbfa"


@dataclass
class App:
    """A site the server provides: the WSGI ``app`` at ``mount``, listed with these texts unless
    sites.toml says otherwise. ``preview(lang)`` (or ``preview()``) returns what the site has now:
    ``{"title": str, "note": str, "items": [(text, path relative to the site)]}`` (title: the heading
    over the items, "新着" when left out; note: how fresh they are). ``disallow``: paths under the
    mount crawlers should not call. ``legacy``: this site also answers the addresses it had before
    the portal: unknown GET paths are redirected under its mount, paths starting with one of these
    prefixes (and requests that are not GET/HEAD) go to it unchanged. ``version()``: what the
    site's code is now; the server restarts into new code when it changes. ``folder``: where its
    code is (its git commit is the version /version.json and the owner's box show)."""

    key: str
    mount: str
    app: Callable
    name: str
    subtitle: str = ""
    description: str = ""
    preview: Callable | None = None
    disallow: tuple = ()
    legacy: tuple | None = None
    version: Callable | None = None
    folder: Path | None = None


@dataclass
class Site:
    """One entry of the list, as sites.toml (and the server's App) define it."""

    mount: str
    name: str
    app: Callable
    subtitle: str = ""
    description: str = ""
    icon: str = ""
    accent: str = "gray"
    #: The big line of its section (what the site does, in a few words) and its facts: (big words, caption).
    headline: str = ""
    facts: tuple = ()
    #: Its section is the page's dark plate (light type on near-black, in both themes).
    dark: bool = False
    tags: tuple = ()
    open_label: str = ""
    listed: bool = True
    public: bool = True
    preview: Callable | None = None
    files: StaticFiles | None = None
    #: The card's search box: an address in the site with {q} for the words, and the box's hint.
    search: str = ""
    search_hint: str = ""
    #: The card's shortcuts: (text, path in the site).
    links: tuple = ()
    #: lang -> {"name": ..., "subtitle": ..., "description": ..., "tags": (...), "open": ..., ...} from sites.toml.
    texts: dict = field(default_factory=dict)
    #: Seconds a preview is shown before it is made again (0: made for every request).
    keep: float = 0.0
    #: The folder of the site's code (a git clone on the VM), for its version.
    folder: Path | None = None
    _kept: dict = field(default_factory=dict, repr=False, compare=False)
    _making: set = field(default_factory=set, repr=False, compare=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def say(self, lang: str, key: str):
        """This site's ``key`` in ``lang``: sites.toml's translation, else its Japanese."""
        default = {
            "name": self.name,
            "subtitle": self.subtitle,
            "headline": self.headline,
            "description": self.description,
            "facts": self.facts,
            "tags": self.tags,
            "open": self.open_label,
            "search_hint": self.search_hint,
        }[key]
        return self.texts.get(lang, {}).get(key, default)

    def shortcuts(self, lang: str) -> list[tuple[str, str]]:
        """The card's shortcuts in ``lang`` (sites.toml ``[site.ko] links`` names them in the same order)."""
        names = self.texts.get(lang, {}).get("links") or [text for text, _ in self.links]
        return [(name, path) for name, (_, path) in zip(names, self.links)]

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
            made = self.preview(lang) if _takes_an_argument(self.preview) else self.preview()  # type: ignore[misc]
            value = _clean_preview(made)
        except Exception:  # a site's preview never breaks the index
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
        #: Notes the deploy scripts leave for the owner (``*.txt``): on the VM, the deploy key a repository
        #: that cannot be cloned yet needs on GitHub (setup.sh), so it can be done from a phone.
        self.owner_notes = self.config.parent / "instance" / "owner-notes"
        #: What runs: when, the Home Page commit and the Python sites' (they change only with a restart).
        self.started = datetime.now(JST)
        self.commit = status.git_head(HOME)
        self.app_commits = {item.mount: status.git_head(item.folder) for item in apps if item.folder}
        #: callable() -> bool, set by the server: new Home Page code is waiting for its restart.
        self.restart_pending: Callable[[], bool] | None = None
        self._lock = threading.Lock()
        self._checked = 0.0
        self._stamp: tuple | None = None  # None: not read yet
        self.settings: dict = {}
        self.changes: list[dict] = []
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
            stamp = web.stamp(self.config)
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
            self.changes, wrong = _changes(data.get("change", []))
            self.problems += wrong
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
                        folder=item.folder,
                    )
                )
        return sites, problems

    def _site(self, entry) -> Site | None:
        if not isinstance(entry, dict):
            raise ValueError("書き方が違います。")
        text = {
            key: _text(entry, key)
            for key in (
                "name",
                "subtitle",
                "headline",
                "description",
                "icon",
                "open",
                "preview",
                "search",
                "search_hint",
            )
        }
        accent = _text(entry, "accent") or "gray"
        if accent not in ACCENTS:
            raise ValueError(f"accent は {' / '.join(ACCENTS)} のどれかです。")
        if text["icon"] and not WORD.fullmatch(text["icon"]):
            raise ValueError("icon は icons フォルダのファイル名（拡張子なし）です。")
        tags = entry.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ValueError('tags は文字列の並び（["…", "…"]）です。')
        if text["search"] and (not SEARCH.fullmatch(text["search"]) or text["search"].count("{q}") != 1):
            raise ValueError('search はサイトの中のアドレスで、言葉の入る {q} を 1 つ含みます（例: "/search?q={q}"）。')
        links = _links(entry.get("links", []))
        facts = _facts(entry.get("facts", []))
        texts = _translations(entry, SITE_TEXTS)
        for lang, said in texts.items():
            if "links" in said and len(said["links"]) != len(links):
                raise ValueError(f"[{lang}] の links は、links と同じ数の名前を同じ順に並べます（{len(links)} 個）。")
        dark = entry.get("dark", False)
        if not isinstance(dark, bool):
            raise ValueError("dark は true か false です。")
        common = {
            "icon": text["icon"],
            "accent": accent,
            "headline": text["headline"],
            "facts": facts,
            "dark": dark,
            "tags": tuple(tags),
            "open_label": text["open"],
            "listed": _flag(entry, "listed"),
            "public": _flag(entry, "public"),
            "search": text["search"],
            "search_hint": text["search_hint"],
            "links": links,
            "texts": texts,
        }
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
                folder=item.folder,
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
            preview = lambda lang: _preview_file(file, lang)
        files = StaticFiles(root, self.allowed_hosts, home_link=_text(entry, "home_link") != "own")
        return Site(
            mount,
            text["name"],
            files,
            text["subtitle"],
            text["description"],
            files=files,
            preview=preview,
            folder=root,
            **common,
        )

    # -- requests -----------------------------------------------------------------------------

    def __call__(self, environ, start_response):
        self.refresh()
        path = environ.get("PATH_INFO", "") or "/"
        method = environ.get("REQUEST_METHOD", "GET")
        visitor = self._visitor(environ)
        outer = environ.get("SCRIPT_NAME", "")
        asked = i18n.asked(environ)
        if asked:  # ?lang=ko on any address: remembered for every site, and the same address without it
            return web.redirect(
                start_response,
                outer + path,
                dict(environ, QUERY_STRING=asked[1]),
                [i18n.set_cookie(asked[0], environ.get("wsgi.url_scheme") == "https")],
            )
        for site in self.sites:
            if path == site.mount or path.startswith(site.mount + "/"):
                if visitor and not site.public:
                    return not_found(environ, start_response)
                if path == site.mount:
                    return web.redirect(start_response, outer + site.mount + "/", environ)
                environ = dict(
                    environ,
                    SCRIPT_NAME=outer + site.mount,
                    PATH_INFO=path[len(site.mount) :],
                    **{"homepage.home": outer + "/", "homepage.site": site.say(i18n.chosen(environ), "name")},
                )
                return site.app(environ, start_response)
        if path in OWN:
            return self._own(environ, start_response, path, method, visitor)
        legacy = next((item for item in self.apps.values() if item.legacy is not None), None)
        if legacy is not None:
            if path.startswith(legacy.legacy) or method not in ("GET", "HEAD"):
                return legacy.app(environ, start_response)
            # Not permanent: a browser keeps a permanent redirect for good, so an address that is
            # unknown today (a typo, or a site added later) would keep going to News Site.
            return web.redirect(start_response, outer + legacy.mount + path, environ)
        return not_found(environ, start_response)

    def _own(self, environ, start_response, path: str, method: str, visitor: bool):
        """The portal's own addresses (OWN)."""
        if self.allowed_hosts is not None and not self.allowed_hosts(environ.get("HTTP_HOST", "")):
            return web.plain(start_response, "400 Bad Request", b"Bad Request")
        if method not in ("GET", "HEAD"):
            return web.plain(start_response, "405 Method Not Allowed", b"Method Not Allowed")
        outer = environ.get("SCRIPT_NAME", "")
        if path == "/owner":  # the owner's own names need no login (the server answers it under the public ones)
            return web.redirect(start_response, outer + "/", dict(environ, QUERY_STRING=""))
        if path in FILES:
            name, kind = FILES[path]
            current = environ.get("QUERY_STRING", "") == f"v={web.version(PACKAGE / name)}"
            return send(
                start_response,
                kind,
                web.read(PACKAGE / name),
                web.IMMUTABLE if current else "public, max-age=86400",
                environ=environ if kind.startswith("text/") else None,  # the pictures are compressed already
            )
        if path == "/robots.txt":
            return send(start_response, "text/plain; charset=utf-8", self.robots().encode(), "public, max-age=86400")
        if path == "/search":
            return self._search(environ, start_response, visitor)
        if path == "/version.json":
            body = json.dumps(self.versions(visitor), ensure_ascii=False, indent=1).encode()
            return send(start_response, "application/json", body, "no-store")
        if path == "/portal.webmanifest":
            body = json.dumps(self.manifest(environ), ensure_ascii=False).encode()
            return send(start_response, "application/manifest+json", body, "no-cache", vary=True, environ=environ)
        body = self.index(environ, visitor).encode("utf-8")
        return send(start_response, "text/html; charset=utf-8", body, "no-cache", vary=True, environ=environ, form=True)

    def _search(self, environ, start_response, visitor: bool):
        """A card's search box (``/search?site=/val&q=...``): on to that site's own search with the words,
        its top without them. The way works without a script, and also to a page's ``#...`` (CoreLab)."""
        asked = dict(parse_qsl(web.wsgi_text(environ.get("QUERY_STRING", ""))))
        site = next(
            (
                item
                for item in self.sites
                if item.mount == asked.get("site") and item.search and (item.public or not visitor)
            ),
            None,
        )
        if site is None:
            return not_found(environ, start_response)
        words = " ".join(asked.get("q", "").split())[:SEARCH_CHARACTERS]
        target = environ.get("SCRIPT_NAME", "") + site.mount
        target += site.search.replace("{q}", quote(words, safe="")) if words else "/"
        return web.found(start_response, target, [("Cache-Control", "no-store")])

    def _visitor(self, environ) -> bool:
        if VISITOR_KEY in environ:  # the server said (a public name, and whether the owner signed in there)
            return environ[VISITOR_KEY] is True
        return self.visitor_hosts is not None and bool(self.visitor_hosts(environ.get("HTTP_HOST", "")))

    def robots(self) -> str:
        """Crawlers may read pages (link previews come from them) but not call the sites' APIs or searches."""
        paths = ["/search", *(item.mount + part for item in self.apps.values() for part in item.disallow)]
        paths += [part for item in self.apps.values() for part in (item.legacy or ())]
        return "User-agent: *\n" + "".join(f"Disallow: {part}\n" for part in dict.fromkeys(paths))

    def versions(self, visitor: bool = True) -> dict:
        """What is live now (``/version.json``): each site's git commit ("/" is Home Page itself), and
        when the server started. New Home Page code counts once the server restarted into it; pages,
        styles and sites.toml count at once (they are read for every request), and so do folder sites."""
        commits = {"/": self._home_commit()[0]}
        commits.update({site.mount: self._commit(site)[0] for site in self.sites if site.public or not visitor})
        return {"started": self.started.isoformat(timespec="seconds"), "versions": commits}

    def _pending(self) -> bool:
        return self.restart_pending is not None and self.restart_pending()

    def _home_commit(self, pending: bool | None = None) -> tuple[str, datetime | None]:
        """Home Page's live commit: the one on disk, unless its new code still waits for the restart."""
        return self.commit if (self._pending() if pending is None else pending) else status.git_head(HOME)

    def _commit(self, site: Site) -> tuple[str, datetime | None]:
        """A site's live commit: a Python site's since the server's start (new code needs a restart),
        a folder site's as it is on disk (its files are served as they are)."""
        if site.folder is None:
            return "", None
        if site.files is None:
            return self.app_commits.get(site.mount, ("", None))
        return status.git_head(site.folder)

    def manifest(self, environ) -> dict:
        """The list as an app on a phone's home screen (Android asks for this; iPhones take apple-touch-icon)."""
        lang = i18n.chosen(environ)
        settings = {**self.settings, **self.page_texts.get(lang, {})}
        home = environ.get("SCRIPT_NAME", "") + "/"
        icon = lambda name, size, purpose: {
            "src": web.asset(name, home),
            "sizes": size,
            "type": "image/png",
            "purpose": purpose,
        }
        return {
            "name": _setting(settings, "title", i18n.text(lang, "サイト一覧")),
            "short_name": i18n.text(lang, "サイト一覧"),
            "description": _setting(settings, "lead", ""),
            "lang": lang,
            "id": home,
            "start_url": home,
            "scope": home,
            "display": "standalone",
            "background_color": PAPER,
            "theme_color": PAPER,
            "icons": [
                icon("icon-192.png", "192x192", "any"),
                icon("icon-512.png", "512x512", "any"),
                icon("icon-maskable.png", "512x512", "maskable"),
            ],
        }

    # -- the page -----------------------------------------------------------------------------

    def index(self, environ, visitor: bool) -> str:
        shown = [site for site in self.sites if site.listed and (site.public or not visitor)]
        lang = i18n.chosen(environ)
        settings = {**self.settings, **self.page_texts.get(lang, {})}
        title = _setting(settings, "title", i18n.text(lang, "サイト一覧"))
        headline = _setting(settings, "headline", "") or title
        lead = _setting(settings, "lead", "")
        points = settings.get("points", [])
        points = [p for p in points if isinstance(p, str)] if isinstance(points, list) else []
        about = _setting(settings, "about", "")
        scheme = environ.get("wsgi.url_scheme", "http")
        host = environ.get("HTTP_HOST", "") or environ.get("SERVER_NAME", "")
        home = environ.get("SCRIPT_NAME", "") + "/"
        origin = f"{scheme}://{host}" if host else ""
        e = html.escape
        say = _sayer(lang)
        jump = ""
        if len(shown) > 1:
            jump = (
                f'<nav class="jump" aria-label="{say("サイトへ移動")}"><ul>'
                + "".join(f'<li><a href="#{_anchor(site)}">{e(site.say(lang, "name"))}</a></li>' for site in shown)
                + "</ul></nav>"
            )
        values = {
            "lang": lang,
            "locale": i18n.LOCALES[lang],
            "menu": i18n.menu(lang),
            "theme": theme_button(lang),
            "theme_script": THEME_SCRIPT,
            "title": e(title),
            "headline": _words(headline, lang),
            "description": e(lead or title),
            "url": e(f"{origin}{web.url_path(home)}") if host else "",
            "image": e(f"{origin}{web.url_path(home)}og.png?v={web.version(PACKAGE / 'og.png')}") if host else "",
            "image_alt": e(f"{title}: " + " · ".join(site.say(lang, "name") for site in shown)),
            "css": e(web.asset("portal.css", home)),
            "icon": e(f"{home}favicon.svg"),
            "touch_icon": e(web.asset("apple-touch-icon.png", home)),
            "manifest": e(f"{home}portal.webmanifest"),
            "jump": jump,
            "lead": f'<p class="lead">{mark(lead, lang)}</p>' if lead else "",
            "points": ('<ul class="points">' + "".join(f"<li>{mark(p, lang)}</li>" for p in points) + "</ul>")
            if points
            else "",
            "find": self._find_all(shown, lang, home),
            "log": self._log(shown, lang),
            "sites": "\n".join(self._section(site, n, visitor, lang, home) for n, site in enumerate(shown, 1)),
            "count": e(i18n.text(lang, "サイト {count} 件", count=len(shown))),
            "about": f"<p>{mark(about, lang)}</p>" if about else "",
            "owner": "" if visitor else self._owner_note(lang, environ.get(OWNER_KEY) is True),
        }
        page = web.read(PACKAGE / "page.html").decode("utf-8")
        return re.sub(r"\{\{ (\w+) \}\}", lambda m: values.get(m.group(1), ""), page)

    def _log(self, shown: list[Site], lang: str) -> str:
        """What changed lately (sites.toml ``[[change]]``), newest first: the day, the site and one plain line."""
        e = html.escape
        names = {site.mount: site for site in shown}
        rows = []
        for change in self.changes[:CHANGES_SHOWN]:
            site = names.get(change["site"])
            if change["site"] and site is None:
                continue  # a change on a site this visitor does not see
            text = change["texts"].get(lang) or change["texts"]["ja"]
            where = f'<a href="{e(site.mount)}/">{e(site.say(lang, "name"))}</a>' if site else ""
            rows.append(
                f'<li><time datetime="{change["day"].isoformat()}">{e(i18n.month_day(lang, change["day"]))}</time>'
                f"{where}<p>{mark(text, lang)}</p></li>"
            )
        if not rows:
            return ""
        return (
            f'<aside class="log" aria-labelledby="log-head"><h2 id="log-head">{_sayer(lang)("最近の変更")}</h2>'
            f"<ol>{''.join(rows)}</ol></aside>"
        )

    @staticmethod
    def _find_all(shown: list[Site], lang: str, home: str) -> str:
        """The opening screen's search: pick a site (the first one with a search box is chosen), type, and
        go on to that site's own search, as its section's box does."""
        e = html.escape
        say = _sayer(lang)
        searchable = [site for site in shown if site.search]
        if not searchable:
            return ""
        if len(searchable) == 1:
            where = f'<input type="hidden" name="site" value="{e(searchable[0].mount)}">'
            hint = _hint(searchable[0], lang)
        else:
            where = (
                f'<select name="site" aria-label="{say("検索するサイト")}">'
                + "".join(
                    f'<option value="{e(site.mount)}">{e(site.say(lang, "name"))}</option>' for site in searchable
                )
                + "</select>"
            )
            hint = i18n.text(lang, "サイトを選んで検索")
        return _search_form(home, where, hint, i18n.text(lang, "検索する言葉"), lang)

    def _section(self, site: Site, number: int, visitor: bool, lang: str = i18n.DEFAULT, home: str = "/") -> str:
        """One site's screen: its name, the headline, what it is, how to go in, a framed preview
        (its own search, what it has now or its most used pages) and its facts."""
        e = html.escape
        say = _sayer(lang)
        href = e(site.mount + "/")
        anchor = _anchor(site)
        name, subtitle, description = site.say(lang, "name"), site.say(lang, "subtitle"), site.say(lang, "description")
        headline = site.say(lang, "headline")
        private = "" if site.public or visitor else f'<span class="private">{say("非公開（持ち主だけ）")}</span>'
        intro = (
            f'<h2 class="name" id="{anchor}-name">{self._icon(site)}<span>{e(name)}</span>{private}</h2>\n'
            + (f'<p class="headline">{mark(headline, lang)}</p>\n' if headline else "")
            + (f'<p class="desc">{mark(description or subtitle, lang)}</p>\n' if description or subtitle else "")
        )
        now = site.now(lang)
        items = "".join(
            f'<li><a href="{e(site.mount + path)}">{mark(text, lang)}</a></li>' for text, path in now.get("items", [])
        )
        note = now.get("note", "")
        updated = site.updated()
        if not note and updated:
            note = i18n.updated(lang, updated)
        shortcuts = site.shortcuts(lang)
        label = site.say(lang, "open") or i18n.text(lang, "{name} を開く", name=name)
        more = "".join(
            f'<a class="more" href="{e(site.mount + path)}">{e(text)}<span aria-hidden="true">›</span></a>'
            for text, path in (shortcuts if items else [])
        )
        go = f'<p class="go"><a class="open" href="{href}">{e(label)}</a>{more}</p>\n'
        body = ""
        if items:
            heading = now.get("title") or i18n.text(lang, "新着")
            body = (
                f'<div class="now"><p class="now-head">{mark(heading, lang)}'
                f"{f'<span>{e(note)}</span>' if note else ''}</p><ol>{items}</ol></div>"
            )
        elif shortcuts:
            body = (
                f'<nav class="links" aria-label="{e(name)}: {say("よく使うページ")}"><ul>'
                + "".join(
                    f'<li><a href="{e(site.mount + path)}"><b>{e(text)}</b><code>{e(site.mount + path)}</code></a></li>'
                    for text, path in shortcuts
                )
                + "</ul></nav>"
            )
        find = ""
        if site.search:
            hint = _hint(site, lang)
            find = _search_form(
                home, f'<input type="hidden" name="site" value="{e(site.mount)}">', hint, f"{name}: {hint}", lang
            )
        sub = f'<span class="sub">{mark(subtitle, lang)}</span>' if subtitle and subtitle != headline else ""
        state = f'<span class="status">{e(note)}</span>' if note and not items else ""
        screen = ""
        if body or find:
            screen = (
                f'<div class="screen"><div class="bar"><p class="who"><b>{e(name)}</b>{sub}{state}</p>{find}</div>'
                f"{body}</div>\n"
            )
        elif state:  # nothing to frame: how fresh it is goes beside the open button
            go = go.replace("</p>\n", f"{state}</p>\n")
        facts = site.say(lang, "facts")
        if facts:
            rows = "".join(
                f"<li><b>{mark(big, lang)}</b><span>{mark(caption, lang)}</span></li>" for big, caption in facts
            )
            extra = f'<ul class="facts" aria-label="{e(name)}: {say("特徴")}">{rows}</ul>\n'
        else:
            tags = site.say(lang, "tags")
            extra = (
                f'<ul class="tags" aria-label="{e(name)}: {say("特徴")}">'
                + "".join(f"<li>{mark(t, lang)}</li>" for t in tags)
                + "</ul>\n"
                if tags
                else ""
            )
        # Odd sections on the light grey band, even ones beside their preview (on a computer); one may be the dark plate
        look = (" plate" if site.dark else " band" if number % 2 else "") + ("" if number % 2 else " side")
        return (
            f'<section class="site accent-{site.accent}{look}" id="{anchor}" aria-labelledby="{anchor}-name">\n'
            f"{intro}{go}{screen}{extra}</section>"
        )

    def _left_notes(self) -> list[str]:
        try:
            files = sorted(self.owner_notes.glob("*.txt"))[:10]
            return [item.read_text(encoding="utf-8")[:4000] for item in files]
        except OSError:
            return []

    @staticmethod
    def _left_note(text: str) -> str:
        """A note's lines: an https address as a link, a key (``ssh-...``) to copy whole, the rest as text."""
        e = html.escape
        parts = []
        for line in filter(None, (line.strip() for line in text.splitlines())):
            if line.startswith("https://") and " " not in line:
                parts.append(f'<p><a href="{e(line)}" rel="noreferrer">{e(line)}</a></p>')
            elif line.startswith("ssh-"):
                parts.append(f'<p><code class="copy">{e(line)}</code></p>')
            else:
                parts.append(f"<p>{e(line)}</p>")
        return f'<div class="left-note" role="status">{"".join(parts)}</div>'

    @staticmethod
    def _icon(site: Site) -> str:
        svg = _icon_svg(site.icon) if site.icon else ""
        inner = svg or f'<span class="letter">{html.escape(site.name[:1].upper())}</span>'
        return f'<span class="icon" aria-hidden="true">{inner}</span>'

    def _owner_note(self, lang: str = i18n.DEFAULT, signed_in: bool = False) -> str:
        """For the owner only (never a visitor): what in sites.toml is wrong, the deploy scripts' notes,
        what runs now (each site's commit and when it arrived, the machine), how to add a site, and on
        a device signed in under the public name (homepage.owner), the way to sign out."""
        e = html.escape
        say = _sayer(lang)
        problems = "".join(f"<li>{e(p)}</li>" for p in self.problems)
        problems = f'<ul class="problems" role="status">{problems}</ul>' if problems else ""
        problems += "".join(self._left_note(text) for text in self._left_notes())
        signed = f'<p><a href="/owner">{say("持ち主としてログイン中です（ログアウト）")}</a></p>' if signed_in else ""
        return (
            f'<div class="owner"><h2>{say("持ち主向け")}</h2>{problems}{self._running(lang)}{signed}'
            f"<p>{mark(i18n.text(lang, 'サイトを足すには sites.toml に [[site]] を1つ書き足します（VM へは master に push して約 1 分）。'), lang)} "
            f"{mark(i18n.text(lang, 'この欄は訪問者には表示されません。'), lang)}</p></div>"
        )

    def _running(self, lang: str) -> str:
        """The owner's view of what runs: each site's commit and when it arrived, then the machine."""
        e = html.escape
        say = _sayer(lang)
        pending = self._pending()
        rows = [("Home Page", *self._home_commit(pending))] + [
            (site.say(lang, "name"), *self._commit(site)) for site in self.sites
        ]
        lines = "".join(
            f'<tr><th scope="row">{e(name)}</th><td><code>{e(commit[:7])}</code></td>'
            f"<td>{e(i18n.moment(lang, when)) if when else ''}</td></tr>"
            for name, commit, when in rows
            if commit
        )
        machine = status.machine(HOME)
        facts = [say("起動 {when}", when=i18n.moment(lang, self.started))]
        if pending:
            facts.append(say("新しいコードで再起動待ち"))
        if "load" in machine:
            facts.append(say("負荷 {load}", load=f"{machine['load']:.2f}"))
        for key, label in (("memory", "メモリ {used} / {total}"), ("swap", "スワップ {used} / {total}")):
            if key in machine:
                used, total = machine[key]
                facts.append(say(label, used=status.size(used), total=status.size(total)))
        if "process" in machine:
            facts.append(say("このサーバー {size}", size=status.size(machine["process"])))
        if "disk" in machine:
            facts.append(say("ディスクの空き {size}", size=status.size(machine["disk"][0])))
        table = f'<table class="running"><caption>{say("動いている版")}</caption>{lines}</table>' if lines else ""
        # each fact on one line ("16 GB" never splits), a line may break between them
        return f'{table}<p class="machine">{" · ".join(f"<span>{fact}</span>" for fact in facts)}</p>'


def build(apps=(), allowed_hosts=None, visitor_hosts=None, config: Path | None = None, notes=()) -> Portal:
    """The portal for a server: ``apps`` are the sites it provides (``App``), the rest comes from sites.toml."""
    return Portal(apps, allowed_hosts=allowed_hosts, visitor_hosts=visitor_hosts, config=config or CONFIG, notes=notes)


# -- helpers --------------------------------------------------------------------------------------


def _preview_file(file: Path, lang: str = i18n.DEFAULT) -> dict:
    """A folder site's preview, from the JSON file sites.toml names (read again when it changes):
    {"title": "見出し", "note": "ひとこと", "items": [["文", "/path/in/the/site"], ...]}. Any text can
    instead be {"ja": "見出し", "ko": "...", "en-GB": "...", "zh-TW": "..."} (Japanese when the language is missing)."""
    data = json.loads(web.read(file).decode("utf-8"))

    def say(value):
        return value.get(lang, value.get(i18n.DEFAULT, "")) if isinstance(value, dict) else value

    preview = _clean_preview(data, say)
    return {**preview, "items": preview["items"][:5]} if preview else {}


def _clean_preview(value, say=lambda text: text) -> dict:
    """A site's preview as the index shows it: ``title`` and ``note`` texts (or ""), and ``items``,
    pairs of a text and a path in the site (starting with /); ``say`` picks each text's language.
    Anything else is left out, so a site that returns something odd still gets its card."""
    if not isinstance(value, dict):
        return {}

    def text(raw) -> str:
        raw = say(raw)
        return raw if isinstance(raw, str) else ""

    items = value.get("items")
    pairs = (
        [item for item in items if isinstance(item, (list, tuple)) and len(item) == 2]
        if isinstance(items, (list, tuple))
        else []
    )
    return {
        "title": text(value.get("title")),
        "note": text(value.get("note")),
        "items": [
            (text(words), path)
            for words, path in pairs
            if text(words) and isinstance(path, str) and path.startswith("/")
        ],
    }


def _links(value) -> tuple:
    """sites.toml ``links``: [["文", "/サイト内のパス"], ...] as (text, path) pairs."""
    if not isinstance(value, list) or not all(
        isinstance(item, list)
        and len(item) == 2
        and all(isinstance(part, str) and part.strip() for part in item)
        and item[1].startswith("/")
        for item in value
    ):
        raise ValueError('links は [["文", "/サイト内のパス"], …] の並びです。')
    return tuple((text.strip(), path.strip()) for text, path in value)


def _facts(value, where: str = "") -> tuple:
    """sites.toml ``facts``: [["大きな文字", "その説明"], ...] (at most 4) as (big, caption) pairs."""
    if (
        not isinstance(value, list)
        or len(value) > 4
        or not all(
            isinstance(item, list) and len(item) == 2 and all(isinstance(part, str) and part.strip() for part in item)
            for item in value
        )
    ):
        raise ValueError(f'{where}facts は [["大きな文字", "その説明"], …] の並びです（4 つまで）。')
    return tuple((big.strip(), caption.strip()) for big, caption in value)


def _changes(entries) -> tuple[list[dict], list[str]]:
    """sites.toml ``[[change]]``: day = 2026-11-27, site = "/val" (optional), text = "…" and ko / en-GB / zh-TW."""
    if not isinstance(entries, list):
        return [], ["[[change]] の書き方が違います。"]
    found, problems = [], []
    for number, entry in enumerate(entries, 1):
        day = entry.get("day") if isinstance(entry, dict) else None
        if isinstance(day, str):
            try:
                day = date.fromisoformat(day)
            except ValueError:
                day = None
        texts = {lang: entry.get("text" if lang == i18n.DEFAULT else lang) for lang in i18n.LANGS} if day else {}
        site = entry.get("site", "") if isinstance(entry, dict) else ""
        if (
            not isinstance(day, date)
            or not isinstance(site, str)
            or not isinstance(texts.get(i18n.DEFAULT), str)
            or not all(isinstance(value, (str, type(None))) for value in texts.values())
        ):
            problems.append(f'{number} 番目の変更: day = 2026-11-27 と text = "…" が要ります（site は "/val" の形）。')
            continue
        texts = {lang: value.strip() for lang, value in texts.items() if value and value.strip()}
        day = day.date() if isinstance(day, datetime) else day
        found.append({"day": day, "site": site.rstrip("/"), "texts": texts})
    found.sort(key=lambda change: change["day"], reverse=True)
    return found, problems


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
            if key == "facts":
                value = _facts(value, f"[{lang}] の ")
            elif key in ("tags", "points", "links"):
                if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                    raise ValueError(f'[{lang}] の {key} は文字列の並び（["…", "…"]）です。')
                value = tuple(value) if key == "tags" else value
            elif not isinstance(value, str):
                raise ValueError(f'[{lang}] の {key} は文字列（"…"）です。')
            texts[key] = value
        found[lang] = texts
    return found


def _words(text: str, lang: str = i18n.DEFAULT) -> str:
    """The opening headline, each phrase (up to its 。 . , 、) in its own span, so they can come in one after another
    (and a line breaks between them, or between the smaller phrases inside one: homepage.phrases)."""
    parts = re.findall(r"(.+?(?:[。．.,、，!！?？]|$))(\s*)", text.strip())
    spans = [f'<span class="w">{mark(word, lang)}</span>{" " if gap else ""}' for word, gap in parts if word]
    return "".join(spans).rstrip()


def _anchor(site: Site) -> str:
    """The id of a site's section (the nav jumps to it): its mount without slashes, "news" for /news."""
    word = site.mount.strip("/").replace("/", "-") or "site"
    return word if word not in ("top", "theme") else f"site-{word}"


def _hint(site: Site, lang: str) -> str:
    return site.say(lang, "search_hint") or i18n.text(lang, "{name} の中を検索", name=site.say(lang, "name"))


def _search_form(home: str, where: str, hint: str, label: str, lang: str) -> str:
    """A search box: on to the chosen site's own search through /search (``where`` names the site)."""
    e = html.escape
    say = _sayer(lang)
    return (
        f'<form class="find" action="{e(home)}search" method="get" role="search">{where}'
        f'<input type="search" name="q" placeholder="{e(hint)}" aria-label="{e(label)}" '
        f'maxlength="{SEARCH_CHARACTERS}" required autocapitalize="off" spellcheck="false" enterkeyhint="search">'
        f'<button type="submit" title="{say("検索")}"><svg viewBox="0 0 24 24" aria-hidden="true">'
        '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 5 5"/></svg>'
        f'<span class="words">{say("検索")}</span></button></form>'
    )


def _sayer(lang: str) -> Callable[..., str]:
    """``say("サイト一覧")``: a portal text in ``lang``, escaped for HTML."""
    return lambda ja, **values: html.escape(i18n.text(lang, ja, **values))


def _takes_an_argument(function) -> bool:
    try:
        return any(
            p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.VAR_POSITIONAL)
            for p in inspect.signature(function).parameters.values()
        )
    except (TypeError, ValueError):
        return False


def _icon_svg(name: str) -> str:
    body = web.read(PACKAGE / "icons" / f"{name}.svg").decode("utf-8", "replace").strip()
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
