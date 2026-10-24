"""The front page ("/"), the sites under their paths, and sites.toml. Run: python -m unittest discover -s tests"""
from __future__ import annotations

import os
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


def call(app, path, method="GET", host=H):
    """One request: (status code, headers dict, body text)."""
    raw, _, query = path.partition("?")
    environ = {"REQUEST_METHOD": method, "PATH_INFO": raw, "QUERY_STRING": query, "SCRIPT_NAME": "",
               "HTTP_HOST": host, "SERVER_NAME": "localhost", "wsgi.url_scheme": "http"}
    seen = {}

    def start_response(status, headers, exc_info=None):
        seen["status"], seen["headers"] = int(status.split()[0]), dict(headers)
    body = b"".join(app(environ, start_response))
    return seen["status"], seen["headers"], body.decode("utf-8", "replace")


def news(environ, start_response):
    """A stand-in for News Site: says where it was called."""
    body = f"news {environ['SCRIPT_NAME']} {environ['PATH_INFO']} {environ['REQUEST_METHOD']}".encode()
    start_response("200 OK", [("Content-Type", "text/plain"), ("Content-Length", str(len(body)))])
    return [body]


NEWS = homepage.App("news", "/news", news, "NewsBridge", "翻訳して読み比べるニュース",
                    preview=lambda: {"note": "取得 5分前", "items": [("台風が接近", "/stories/a"), ("株価が上昇", "/a/7")]},
                    disallow=("/api/",), legacy=("/relay/",))


class HomePageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.game = self.tmp / "Infra Game"
        (self.game / "js").mkdir(parents=True)
        (self.game / ".git").mkdir()
        (self.game / "index.html").write_text('<!doctype html><title>CoreLab</title><body><script src="./js/app.js"></script></body>', encoding="utf-8")
        (self.game / "js" / "app.js").write_text("1;", encoding="utf-8")
        (self.game / ".git" / "config").write_text("[core]", encoding="utf-8")
        (self.game / "README.md").write_text("notes", encoding="utf-8")
        (self.tmp / "secret.js").write_text("2;", encoding="utf-8")
        self.memo = self.tmp / "Memo"
        self.memo.mkdir()
        (self.memo / "index.html").write_text("<!doctype html><title>Memo</title><BODY><p>memo</p></BODY>", encoding="utf-8")
        self.config = self.tmp / "sites.toml"
        self.write('''
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
''')
        self.portal = homepage.build([NEWS], allowed_hosts=lambda host: host in (H, PUBLIC),
                                     visitor_hosts=lambda host: host == PUBLIC, config=self.config)

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
        hidden = ["/infra/.git/config", "/infra/README.md", "/infra/../secret.js", "/infra/%2e%2e/secret.js",
                  "/infra/js", "/infra/nothing.js", "/infra/CLAUDE~1/settings.json", "/infra/.claude/settings.json",
                  "/infra/js\\..\\..\\secret.js"]
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
        self.write(self.config.read_text(encoding="utf-8") + '''
[[site]]
mount = "/memo"
folder = "Memo"
name = "Memo"
''')
        status, _, body = call(self.portal, "/memo/")
        self.assertEqual(status, 200)
        self.assertIn('<a href="/" title="サイト一覧へ戻る"', body)
        self.assertLess(body.index("サイト一覧へ戻る"), body.index("</BODY>"))
        self.assertIn('<a class="open" href="/memo/">Memo を開く', call(self.portal, "/")[2])

    def test_sites_toml_edits_show_without_a_restart_and_mistakes_are_explained_to_the_owner(self):
        self.write(self.config.read_text(encoding="utf-8") + '''
[[site]]
mount = "/memo"
folder = "Memo"
name = "Memo"
accent = "pink"

[[site]]
mount = "/gone"
folder = "Nowhere"
name = "Gone"
''')
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
        self.write(self.config.read_text(encoding="utf-8").replace('home_link = "own"', 'home_link = "own"\npublic = false'))
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
        self.assertEqual((status, headers["Location"]), (308, "/news/a/7?tr=ja"))
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
        self.write('[[site]]\nmount = "/news"\nfolder = "Memo"\nname = "X"\n\n'
                   '[[site]]\nmount = "/Memo"\nfolder = "Memo"\nname = "X"\n\n'
                   '[[site]]\nmount = "/robots.txt"\nfolder = "Memo"\nname = "X"\n\n'
                   '[[site]]\nmount = "/memo"\nfolder = "Memo"\nname = "Memo"\n\n'
                   '[[site]]\nmount = "/memo"\nfolder = "Infra Game"\nname = "Again"\n')
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

    def test_this_folders_own_sites_toml_reads_cleanly(self):
        portal = homepage.build([NEWS])
        problems = [p for p in portal.problems if "index.html がありません" not in p]
        self.assertEqual(problems, [])
        self.assertEqual(portal.sites[0].mount, "/news")


if __name__ == "__main__":
    unittest.main()
