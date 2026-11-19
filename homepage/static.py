"""The folder sites (``folder = ...`` in sites.toml): one folder's files, read only."""

from __future__ import annotations

import gzip
import hashlib
import html
import os
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from homepage import i18n, web
from homepage.pages import not_found
from homepage.status import JST


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
            return web.plain(start_response, "400 Bad Request", b"Bad Request")
        if environ.get("REQUEST_METHOD", "GET") not in ("GET", "HEAD"):
            return web.plain(start_response, "405 Method Not Allowed", b"Method Not Allowed")
        path = web.wsgi_text(environ.get("PATH_INFO", ""))
        parts = [part for part in path.split("/") if part]
        if not parts or path.endswith("/"):
            parts.append("index.html")
        file = self._file(parts)
        if file is None:
            return not_found(environ, start_response, environ.get("homepage.site", ""))
        kind = self.TYPES[file.suffix.lower()]
        stamp = web.stamp(file)
        is_page = kind.startswith("text/html")
        page, versions = self._page(file, stamp) if is_page else (None, "")
        # What a page gets on its way out: the way back to the list, in the visitor's language, and
        # its relative share links completed with the address the visitor used.
        back = environ.get("homepage.home", "/") if self.home_link and is_page else ""
        made = (
            back,
            i18n.chosen(environ) if back else "",
            web.address(environ) if page is not None and self.SHARE.search(page) else "",
        )
        home = "\n".join(made) if any(made) else ""
        packed = file.suffix.lower() in self.GZIP_TYPES and stamp[1] >= web.GZIP_MIN and web.takes_gzip(environ)
        tag = '"' + hashlib.sha1(f"{stamp}{home}{versions}".encode()).hexdigest()[:16] + ('-gz"' if packed else '"')
        current = not is_page and environ.get("QUERY_STRING", "") == f"v={web.short(stamp)}"
        headers = [
            ("Content-Type", kind),
            ("Cache-Control", web.IMMUTABLE if current else "no-cache"),
            ("ETag", tag),
            ("Last-Modified", web.http_date(stamp[0])),
            # the way back is in the visitor's language
            ("Vary", "Accept-Encoding, Cookie, Accept-Language" if back else "Accept-Encoding"),
            ("Content-Security-Policy", self.CSP),
            *web.SECURITY_HEADERS,
        ]
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
        if kept and kept[0] == stamp and all(web.stamp(asset) == was for asset, was in kept[1]):
            return kept[2], kept[3]
        assets: list[tuple[Path, tuple]] = []
        folder = list(file.parent.relative_to(self.root).parts)

        def versioned(match: re.Match) -> bytes:
            address = match.group(3).decode("utf-8", "replace")
            asset = self._file(folder + [part for part in address.split("/") if part not in ("", ".")])
            if asset is None or asset.suffix.lower() == ".html":
                return match.group(0)
            assets.append((asset, web.stamp(asset)))
            return match.group(1) + match.group(2) + f"{address}?v={web.short(assets[-1][1])}".encode() + match.group(2)

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
