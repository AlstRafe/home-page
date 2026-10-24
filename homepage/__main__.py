"""``python -m homepage [--port 5055] [--demo]``: the index and the folder sites on this PC only (127.0.0.1),
for trying out a change to sites.toml or the design. ``--demo`` adds a stand-in for News Site."""
from __future__ import annotations

import argparse
from wsgiref.simple_server import make_server

from homepage import App, build


def _stand_in(environ, start_response):
    body = "<!doctype html><meta charset=utf-8><title>News Site</title><p>（News Site の代わり）<a href=\"/\">← サイト一覧</a>".encode()
    start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body)))])
    return [body]


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m homepage")
    parser.add_argument("--port", type=int, default=5055)
    parser.add_argument("--demo", action="store_true", help="News Site の代わりを /news に置く")
    args = parser.parse_args()
    apps = []
    if args.demo:
        sample = {"title": "各社が伝えた話題", "note": "取得 12分前", "items": [("台風が沖縄に接近、交通に影響", "/stories/a"),
                                                ("半導体輸出、前年比で増加", "/stories/b"),
                                                ("Kubernetes 新版、スケジューラを改良", "/stories/c")]}
        apps.append(App("news", "/news", _stand_in, "NewsBridge", "翻訳して読み比べるニュース",
                        preview=lambda: sample, disallow=("/api/",), legacy=("/relay/",)))
    portal = build(apps)
    with make_server("127.0.0.1", args.port, portal) as server:
        print(f"http://127.0.0.1:{args.port}/ （終了は Ctrl+C）", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
