"""Is the public site up, with every page a visitor needs? ``python deploy/livecheck.py [https://name]``

Asks the public address (Tailscale Funnel) for each site's front page and the files link previews
and phones use, the way a first-time visitor's browser would, and says what is missing (and, as a
warning, what was slow).
GitHub Actions runs it every few hours and after each push to master (.github/workflows/live.yml),
so a VM that stopped, a Funnel that went off or a deployment that broke a page shows up as a red
run (and GitHub's e-mail) instead of a visitor finding it. Standard library only.
"""

from __future__ import annotations

import gzip
import re
import sys
import time
import urllib.error
import urllib.request

BASE = "https://haruxera.tail5d96b9.ts.net"
#: A page slower than this is reported as a warning, not a failure (the VM has 1/8 of a CPU, so a few
#: seconds happen now and then).
SLOW_SECONDS = 8.0
TIMEOUT = 30
TRIES = 3
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
        text = body.decode("utf-8", "replace") if kind.startswith(("text/", "application/json")) else ""
        for needed in texts:
            if needed not in text:
                problems.append(f"{path}: {needed!r} がありません")
        return headers, text

    headers, page = get("/", "text/html", "<h1>", "/news/", "/infra/")
    for name in ("Strict-Transport-Security", "Content-Security-Policy", "X-Content-Type-Options"):
        if name not in headers:
            problems.append(f"/: {name} ヘッダがありません")
    for path, html in (("/", page), ("/infra/", get("/infra/", "text/html", "CoreLab")[1])):
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
    get("/robots.txt", "text/plain", "User-agent")
    return problems


def main(argv: list[str]) -> int:
    base = (argv[0] if argv else BASE).rstrip("/")
    problems = check(base)
    if problems:
        print("\n問題:\n" + "\n".join(f"- {p}" for p in problems))
        return 1
    print("\nすべて ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
