"""How the portal answers: headers every answer carries, gzip, redirects, addresses, and its own files.

Shared by the index and the portal's pages (homepage/__init__.py, homepage/pages.py) and the folder
sites (homepage/static.py). Nothing here knows about sites.toml.
"""

from __future__ import annotations

import hashlib
from email.utils import formatdate
from pathlib import Path
from urllib.parse import quote

PACKAGE = Path(__file__).resolve().parent
#: What every page of the portal says about itself, the same as News Site's pages (newsreader/web/security.py).
SECURITY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "same-origin"),
    ("X-Frame-Options", "DENY"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()"),
)
#: For a file asked for at its current version (``?v=``): a new version has a new address.
IMMUTABLE = "public, max-age=31536000, immutable"
#: Text answers from this size up are sent gzipped to browsers that take it.
GZIP_MIN = 1024


def stamp(path: Path) -> tuple:
    """(modification time, size) of a file, or () when it is not there."""
    try:
        info = path.stat()
    except OSError:
        return ()
    return (info.st_mtime_ns, info.st_size)


_files: dict[Path, tuple[tuple, bytes]] = {}


def read(path: Path) -> bytes:
    """A file of this package, read again only when it changed (so design edits show without a restart)."""
    now = stamp(path)
    cached = _files.get(path)
    if cached and cached[0] == now:
        return cached[1]
    try:
        body = path.read_bytes()
    except OSError:
        body = b""
    _files[path] = (now, body)
    return body


def short(value: tuple) -> str:
    """A file's version for its address (``?v=``): from its modification time and size."""
    return hashlib.sha1(repr(value).encode()).hexdigest()[:10]


def version(path: Path) -> str:
    now = stamp(path)
    return short(now) if now else "0"


def asset(name: str, home: str = "/") -> str:
    """The address of a file of this package at its current version (``/portal.css?v=...``)."""
    return f"{home}{name}?v={version(PACKAGE / name)}"


def http_date(mtime_ns: int) -> str:
    return formatdate(mtime_ns / 1_000_000_000, usegmt=True)


def wsgi_text(value: str) -> str:
    """A path from the WSGI environ as text: servers give its bytes as latin-1 (PEP 3333), the
    address has them in UTF-8 (``/写真.png``). Anything else (not UTF-8, or text already) stays as it is."""
    try:
        return value.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return value


def url_path(path: str, safe: str = "/") -> str:
    """A WSGI path (PEP 3333: the request's bytes as latin-1) %-quoted for a Location header or a link.
    Text that is not latin-1 (not from a WSGI server) is sent as UTF-8."""
    try:
        raw = path.encode("latin-1")
    except UnicodeEncodeError:
        raw = path.encode("utf-8")
    return quote(raw, safe=safe)


def address(environ) -> str:
    """The full address of this request, without its query (``https://name/infra/``)."""
    host = environ.get("HTTP_HOST", "") or environ.get("SERVER_NAME", "")
    path = url_path(environ.get("SCRIPT_NAME", "") + environ.get("PATH_INFO", ""))
    return f"{environ.get('wsgi.url_scheme', 'http')}://{host}{path}"


def takes_gzip(environ) -> bool:
    return "gzip" in environ.get("HTTP_ACCEPT_ENCODING", "").lower()


def plain(start_response, status: str, body: bytes):
    start_response(
        status,
        [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("X-Content-Type-Options", "nosniff"),
        ],
    )
    return [body]


def found(start_response, location: str, extra=()):
    """302 to ``location``, an address that is quoted already."""
    start_response("302 Found", [("Location", location), ("Content-Length", "0"), *extra])
    return [b""]


def redirect(start_response, target: str, environ, extra=()):
    """302 to ``target`` (a WSGI path, %-quoted here) with the request's query."""
    query = environ.get("QUERY_STRING", "")
    return found(start_response, url_path(target, safe="/:@!$&'()*+,;=") + (f"?{query}" if query else ""), extra)
