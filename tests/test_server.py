"""The server (homepage/server.py) and launcher.py, without starting either. Run: python -m unittest discover -s tests"""

from __future__ import annotations

import http.client
import importlib.util
import io
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_homepage import call

import homepage
from homepage import owner, server

FACTORY = """
def site(mount, host):
    def app(environ, start_response):
        body = f"{environ['SCRIPT_NAME']} {environ['PATH_INFO']}".encode()
        start_response("200 OK", [("Content-Type", "text/plain"), ("Content-Length", str(len(body)))])
        return [body]
    return {"app": app, "name": "Shop", "subtitle": "a shop", "disallow": ["/api/"], "version": lambda: "v1",
            "preview": lambda: {"items": [("today", "/today")]}, "host": host}


def broken(mount, host):
    raise RuntimeError("no database")
"""


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "Shop" / "shopsite").mkdir(parents=True)
        (self.tmp / "Shop" / "shopsite" / "__init__.py").write_text(FACTORY, encoding="utf-8")
        self.config = self.tmp / "sites.toml"
        self.config.write_text(
            """title = "x"

[server]
port = 5099
listen = "local"
hosts = ["MyPC.local"]

[[site]]
mount = "/shop"
python = "Shop"
entry = "shopsite:site"
description = "Buy things."

[[site]]
mount = "/broken"
python = "Shop"
entry = "shopsite:broken"

[[site]]
mount = "/nowhere"
python = "Nowhere"
entry = "nothing:site"
""",
            encoding="utf-8",
        )

    def tearDown(self):
        sys.modules.pop("shopsite", None)
        while str(self.tmp / "Shop") in sys.path:
            sys.path.remove(str(self.tmp / "Shop"))
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_settings_and_what_restarts_the_server(self):
        settings = server.read_settings(self.config)
        self.assertEqual((settings.port, settings.listen, settings.hosts), (5099, "local", ("mypc.local",)))
        self.assertEqual([entry["mount"] for entry in settings.python_sites], ["/shop", "/broken", "/nowhere"])
        self.assertEqual(server.addresses(settings), ["127.0.0.1"])
        before = server.settings_stamp(self.config)
        text = self.config.read_text(encoding="utf-8")
        self.config.write_text(text.replace("Buy things.", "Buy more things."), encoding="utf-8")
        self.assertEqual(server.settings_stamp(self.config), before)  # texts show without a restart
        self.config.write_text(text.replace("port = 5099", "port = 5098"), encoding="utf-8")
        self.assertNotEqual(server.settings_stamp(self.config), before)
        self.config.write_text("port = [", encoding="utf-8")
        self.assertIsNone(server.settings_stamp(self.config))  # half written: no restart for it
        self.assertEqual(server.read_settings(self.config).port, 5000)

    def test_code_changes_are_seen(self):
        package = self.tmp / "Shop" / "shopsite"
        before = server.code_stamp(package)
        (package / "__init__.py").write_text(FACTORY + "\n# changed\n", encoding="utf-8")
        self.assertNotEqual(server.code_stamp(package), before)

    def test_python_sites_are_loaded_and_the_failures_explained(self):
        host = {"port": 5099, "addresses": ["127.0.0.1"], "names": ["localhost"], "urls": ["http://127.0.0.1:5099/"]}
        apps, notes = server.load_python_sites(server.read_settings(self.config).python_sites, self.tmp, host)
        self.assertEqual([app.mount for app in apps], ["/shop"])
        shop = apps[0]
        self.assertEqual(
            (shop.key, shop.name, shop.subtitle, shop.disallow, shop.version()),
            ("/shop", "Shop", "a shop", ("/api/",), "v1"),
        )
        self.assertEqual(len(notes), 2)
        self.assertIn("no database", notes[0])
        self.assertIn("Nowhere", notes[1])
        portal = homepage.build(apps, config=self.config, notes=notes)
        page = call(portal, "/")[2]
        self.assertIn('<a href="/shop/">Shop</a>', page)
        self.assertIn("Buy things.", page)
        self.assertIn('href="/shop/today">today</a>', page)
        self.assertIn("/broken を読み込めませんでした", page)
        self.assertEqual(call(portal, "/shop/a")[2], "/shop /a")
        self.assertEqual(call(portal, "/robots.txt")[2], "User-agent: *\nDisallow: /shop/api/\n")

    def test_names_and_the_public_name(self):
        names = server.Hosts(["100.70.1.2", "haruxera.tail1234.ts.net", "HARUXERA", None])
        for host in ("localhost:5000", "127.0.0.1:5000", "[::1]:5000", "100.70.1.2:5000", "haruxera", "x.tail9.ts.net"):
            self.assertTrue(names.allowed(host), host)
        self.assertFalse(names.allowed("evil.example"))
        self.assertTrue(names.visitor("x.tail9.ts.net"))
        self.assertFalse(names.visitor("localhost"))
        seen = {}

        def app(environ, start_response):
            seen["scheme"] = environ["wsgi.url_scheme"]
            start_response("200 OK", [])
            return [b""]

        wrapped = server.Public(app, names.visitor)
        _, headers, _ = call(wrapped, "/", host="x.tail9.ts.net")
        self.assertEqual((seen["scheme"], headers["X-Robots-Tag"]), ("https", "noindex"))
        self.assertIn("max-age=", headers["Strict-Transport-Security"])
        _, headers, _ = call(wrapped, "/")
        self.assertEqual(seen["scheme"], "http")
        self.assertNotIn("X-Robots-Tag", headers)

    def test_the_machines_own_public_domain_is_a_visitors_address(self):
        text = self.config.read_text(encoding="utf-8")
        self.assertEqual(
            (server.read_settings(self.config).public, server.read_settings(self.config).moved_to), ((), "")
        )
        self.config.write_text(
            text.replace(
                "[server]\n",
                '[server]\npublic = [" Sites.DuckDNS.org.", "", 5, "sites.duckdns.org:443"]\nmoved_to = "sites.duckdns.org"\n',
            ),
            encoding="utf-8",
        )
        settings = server.read_settings(self.config)
        self.assertEqual((settings.public, settings.moved_to), (("sites.duckdns.org",), "sites.duckdns.org"))
        self.config.write_text(
            text.replace("[server]\n", '[server]\nmoved_to = "elsewhere.example"\n'), encoding="utf-8"
        )
        self.assertEqual(server.read_settings(self.config).moved_to, "")  # only to a name it serves
        names = server.Hosts(["100.70.1.2", "haruxera"], ["sites.duckdns.org", "haruxera"])
        self.assertTrue(names.allowed("sites.duckdns.org"))
        self.assertTrue(names.visitor("SITES.duckdns.org:443"))
        self.assertFalse(names.visitor("haruxera"))  # an own name never becomes a visitor's
        self.assertNotIn("sites.duckdns.org", names.names)  # the sites are told to trust the own names only
        self.assertFalse(names.allowed("other.duckdns.org"))
        seen = {}

        def app(environ, start_response):
            seen.update(scheme=environ["wsgi.url_scheme"], visitor=environ.get(server.VISITOR_KEY))
            start_response("200 OK", [])
            return [b""]

        wrapped = server.Public(app, names.visitor)
        call(wrapped, "/news/", host="sites.duckdns.org")
        self.assertEqual(seen, {"scheme": "https", "visitor": True})
        call(wrapped, "/news/", host="haruxera")
        self.assertEqual(seen, {"scheme": "http", "visitor": None})

    def test_the_old_public_address_sends_pages_on_to_the_new_one(self):
        names = server.Hosts(["haruxera"], ["sites.duckdns.org"])
        served = []

        def app(environ, start_response):
            served.append((environ["HTTP_HOST"], environ["REQUEST_METHOD"]))
            start_response("200 OK", [])
            return [b""]

        wrapped = server.Public(app, names.visitor, "sites.duckdns.org")
        status, headers, _ = call(wrapped, "/news/a/1?lang=ko", host="haruxera.tail1234.ts.net")
        self.assertEqual((status, headers["Location"]), (307, "https://sites.duckdns.org/news/a/1?lang=ko"))
        self.assertIn("max-age=", headers["Strict-Transport-Security"])
        path = "/news/?q=" + "東京".encode().decode("latin-1")  # WSGI: the path's bytes as latin-1
        status, headers, _ = call(wrapped, path.replace("?q=", "x"), "HEAD", host="haruxera.tail1234.ts.net")
        self.assertEqual(headers["Location"], "https://sites.duckdns.org/news/x%E6%9D%B1%E4%BA%AC")
        self.assertEqual(
            call(wrapped, "", host="haruxera.tail1234.ts.net")[1]["Location"], "https://sites.duckdns.org/"
        )
        self.assertEqual(call(wrapped, "/news/relay/translate", "POST", host="haruxera.tail1234.ts.net")[0], 200)
        self.assertEqual(call(wrapped, "/", host="sites.duckdns.org")[0], 200)
        self.assertEqual(call(wrapped, "/", host="haruxera")[0], 200)  # the owner's own names stay as they are
        self.assertEqual(
            served,
            [
                ("haruxera.tail1234.ts.net", "POST"),
                ("sites.duckdns.org", "GET"),
                ("haruxera", "GET"),
            ],
        )


