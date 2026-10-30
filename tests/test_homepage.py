"""The front page ("/"), the sites under their paths, and sites.toml. Run: python -m unittest discover -s tests"""

from __future__ import annotations

import gzip
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import homepage

H = "localhost"
PUBLIC = "haruxera.tail1234.ts.net"


def call(app, path, method="GET", host=H, raw=False, **headers):
    """One request: (status code, headers dict, body text, or bytes with raw=True).
    ``headers``: request headers as environ keys (HTTP_IF_NONE_MATCH="...")."""
    target, _, query = path.partition("?")
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": target,
        "QUERY_STRING": query,
        "SCRIPT_NAME": "",
        "HTTP_HOST": host,
        "SERVER_NAME": "localhost",
        "wsgi.url_scheme": "http",
        **headers,
    }
    seen = {}

    def start_response(status, headers, exc_info=None):
        seen["status"], seen["headers"] = int(status.split()[0]), dict(headers)

    body = b"".join(app(environ, start_response))
    return seen["status"], seen["headers"], body if raw else body.decode("utf-8", "replace")


def news(environ, start_response):
    """A stand-in for News Site: says where it was called."""
    body = f"news {environ['SCRIPT_NAME']} {environ['PATH_INFO']} {environ['REQUEST_METHOD']}".encode()
    start_response("200 OK", [("Content-Type", "text/plain"), ("Content-Length", str(len(body)))])
    return [body]


NEWS = homepage.App(
    "news",
    "/news",
    news,
    "NewsBridge",
    "翻訳して読み比べるニュース",
    preview=lambda: {"note": "取得 5分前", "items": [("台風が接近", "/stories/a"), ("株価が上昇", "/a/7")]},
    disallow=("/api/",),
    legacy=("/relay/",),
)


class HomePageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.game = self.tmp / "Infra Game"
        (self.game / "js").mkdir(parents=True)
        (self.game / ".git").mkdir()
        (self.game / "index.html").write_text(
            '<!doctype html><title>CoreLab</title><body><script src="./js/app.js"></script></body>', encoding="utf-8"
        )
        (self.game / "js" / "app.js").write_text("1;", encoding="utf-8")
        (self.game / ".git" / "config").write_text("[core]", encoding="utf-8")
        (self.game / "README.md").write_text("notes", encoding="utf-8")
        (self.tmp / "secret.js").write_text("2;", encoding="utf-8")
        self.memo = self.tmp / "Memo"
        self.memo.mkdir()
        (self.memo / "index.html").write_text(
            "<!doctype html><title>Memo</title><BODY><p>memo</p></BODY>", encoding="utf-8"
        )
        self.config = self.tmp / "sites.toml"
        self.write("""
title = "サイト一覧"
lead = "小さなサイトの入口です。"
points = ["登録不要", "無料"]

[[site]]
app = "news"
description = "ニュースを読み比べる。"
icon = "news"
accent = "red"
tags = ["毎時更新"]

[[site]]
mount = "/infra"
folder = "Infra Game"
name = "CoreLab"
subtitle = "インフラ運用トレーニングゲーム"
icon = "terminal"
accent = "teal"
home_link = "own"
""")
        self.portal = homepage.build(
            [NEWS],
            allowed_hosts=lambda host: host in (H, PUBLIC),
            visitor_hosts=lambda host: host == PUBLIC,
            config=self.config,
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, text: str) -> None:
        self.config.write_text(text, encoding="utf-8")
        # a new modification time even on a coarse clock, and past the portal's once-a-second look
        stamp = time.time() + getattr(self, "_bump", 0)
        self._bump = getattr(self, "_bump", 0) + 2
        os.utime(self.config, (stamp, stamp))
        if hasattr(self, "portal"):
            self.portal._checked = 0.0

    def test_the_index_lists_the_sites_in_order_with_what_they_have_now(self):
        status, headers, page = call(self.portal, "/")
        self.assertEqual(status, 200)
        self.assertIn('<h2><a href="/news/">NewsBridge</a></h2>', page)
        self.assertIn('<h2><a href="/infra/">CoreLab</a></h2>', page)
        self.assertLess(page.index("/news/"), page.index("/infra/"))
        self.assertIn('<p class="sub">翻訳して読み比べるニュース</p>', page)  # the app's own subtitle
        self.assertIn('href="/news/stories/a">台風が接近</a>', page)
        self.assertIn("取得 5分前", page)
        self.assertIn('<a class="open" href="/infra/">CoreLab を開く', page)
        self.assertIn("<li>登録不要</li>", page)
        self.assertIn('class="site accent-teal"', page)
        self.assertIn("<svg", page)  # the icon, inline
        self.assertIn("更新 ", page)  # the folder site's last change
        self.assertNotIn("{{", page)
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertIn('content="http://localhost/"', page)  # og:url
        self.assertEqual(call(self.portal, "/portal.css")[0], 200)
        self.assertEqual(call(self.portal, "/favicon.svg")[1]["Content-Type"], "image/svg+xml")
        self.assertEqual(call(self.portal, "/", host="evil.example")[0], 400)
        self.assertEqual(call(self.portal, "/", method="POST")[0], 405)

    def test_a_folder_site_under_its_path(self):
        self.assertEqual(call(self.portal, "/infra")[1]["Location"], "/infra/")
        status, headers, body = call(self.portal, "/infra/")
        self.assertEqual(status, 200)
        self.assertIn("<title>CoreLab</title>", body)
        self.assertNotIn("サイト一覧", body)  # home_link = "own": the site has its own way back
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        status, headers, _ = call(self.portal, "/infra/js/app.js")
        self.assertEqual((status, headers["Content-Type"]), (200, "text/javascript; charset=utf-8"))
        (self.game / ".claude").mkdir()
        (self.game / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
        hidden = [
            "/infra/.git/config",
            "/infra/README.md",
            "/infra/../secret.js",
            "/infra/%2e%2e/secret.js",
            "/infra/js",
            "/infra/nothing.js",
            "/infra/CLAUDE~1/settings.json",
            "/infra/.claude/settings.json",
            "/infra/js\\..\\..\\secret.js",
        ]
        try:
            (self.game / "linked").symlink_to(self.game / ".claude", target_is_directory=True)
            hidden.append("/infra/linked/settings.json")
        except OSError:  # no symlinks for this Windows account
            pass
        for path in hidden:
            self.assertEqual(call(self.portal, path)[0], 404, path)
        self.assertEqual(call(self.portal, "/infra/", method="POST")[0], 405)
        self.assertEqual(call(self.portal, "/infra/", host="evil.example")[0], 400)

    def test_a_site_without_its_own_way_back_gets_one(self):
        self.write(
            self.config.read_text(encoding="utf-8")
            + """
[[site]]
mount = "/memo"
folder = "Memo"
name = "Memo"
"""
        )
        status, _, body = call(self.portal, "/memo/")
        self.assertEqual(status, 200)
        self.assertIn('<a href="/" title="サイト一覧へ戻る"', body)
        self.assertLess(body.index("サイト一覧へ戻る"), body.index("</BODY>"))
        self.assertIn('<a class="open" href="/memo/">Memo を開く', call(self.portal, "/")[2])

    def test_folder_files_are_sent_gzipped_and_not_again_while_unchanged(self):
        script = self.game / "js" / "app.js"
        script.write_text("var mission = 1;\n" * 400, encoding="utf-8")
        status, headers, body = call(self.portal, "/infra/js/app.js", raw=True, HTTP_ACCEPT_ENCODING="gzip, br")
        self.assertEqual((status, headers["Content-Encoding"], headers["Vary"]), (200, "gzip", "Accept-Encoding"))
        self.assertEqual(gzip.decompress(body), script.read_bytes())
        self.assertLess(len(body), script.stat().st_size // 5)
        self.assertEqual(int(headers["Content-Length"]), len(body))
        status, again, body = call(
            self.portal, "/infra/js/app.js", raw=True, HTTP_ACCEPT_ENCODING="gzip", HTTP_IF_NONE_MATCH=headers["ETag"]
        )
        self.assertEqual((status, body), (304, b""))
        self.assertEqual(again["ETag"], headers["ETag"])
        status, plain, body = call(self.portal, "/infra/js/app.js", raw=True)  # no gzip: another tag
        self.assertEqual(status, 200)
        self.assertNotIn("Content-Encoding", plain)
        self.assertNotEqual(plain["ETag"], headers["ETag"])
        self.assertEqual(body, script.read_bytes())
        script.write_text("var mission = 2;\n" * 400, encoding="utf-8")
        later = time.time() + 5
        os.utime(script, (later, later))
        status, changed, body = call(
            self.portal, "/infra/js/app.js", raw=True, HTTP_ACCEPT_ENCODING="gzip", HTTP_IF_NONE_MATCH=headers["ETag"]
        )
        self.assertEqual(status, 200)
        self.assertNotEqual(changed["ETag"], headers["ETag"])
        self.assertIn(b"mission = 2", gzip.decompress(body))
        self.assertNotIn("Content-Encoding", call(self.portal, "/infra/", HTTP_ACCEPT_ENCODING="gzip")[1])  # small

    def test_a_pages_scripts_are_kept_until_they_change(self):
        script = self.game / "js" / "app.js"
        (self.game / "index.html").write_text(
            '<!doctype html><title>CoreLab</title><link rel="stylesheet" href="./css/app.css">'
            '<link rel="icon" href="data:image/svg+xml,x"><script src="/elsewhere.js"></script>'
            "<script src='js/app.js'></script><script src=\"./js/none.js\"></script><body></body>",
            encoding="utf-8",
        )
        status, headers, page = call(self.portal, "/infra/")
        self.assertEqual((status, headers["Cache-Control"]), (200, "no-cache"))
        address = re.search(r"js/app\.js\?v=(\w+)'", page)
        self.assertIsNotNone(address, page)
        self.assertIn('href="./css/app.css"', page)  # no such file: left as it is
        self.assertIn('href="data:image/svg+xml,x"', page)
        self.assertIn('src="/elsewhere.js"', page)
        self.assertIn('src="./js/none.js"', page)
        status, kept, _ = call(self.portal, f"/infra/js/app.js?v={address.group(1)}")
        self.assertEqual((status, kept["Cache-Control"]), (200, "public, max-age=31536000, immutable"))
        self.assertEqual(call(self.portal, "/infra/js/app.js?v=old")[1]["Cache-Control"], "no-cache")
        self.assertEqual(call(self.portal, "/infra/js/app.js")[1]["Cache-Control"], "no-cache")
        script.write_text("2;", encoding="utf-8")
        later = time.time() + 5
        os.utime(script, (later, later))
        status, again, page = call(self.portal, "/infra/", HTTP_IF_NONE_MATCH=headers["ETag"])
        self.assertEqual(status, 200)  # the page names the new version
        self.assertNotEqual(again["ETag"], headers["ETag"])
        self.assertNotIn(f"v={address.group(1)}", page)
        self.assertEqual(call(self.portal, f"/infra/js/app.js?v={address.group(1)}")[1]["Cache-Control"], "no-cache")

    def test_a_python_sites_preview_is_made_once_a_minute_in_the_background(self):
        made = []
        news_app = homepage.App(
            "news",
            "/news",
            news,
            "NewsBridge",
            preview=lambda lang: made.append(lang) or {"items": [(f"story {len(made)}", "/a/1")]},
        )
        portal = homepage.build([news_app], config=self.config)
        self.assertIn("story 1", call(portal, "/")[2])
        self.assertIn("story 1", call(portal, "/")[2])
        self.assertEqual(made, ["ja"])
        site = next(item for item in portal.sites if item.mount == "/news")
        site._kept["ja"] = (time.monotonic() - homepage.PREVIEW_SECONDS - 1, site._kept["ja"][1])
        self.assertIn("story 1", call(portal, "/")[2])  # at once, the old one
        for _ in range(100):
            if site._kept["ja"][1]["items"][0][0] == "story 2":
                break
            time.sleep(0.02)
        self.assertIn("story 2", call(portal, "/")[2])
        portal.warm().join(5)
        self.assertEqual(sorted(made), sorted(["ja", "ja", "ko", "en-GB", "zh-TW"]))

    def test_the_index_is_sent_gzipped_and_the_folder_sites_date_skips_dot_folders(self):
        status, headers, body = call(self.portal, "/", raw=True, HTTP_ACCEPT_ENCODING="gzip, deflate, br")
        self.assertEqual((status, headers["Content-Encoding"]), (200, "gzip"))
        self.assertIn(b"<h1>", gzip.decompress(body))
        self.assertEqual(headers["Vary"], "Accept-Encoding, Cookie, Accept-Language")
        self.assertNotIn("Content-Encoding", call(self.portal, "/")[1])
        css = re.search(r'portal\.css\?v=(\w+)"', gzip.decompress(body).decode()).group(1)
        self.assertEqual(
            call(self.portal, f"/portal.css?v={css}")[1]["Cache-Control"], "public, max-age=31536000, immutable"
        )
        old = time.time() - 86400 * 400
        for file in self.game.rglob("*"):
            os.utime(file, (old, old))
        later = time.time() + 86400 * 30
        os.utime(self.game / ".git" / "config", (later, later))
        files = homepage.StaticFiles(self.game)
        self.assertLess(files.newest().timestamp(), time.time() - 86400 * 300)

    def test_a_folder_site_shows_what_it_has_from_its_own_json(self):
        (self.game / "portal.json").write_text(
            '{"title": "すぐ遊べるミッション", "items": [["初日の当番", "/#/play/basics-01"], '
            '["外へのリンク", "https://example.com/"], ["はじめてのコンテナ", "/#/play/docker-01"]]}',
            encoding="utf-8",
        )
        self.write(
            self.config.read_text(encoding="utf-8").replace(
                'home_link = "own"', 'home_link = "own"\npreview = "portal.json"'
            )
        )
        page = call(self.portal, "/")[2]
        self.assertIn('<p class="now-head">すぐ遊べるミッション<span>更新 ', page)
        self.assertIn('<a href="/infra/#/play/basics-01">初日の当番</a>', page)
        self.assertIn('<a href="/infra/#/play/docker-01">はじめてのコンテナ</a>', page)
        self.assertNotIn("example.com", page)  # only paths of the site itself
        (self.game / "portal.json").write_text("{broken", encoding="utf-8")
        later = time.time() + 5
        os.utime(self.game / "portal.json", (later, later))
        status, _, page = call(self.portal, "/")
        self.assertEqual(status, 200)
        self.assertIn('<a href="/infra/">CoreLab</a>', page)
        self.assertNotIn("初日の当番", page)
        self.write(self.config.read_text(encoding="utf-8").replace('"portal.json"', '"../secret.js"'))
        self.assertIn("preview はそのフォルダの中の .json", call(self.portal, "/")[2])

    def test_sites_toml_edits_show_without_a_restart_and_mistakes_are_explained_to_the_owner(self):
        self.write(
            self.config.read_text(encoding="utf-8")
            + """
[[site]]
mount = "/memo"
folder = "Memo"
name = "Memo"
accent = "pink"

[[site]]
mount = "/gone"
folder = "Nowhere"
name = "Gone"
"""
        )
        page = call(self.portal, "/")[2]
        self.assertNotIn("/memo/", page)
        self.assertIn("3 番目のサイト: accent は", page)
        self.assertIn("4 番目のサイト:", page)
        self.assertNotIn("/gone/", page)
        self.assertIn("このPCの持ち主向け", page)
        self.assertNotIn("このPCの持ち主向け", call(self.portal, "/", host=PUBLIC)[2])
        self.write("title = [broken")
        page = call(self.portal, "/")[2]
        self.assertIn("sites.toml を読めませんでした", page)
        self.assertIn("/infra/", page)  # the last good list
        self.assertNotIn("読めませんでした", call(self.portal, "/", host=PUBLIC)[2])

    def test_a_site_kept_from_the_public_name(self):
        self.write(
            self.config.read_text(encoding="utf-8").replace('home_link = "own"', 'home_link = "own"\npublic = false')
        )
        owner = call(self.portal, "/")[2]
        self.assertIn("/infra/", owner)
        self.assertIn("非公開", owner)
        visitor = call(self.portal, "/", host=PUBLIC)[2]
        self.assertNotIn("/infra/", visitor)
        self.assertIn("サイト 1 件", visitor)
        self.assertEqual(call(self.portal, "/infra/", host=PUBLIC)[0], 404)
        self.assertEqual(call(self.portal, "/infra/")[0], 200)

    def test_the_server_app_and_the_addresses_from_before_the_portal(self):
        self.assertEqual(call(self.portal, "/news/a/7?tr=ja")[2], "news /news /a/7 GET")
        self.assertEqual(call(self.portal, "/news")[1]["Location"], "/news/")
        status, headers, _ = call(self.portal, "/a/7?tr=ja")
        self.assertEqual((status, headers["Location"]), (302, "/news/a/7?tr=ja"))  # not kept: /memo may come later
        self.assertEqual(call(self.portal, "/relay/v1/ping", method="POST")[2], "news  /relay/v1/ping POST")
        self.assertEqual(call(self.portal, "/api/saved", method="POST")[2], "news  /api/saved POST")
        robots = call(self.portal, "/robots.txt")[2]
        self.assertEqual(robots, "User-agent: *\nDisallow: /news/api/\nDisallow: /relay/\n")

    def test_an_app_missing_from_sites_toml_is_still_served_and_one_not_provided_is_left_out(self):
        self.write('[[site]]\nmount = "/infra"\nfolder = "Infra Game"\nname = "CoreLab"\n')
        page = call(self.portal, "/")[2]
        self.assertIn('<a href="/news/">NewsBridge</a>', page)
        self.assertLess(page.index("/infra/"), page.index("/news/"))
        alone = homepage.build([], config=self.config)  # Home Page on its own: no News Site
        self.write('[[site]]\napp = "news"\n\n[[site]]\nmount = "/infra"\nfolder = "Infra Game"\nname = "CoreLab"\n')
        alone._checked = 0.0
        page = call(alone, "/")[2]
        self.assertNotIn("/news/", page)
        self.assertIn("サイト 1 件", page)
        self.assertEqual(call(alone, "/a/7")[0], 404)

    def test_mounts_that_would_clash_are_refused(self):
        self.write(
            '[[site]]\nmount = "/news"\nfolder = "Memo"\nname = "X"\n\n'
            '[[site]]\nmount = "/Memo"\nfolder = "Memo"\nname = "X"\n\n'
            '[[site]]\nmount = "/robots.txt"\nfolder = "Memo"\nname = "X"\n\n'
            '[[site]]\nmount = "/memo"\nfolder = "Memo"\nname = "Memo"\n\n'
            '[[site]]\nmount = "/memo"\nfolder = "Infra Game"\nname = "Again"\n'
        )
        page = call(self.portal, "/")[2]
        for number in (1, 2, 3, 5):
            self.assertIn(f"{number} 番目のサイト", page)
        self.assertIn('<a href="/memo/">Memo</a>', page)
        self.assertEqual(call(self.portal, "/news/x")[2], "news /news /x GET")

    def test_a_failing_preview_never_breaks_the_index(self):
        broken = homepage.App("news", "/news", news, "NewsBridge", preview=lambda: 1 / 0)
        portal = homepage.build([broken], config=self.config)
        status, _, page = call(portal, "/")
        self.assertEqual(status, 200)
        self.assertIn('<a href="/news/">NewsBridge</a>', page)
        self.assertNotIn('class="now"', page)

    def test_one_language_for_every_site_chosen_by_the_visitor(self):
        status, headers, _ = call(self.portal, "/news/a/7?tr=ja&lang=ko")
        self.assertEqual((status, headers["Location"]), (302, "/news/a/7?tr=ja"))
        self.assertIn("lang=ko; Path=/;", headers["Set-Cookie"])
        self.assertEqual(call(self.portal, "/?lang=en-GB")[1]["Location"], "/")
        self.assertEqual(call(self.portal, "/infra/?lang=zh-TW")[1]["Location"], "/infra/")
        self.assertEqual(call(self.portal, "/?lang=fr")[0], 200)  # not one of ours: no choice
        self.assertIn("Secure", call(self.portal, "/?lang=ko", **{"wsgi.url_scheme": "https"})[1]["Set-Cookie"])
        self.write(
            self.config.read_text(encoding="utf-8").replace(
                'home_link = "own"',
                'home_link = "own"\n\n[site.ko]\nsubtitle = "인프라 운영 트레이닝 게임"\ntags = ["설치 불필요"]',
            )
            + '\n[ko]\ntitle = "사이트 목록"\npoints = ["무료"]\n'
        )
        status, headers, page = call(self.portal, "/", HTTP_COOKIE="lang=ko")
        self.assertIn('<html lang="ko">', page)
        self.assertIn("<h1>사이트 목록</h1>", page)
        self.assertIn("<li>무료</li>", page)
        self.assertIn("小さなサイトの入口です。", page)  # a text without a translation stays Japanese
        self.assertIn('<p class="sub">인프라 운영 트레이닝 게임</p>', page)
        self.assertIn("<li>설치 불필요</li>", page)
        self.assertIn("CoreLab 열기", page)
        self.assertIn("사이트 2개", page)
        self.assertIn('<a href="?lang=ko" lang="ko" hreflang="ko" aria-current="true">한국어</a>', page)
        self.assertIn('<a href="?lang=en-GB" lang="en-GB" hreflang="en-GB">English (UK)</a>', page)
        self.assertIn("Cookie", headers["Vary"])
        self.assertIn('<p class="sub">翻訳して読み比べるニュース</p>', page)  # no [site.ko] for News: its own
        english = call(self.portal, "/", HTTP_ACCEPT_LANGUAGE="en-US,en;q=0.9,ja;q=0.5")[2]
        self.assertIn('<html lang="en-GB">', english)
        self.assertIn("Open CoreLab", english)
        self.assertIn("2 sites", english)
        self.assertIn('<html lang="ja">', call(self.portal, "/", HTTP_COOKIE="lang=ja", HTTP_ACCEPT_LANGUAGE="ko")[2])
        self.write(self.config.read_text(encoding="utf-8") + '\n[en-GB]\npoints = "Free"\n')
        self.assertIn("[en-GB] の points は文字列の並び", call(self.portal, "/")[2])

    def test_the_browsers_languages_decide_until_the_visitor_chooses(self):
        from homepage import i18n

        cases = {
            "": "ja",
            "ja,en;q=0.8": "ja",
            "ko-KR,ko;q=0.9": "ko",
            "zh-TW,zh;q=0.9": "zh-TW",
            "zh-CN": "zh-TW",
            "en-US": "en-GB",
            "fr-FR,fr;q=0.9": "en-GB",
            "fr,ko;q=0.5,ja;q=0.8": "ja",
            "en;q=0,ko": "ko",
        }
        for header, lang in cases.items():
            self.assertEqual(i18n.from_browser(header), lang, header)
        self.assertEqual(i18n.chosen({"HTTP_COOKIE": "lang=zh-TW; other=1", "HTTP_ACCEPT_LANGUAGE": "ko"}), "zh-TW")
        self.assertEqual(i18n.chosen({"HTTP_COOKIE": "lang=xx", "HTTP_ACCEPT_LANGUAGE": "ko"}), "ko")

    def test_previews_and_the_way_back_in_the_visitors_language(self):
        seen = []
        news_app = homepage.App(
            "news",
            "/news",
            news,
            "NewsBridge",
            preview=lambda lang: seen.append(lang) or {"note": f"note-{lang}", "items": [("x", "/a/1")]},
        )
        portal = homepage.build([news_app], config=self.config)
        self.assertIn("note-zh-TW", call(portal, "/", HTTP_COOKIE="lang=zh-TW")[2])
        self.assertEqual(seen, ["zh-TW"])
        (self.game / "portal.json").write_text(
            '{"title": {"ja": "すぐ遊べるミッション", "en-GB": "Missions to play now"}, '
            '"items": [[{"ja": "初日の当番", "ko": "첫날 당번"}, "/#/play/basics-01"]]}',
            encoding="utf-8",
        )
        self.write(
            self.config.read_text(encoding="utf-8").replace(
                'home_link = "own"', 'home_link = "own"\npreview = "portal.json"'
            )
        )
        self.assertIn(
            '<p class="now-head">Missions to play now<span>Updated ',
            call(self.portal, "/", HTTP_COOKIE="lang=en-GB")[2],
        )
        korean = call(self.portal, "/", HTTP_COOKIE="lang=ko")[2]
        self.assertIn(">첫날 당번</a>", korean)
        self.assertIn('<p class="now-head">すぐ遊べるミッション<span>업데이트 ', korean)
        self.write(
            self.config.read_text(encoding="utf-8") + '\n[[site]]\nmount = "/memo"\nfolder = "Memo"\nname = "Memo"\n'
        )
        status, headers, body = call(self.portal, "/memo/", HTTP_COOKIE="lang=en-GB")
        self.assertIn('title="Back to all sites"', body)
        self.assertIn("All sites</a>", body)
        self.assertNotEqual(headers["ETag"], call(self.portal, "/memo/")[1]["ETag"])
        self.assertIn("Cookie", headers["Vary"])

    def test_light_or_dark_is_chosen_with_the_button_and_shared_with_the_sites(self):
        status, headers, page = call(self.portal, "/")
        self.assertIn('<button type="button" class="theme" id="theme" title="ダークモード: 自動 → オフ → オン">', page)
        for words in ("ダークモード 自動", "ダークモード オフ", "ダークモード オン"):
            self.assertIn(f'<span class="words">{words}</span>', page)
        # the script that applies and saves the choice (localStorage "theme", as News Site and CoreLab) runs
        # in <head>, before the page is painted, and the CSP allows exactly it
        self.assertLess(page.index(f"<script>{homepage.THEME_SCRIPT}</script>"), page.index("<body>"))
        self.assertIn('localStorage.getItem("theme")', homepage.THEME_SCRIPT)
        self.assertIn(f"script-src {homepage.THEME_HASH};", headers["Content-Security-Policy"])
        korean = call(self.portal, "/", HTTP_COOKIE="lang=ko")[2]
        self.assertIn('title="다크 모드: 자동 → 끔 → 켬"', korean)
        self.assertIn('<span class="words">다크 모드 켬</span>', korean)
        english = call(self.portal, "/", HTTP_COOKIE="lang=en-GB")[2]
        self.assertIn('<span class="words">Dark mode: auto</span>', english)
        missing = call(self.portal, "/infra/nothing.html", HTTP_ACCEPT="text/html")[2]
        self.assertIn(f"<script>{homepage.THEME_SCRIPT}</script>", missing)  # a 404 is in the chosen theme too

    def test_a_missing_page_shows_the_way_back_to_browsers(self):
        status, headers, page = call(
            self.portal, "/infra/nothing.html", HTTP_ACCEPT="text/html,*/*", HTTP_COOKIE="lang=ko"
        )
        self.assertEqual(status, 404)
        self.assertIn('<html lang="ko">', page)
        self.assertIn("페이지를 찾을 수 없습니다", page)
        self.assertIn('<a class="open" href="/infra/">CoreLab 첫 화면으로</a>', page)
        self.assertIn('href="/"><span class="arrow-back" aria-hidden="true">←</span>사이트 목록</a>', page)
        self.assertEqual(call(self.portal, "/infra/nothing.js")[2], "Not Found")  # not a browser page
        alone = homepage.build([], config=self.config)
        status, _, page = call(alone, "/nothing", HTTP_ACCEPT="text/html")
        self.assertEqual(status, 404)
        self.assertIn("ページが見つかりません", page)
        self.assertNotIn("のトップへ", page)

    def test_link_previews_and_the_home_screen_icon(self):
        status, headers, page = call(self.portal, "/", host=PUBLIC, **{"wsgi.url_scheme": "https"})
        self.assertEqual(status, 200)
        image = re.search(r'<meta property="og:image" content="(https://[^"]+)">', page)
        self.assertIsNotNone(image, page)
        self.assertTrue(image.group(1).startswith(f"https://{PUBLIC}/og.png?v="))
        self.assertIn('<meta name="twitter:card" content="summary_large_image">', page)
        self.assertIn('<meta property="og:image:alt" content="サイト一覧: NewsBridge · CoreLab">', page)
        touch = re.search(r'<link rel="apple-touch-icon" href="(/apple-touch-icon\.png\?v=\w+)">', page)
        self.assertIsNotNone(touch, page)
        for address, size in ((image.group(1).split(PUBLIC)[1], (1200, 630)), (touch.group(1), (180, 180))):
            status, headers, body = call(self.portal, address, raw=True)
            self.assertEqual((status, headers["Content-Type"]), (200, "image/png"), address)
            self.assertEqual(headers["Cache-Control"], "public, max-age=31536000, immutable")
            self.assertEqual(body[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual((int.from_bytes(body[16:20]), int.from_bytes(body[20:24])), size)  # IHDR
        self.assertEqual(call(self.portal, "/apple-touch-icon.png")[1]["Cache-Control"], "public, max-age=86400")

    def test_a_folder_sites_relative_share_links_are_completed(self):
        (self.game / "og.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (self.game / "index.html").write_text(
            '<!doctype html><title>CoreLab</title><meta property="og:url" content="./">'
            '<meta property="og:image" content="og.png"><meta property="og:title" content="CoreLab">'
            '<meta property="og:image" content="https://example.com/x.png"><body>' + "x" * 2000 + "</body>",
            encoding="utf-8",
        )
        self.write(self.config.read_text(encoding="utf-8").replace('home_link = "own"\n', ""))
        page = call(self.portal, "/infra/", host=PUBLIC, **{"wsgi.url_scheme": "https"})[2]
        self.assertIn(f'<meta property="og:url" content="https://{PUBLIC}/infra/">', page)
        self.assertIn(f'<meta property="og:image" content="https://{PUBLIC}/infra/og.png">', page)
        self.assertIn('<meta property="og:image" content="https://example.com/x.png">', page)  # full already
        self.assertIn("サイト一覧へ戻る", page)  # and the way back still comes
        status, headers, body = call(self.portal, "/infra/", raw=True, HTTP_ACCEPT_ENCODING="gzip")
        self.assertEqual((status, headers["Content-Encoding"]), (200, "gzip"))
        self.assertIn(b'content="http://localhost/infra/og.png"', gzip.decompress(body))
        self.assertNotEqual(call(self.portal, "/infra/", host=PUBLIC)[1]["ETag"], headers["ETag"].replace("-gz", ""))
        for name in range(homepage.StaticFiles.GZIP_KEPT + 5):  # any *.ts.net name reaches the server
            call(self.portal, "/infra/", host=f"n{name}.ts.net", HTTP_ACCEPT_ENCODING="gzip")
        self.assertLessEqual(len(self.portal.sites[1].files._gzipped), homepage.StaticFiles.GZIP_KEPT)

    def test_every_answer_says_what_the_browser_may_not_do(self):
        for path in ("/", "/portal.css", "/og.png", "/infra/", "/infra/js/app.js"):
            headers = call(self.portal, path)[1]
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff", path)
            self.assertEqual(headers["X-Frame-Options"], "DENY", path)
            self.assertEqual(headers["Cross-Origin-Opener-Policy"], "same-origin", path)
            self.assertIn("camera=()", headers["Permissions-Policy"], path)
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"], path)

    def test_this_folders_own_sites_toml_reads_cleanly(self):
        from dataclasses import replace

        portal = homepage.build([replace(NEWS, key="/news")])  # as the server loads the Python site
        problems = [p for p in portal.problems if "index.html がありません" not in p]
        self.assertEqual(problems, [])
        self.assertEqual(portal.sites[0].mount, "/news")


if __name__ == "__main__":
    unittest.main()
