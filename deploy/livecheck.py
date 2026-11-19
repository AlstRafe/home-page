"""Is the public site up, with every page a visitor needs? ``python deploy/livecheck.py [https://name] [--expect SHA]``

Asks the public address (the VM's own name, served by Caddy) for each site's front page and the files
link previews and phones use, the way a first-time visitor's browser would, and says what is missing
(and, as a warning, what was slow). The old address (Tailscale Funnel) must send pages there.
GitHub Actions runs it every few hours and after each push to master (.github/workflows/live.yml),
so a VM that stopped, a Funnel that went off or a deployment that broke a page shows up as a red
run (and GitHub's e-mail) instead of a visitor finding it. Standard library only.

``--expect SHA`` (after a push: the commit pushed) first waits until ``/version.json`` says that commit
of Home Page is live (the VM pulls master every minute and restarts into new code), so the pages are
checked as they are after the push, not before it, and not after a guessed pause. ``--site /val``
waits for that site's commit instead (another repository's workflow can use it the same way).
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import time
import urllib.error
import urllib.request

BASE = "https://haruxera.duckdns.org"
#: The address the links people were sent use (Funnel): it answers a page with a redirect to BASE.
OLD = "https://haruxera.tail5d96b9.ts.net"
#: A page slower than this is reported as a warning, not a failure (the VM has 1/8 of a CPU, so a few
#: seconds happen now and then).
SLOW_SECONDS = 8.0
TIMEOUT = 30
TRIES = 3
#: How long --expect waits for the commit (a pull is at most a minute, a restart about one more).
WAIT_SECONDS = 8 * 60
WAIT_STEP = 10
HEADERS = {"Accept": "text/html,*/*", "Accept-Encoding": "gzip", "Accept-Language": "ja", "User-Agent": "livecheck"}


def fetch(url: str) -> tuple[int, dict, bytes, float]:
    """(status, headers, body, seconds), tried again after a pause when it fails (the VM may be busy)."""
    last: Exception | None = None
    for attempt in range(TRIES):
        start = time.monotonic()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=TIMEOUT) as answer:
                body, status, headers = answer.read(), answer.status, dict(answer.headers)
        except urllib.error.HTTPError as error:
            body, status, headers = error.read(), error.code, dict(error.headers)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last = error
            time.sleep(5 * (attempt + 1))
            continue
        if headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        return status, headers, body, time.monotonic() - start
    raise ConnectionError(f"{url}: {last}")


class _Stay(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # the redirect itself is the answer


def goes(url: str, expected: str) -> list[str]:
    """Whether ``url`` answers with a redirect to ``expected``."""
    opener = urllib.request.build_opener(_Stay)
    start = time.monotonic()
    try:
        opener.open(urllib.request.Request(url, headers=HEADERS), timeout=TIMEOUT)
        return [f"{url}: 転送されません"]
    except urllib.error.HTTPError as error:
        status, location = error.code, error.headers.get("Location", "")
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return [f"{url}: 答えがありません（{error}）"]
    print(f"{status} {time.monotonic() - start:5.2f}s      {url} -> {location}")
    if status not in (301, 302, 307, 308) or location != expected:
        return [f"{url}: {status} {location!r}（{expected} への転送のはず）"]
    return []


def moved(old: str, base: str, path: str = "/news/?q=check") -> list[str]:
    """Whether the old address sends a page to the same path at ``base``."""
    return goes(old + path, base + path)


def live_commit(base: str, site: str = "/") -> str:
    """The commit ``/version.json`` says is live for ``site`` ("" while it cannot tell)."""
    try:
        status, _, body, _ = fetch(base + "/version.json")
        return str(json.loads(body)["versions"].get(site, "")) if status == 200 else ""
    except (ConnectionError, ValueError, KeyError, TypeError, AttributeError):
        return ""


def wait_for(
    base: str, commit: str, site: str = "/", limit: float = WAIT_SECONDS, step: float = WAIT_STEP
) -> list[str]:
    """Waits until ``commit`` of ``site`` is live (a problem when it is not after ``limit`` seconds)."""
    start = time.monotonic()
    while True:
        now = live_commit(base, site)
        seconds = time.monotonic() - start
        if now == commit:
            print(f"反映を確認: {site} は {commit[:7]}（{seconds:.0f} 秒待ちました）")
            return []
        if seconds >= limit:
            return [f"{site}: {commit[:7]} が {limit / 60:.0f} 分たっても反映されません（いま {now[:7] or '不明'}）"]
        print(f"待っています: {site} はまだ {now[:7] or '不明'}（{seconds:.0f} 秒）", flush=True)
        time.sleep(step)


def meta(page: str, name: str) -> str:
    found = re.search(rf'<meta (?:property|name)="{re.escape(name)}" content="([^"]*)"', page)
    return found.group(1) if found else ""


def check(base: str) -> list[str]:
    problems: list[str] = []

    def get(path: str, kind: str, *texts: str) -> tuple[dict, str]:
        try:
            status, headers, body, seconds = fetch(base + path)
        except ConnectionError as error:
            problems.append(f"{path}: 答えがありません（{error}）")
            return {}, ""
        mark = "遅い" if seconds > SLOW_SECONDS else "ok"
        print(f"{status} {seconds:5.2f}s {mark:4} {path}")
        if status != 200:
            problems.append(f"{path}: {status}")
        elif not headers.get("Content-Type", "").startswith(kind):
            problems.append(f"{path}: Content-Type {headers.get('Content-Type')}（{kind} のはず）")
        if seconds > SLOW_SECONDS:
            # a yellow note on the run (GitHub Actions reads this line), not a red run and an e-mail
            print(f"::warning::{path}: {seconds:.1f} 秒かかりました")
        text = body.decode("utf-8", "replace") if kind.startswith(("text/", "application/")) else ""
        for needed in texts:
            if needed not in text:
                problems.append(f"{path}: {needed!r} がありません")
        return headers, text

    headers, page = get("/", "text/html", "<h1>", "/news/", "/infra/", "/val/")
    for name in ("Strict-Transport-Security", "Content-Security-Policy", "X-Content-Type-Options"):
        if name not in headers:
            problems.append(f"/: {name} ヘッダがありません")
    sites = (("/infra/", "CoreLab"), ("/val/", "VAL Tracker"))
    for path, html in (("/", page), *((path, get(path, "text/html", name)[1]) for path, name in sites)):
        image = meta(html, "og:image")
        if not image.startswith(base + "/"):
            problems.append(f"{path}: og:image が公開アドレスの完全な URL ではありません（{image!r}）")
        elif html:
            get(image[len(base) :], "image/png")
    get("/apple-touch-icon.png", "image/png")
    get("/news/", "text/html", "NewsBridge")
    get("/news/manifest.webmanifest", "application/")
    _, version = get("/news/api/version", "application/json", '"version"')
    print(f"News Site: {version.strip()}")
    # VAL Tracker's agents and their pictures come from valorant-api.com and media.valorant-api.com through
    # the VM (saved there once fetched): no pictures means the VM could not reach them.
    _, agents = get("/val/agents", "text/html", "/val/media/")
    picture = re.search(r'src="(/val/media/[^"]+)"', agents)
    if picture:
        get(picture.group(1), "image/png")
    get("/robots.txt", "text/plain", "User-agent")
    # What runs (for --expect), the list as a phone app, and a card's search box (Riot IDs carry a #).
    get("/version.json", "application/json", '"versions"')
    get("/portal.webmanifest", "application/manifest+json", '"icons"')
    problems += goes(base + "/search?site=/val&q=Name%23JP1", "/val/search?q=Name%23JP1")
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python deploy/livecheck.py")
    parser.add_argument("base", nargs="?", default=BASE, help=f"公開アドレス（既定: {BASE}）")
    parser.add_argument("--expect", default="", help="先にこのコミットの反映を待つ（push のあと: github.sha）")
    parser.add_argument("--site", default="/", help='--expect のサイト（既定: "/" = Home Page）')
    args = parser.parse_args(argv)
    base = (args.base or BASE).rstrip("/")
    problems = wait_for(base, args.expect, args.site) if args.expect else []
    problems += check(base)
    if base == BASE:
        problems += moved(OLD, base)
    if problems:
        print("\n問題:\n" + "\n".join(f"- {p}" for p in problems))
        return 1
    print("\nすべて ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