@unittest.skipUnless(importlib.util.find_spec("waitress"), "waitress is not installed (CI installs it)")
class RestartTests(unittest.TestCase):
    """A restart (new code, settings) lets the answers in flight go out and ends at once."""

    def test_a_restart_finishes_the_requests_being_answered_and_ends_soon(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        started, asked = threading.Event(), threading.Event()

        def app(environ, start_response):
            if environ["PATH_INFO"] == "/slow":
                started.set()
                time.sleep(0.6)
            body = environ["PATH_INFO"].encode() * 2000
            start_response("200 OK", [("Content-Type", "text/plain"), ("Content-Length", str(len(body)))])
            return [body]

        result = {}

        def run():
            result["code"] = server.serve(
                app,
                ["127.0.0.1"],
                port,
                supervised=True,
                reason=lambda rounds: "テスト" if asked.is_set() else None,
                poll_seconds=0.05,
                drain_seconds=5,
            )

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        for _ in range(100):
            try:
                idle = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                idle.request("GET", "/quick")
                break
            except OSError:
                time.sleep(0.05)
        self.assertEqual(idle.getresponse().read(), b"/quick" * 2000)  # left open: an idle keep-alive one
        slow = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        slow.request("GET", "/slow")
        self.assertTrue(started.wait(5))
        asked.set()
        began = time.monotonic()
        self.assertEqual(slow.getresponse().read(), b"/slow" * 2000)  # answered in full
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result["code"], server.RESTART_EXIT_CODE)
        self.assertLess(time.monotonic() - began, 3)  # not held up by the idle connection
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
        idle.close()
        slow.close()


class OwnerTests(unittest.TestCase):
    """持ち主のログイン: homepage/owner.py and the server's /owner."""

    PUBLIC = "sites.duckdns.org"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.file = self.tmp / "state" / "owner.json"
        self.cost, owner.SCRYPT = owner.SCRYPT, {"n": 2**4, "r": 8, "p": 1}  # the real cost is slow on purpose
        self.seen = []

        def app(environ, start_response):
            self.seen.append(
                (environ.get(server.VISITOR_KEY), environ.get(server.OWNER_KEY), environ.get("HTTP_COOKIE"))
            )
            start_response("200 OK", [])
            return [b""]

        self.owner = owner.Owner(self.file)
        self.public = server.Public(app, server.Hosts(["haruxera"], [self.PUBLIC]).visitor, owner=self.owner)

    def tearDown(self):
        owner.SCRYPT = self.cost
        shutil.rmtree(self.tmp, ignore_errors=True)

    def post(self, form, **headers):
        body = urlencode(form).encode()
        return call(
            self.public,
            "/owner",
            "POST",
            host=self.PUBLIC,
            CONTENT_LENGTH=str(len(body)),
            CONTENT_TYPE="application/x-www-form-urlencoded",
            **{"wsgi.input": io.BytesIO(body), "HTTP_ORIGIN": f"https://{self.PUBLIC}", **headers},
        )

    def test_a_password_is_kept_as_a_hash_and_checked_with_a_limit_for_everyone(self):
        self.assertFalse(self.owner.ready)
        self.assertEqual(self.owner.login("whatever"), "off")
        with self.assertRaises(ValueError):
            owner.write("short", self.file)
        owner.write("correct horse battery", self.file)
        self.assertNotIn("correct horse", self.file.read_text(encoding="utf-8"))
        if sys.platform != "win32":
            self.assertEqual(self.file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.owner.login("correct horse battery", now=1000), "ok")
        for second in range(5):
            self.assertEqual(self.owner.login("wrong password!", now=1000 + second), "wrong")
        self.assertEqual(self.owner.login("correct horse battery", now=1010), "busy")  # even the right one
        self.assertEqual(self.owner.login("correct horse battery", now=1061), "ok")  # a minute later
        for second in range(15):
            self.owner.login("wrong password!", now=1100 + second * 13)
        self.assertEqual(self.owner.login("correct horse battery", now=1400), "busy")  # 20 in an hour
        self.assertEqual(self.owner.login("correct horse battery", now=1000 + 3601), "ok")

    def test_the_cookie_is_signed_and_a_new_password_signs_every_device_out(self):
        owner.write("correct horse battery", self.file)
        name, value = self.owner.cookie(now=5000)
        self.assertEqual(name, "Set-Cookie")
        for part in ("__Host-owner=", "Path=/", "Secure", "HttpOnly", "SameSite=Lax"):
            self.assertIn(part, value)
        cookie = value.split(";", 1)[0]
        self.assertTrue(self.owner.signed_in({"HTTP_COOKIE": f"lang=ko; {cookie}"}, now=5001))
        self.assertTrue(self.owner.signed_in({"HTTP_COOKIE": f'x="a b; {cookie}'}, now=5001))  # after a broken one
        issued, signature = cookie.split("=", 1)[1].split(".")
        self.assertFalse(self.owner.signed_in({"HTTP_COOKIE": f"__Host-owner={int(issued) + 1}.{signature}"}, now=5001))
        self.assertFalse(self.owner.signed_in({"HTTP_COOKIE": cookie}, now=5000 + owner.SECONDS + 1))
        self.assertFalse(self.owner.signed_in({"HTTP_COOKIE": "__Host-owner=garbage"}, now=5001))
        self.assertFalse(self.owner.signed_in({}, now=5001))
        before = self.file.stat()
        owner.write("another long password", self.file)
        # Windows' clock moves in steps of about 15 ms: a new file of the same size may carry the same time.
        os.utime(self.file, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertFalse(self.owner.signed_in({"HTTP_COOKIE": cookie}, now=5001))
        self.assertEqual(owner.without_cookie(f"lang=ko; {cookie}; theme=x"), "lang=ko; theme=x")

    def test_a_signed_in_device_is_the_owners_under_the_public_name(self):
        owner.write("correct horse battery", self.file)
        call(self.public, "/news/", host=self.PUBLIC, HTTP_COOKIE="lang=ko")
        self.assertEqual(self.seen[-1], (True, False, "lang=ko"))
        status, headers, page = call(self.public, "/owner", host=self.PUBLIC)
        self.assertEqual(status, 200)
        self.assertIn('type="password"', page)
        self.assertIn("form-action 'self'", headers["Content-Security-Policy"])
        self.assertEqual((headers["Cache-Control"], headers["X-Robots-Tag"]), ("no-store", "noindex"))
        status, _, page = self.post({"password": "not it at all"})
        self.assertEqual(status, 401)
        self.assertIn("パスワードが違います", page)
        self.assertEqual(self.post({"password": "correct horse battery"}, HTTP_SEC_FETCH_SITE="cross-site")[0], 403)
        self.assertEqual(self.post({"password": "correct horse battery"}, HTTP_ORIGIN="https://evil.example")[0], 403)
        status, headers, _ = self.post({"password": "correct horse battery"}, HTTP_SEC_FETCH_SITE="same-origin")
        self.assertEqual((status, headers["Location"]), (303, "/"))
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        call(self.public, "/news/", host=self.PUBLIC, HTTP_COOKIE=f"lang=ko; {cookie}")
        self.assertEqual(self.seen[-1], (False, True, "lang=ko"))  # the sites never see the cookie
        self.assertIn("ログアウト", call(self.public, "/owner", host=self.PUBLIC, HTTP_COOKIE=cookie)[2])
        status, headers, _ = self.post({"do": "logout"}, HTTP_COOKIE=cookie)
        self.assertEqual((status, headers["Location"]), (303, "/owner"))
        self.assertIn("Max-Age=0", headers["Set-Cookie"])
        call(self.public, "/news/", host="haruxera", HTTP_COOKIE=cookie)
        self.assertEqual(self.seen[-1], (None, None, cookie))  # the owner's own names are left as they are

    def test_without_a_password_there_is_no_login(self):
        status, _, page = call(self.public, "/owner", host=self.PUBLIC, HTTP_ACCEPT_LANGUAGE="en-GB")
        self.assertEqual(status, 200)
        self.assertIn("Sign-in has not been set up yet.", page)
        self.assertNotIn('type="password"', page)
        self.assertEqual(self.post({"password": "correct horse battery"})[0], 403)
        self.assertEqual(self.seen, [])

    def test_the_list_shows_the_owner_everything_after_signing_in(self):
        apps = [homepage.App("/news", "/news", lambda environ, start: [b""], "News")]
        config = self.tmp / "sites.toml"
        config.write_text(
            '[[site]]\nmount = "/news"\napp = "/news"\n\n[[site]]\nmount = "/news-private"\nname = "x"\n'
            'folder = "nowhere"\npublic = false\n',
            encoding="utf-8",
        )
        portal = homepage.build(apps, visitor_hosts=lambda host: host == self.PUBLIC, config=config)
        page = call(portal, "/", host=self.PUBLIC, **{server.VISITOR_KEY: False, server.OWNER_KEY: True})[2]
        self.assertIn('href="/owner"', page)
        self.assertNotIn('href="/owner"', call(portal, "/", host=self.PUBLIC, **{server.VISITOR_KEY: True})[2])
        self.assertNotIn('href="/owner"', call(portal, "/", host="haruxera")[2])  # the own names need no login
        self.assertEqual(call(portal, "/owner", host="haruxera")[:2][0], 302)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("homepage_launcher", ROOT / "launcher.py")
        self.launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.launcher)

    def test_the_logon_task_starts_the_launcher_in_the_background(self):
        xml = self.launcher.logon_task_xml(Path(r"C:\Python\pythonw.exe"), '"launcher.py" --background', "PC\\me")
        root = xml.getroot()
        text = "".join(root.itertext())
        self.assertIn(r"C:\Python\pythonw.exe", text)
        self.assertIn("--background", text)
        self.assertIn(str(ROOT), text)
        self.assertIn("PT30S", text)

    def test_the_packages_follow_the_python_sites_requirements(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "App").mkdir()
            (tmp / "App" / "requirements.txt").write_text("flask\n", encoding="utf-8")
            (tmp / "sites.toml").write_text(
                '[server]\nport = 5123\n\n[[site]]\nmount = "/a"\npython = "App"\nentry = "a:site"\n', encoding="utf-8"
            )
            self.launcher.CONFIG = tmp / "sites.toml"
            port, files = self.launcher.server_settings()
            self.assertEqual((port, files), (5123, [(tmp / "App" / "requirements.txt").resolve()]))
            before = self.launcher.requirements_digest(files)
            (tmp / "App" / "requirements.txt").write_text("flask\nwaitress\n", encoding="utf-8")
            self.assertNotEqual(self.launcher.requirements_digest(files), before)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_this_folders_sites_toml_needs_news_sites_packages(self):
        port, files = self.launcher.server_settings()
        self.assertEqual(port, 5000)
        if (ROOT.parent / "News Site" / "work" / "app" / "requirements.txt").is_file():
            self.assertIn((ROOT.parent / "News Site" / "work" / "app" / "requirements.txt").resolve(), files)


if __name__ == "__main__":
    unittest.main()
