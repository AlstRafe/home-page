"""The server (homepage/server.py) and launcher.py, without starting either. Run: python -m unittest discover -s tests"""
from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_homepage import call

import homepage
from homepage import server

FACTORY = '''
def site(mount, host):
    def app(environ, start_response):
        body = f"{environ['SCRIPT_NAME']} {environ['PATH_INFO']}".encode()
        start_response("200 OK", [("Content-Type", "text/plain"), ("Content-Length", str(len(body)))])
        return [body]
    return {"app": app, "name": "Shop", "subtitle": "a shop", "disallow": ["/api/"], "version": lambda: "v1",
            "preview": lambda: {"items": [("today", "/today")]}, "host": host}


def broken(mount, host):
    raise RuntimeError("no database")
'''


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "Shop" / "shopsite").mkdir(parents=True)
        (self.tmp / "Shop" / "shopsite" / "__init__.py").write_text(FACTORY, encoding="utf-8")
        self.config = self.tmp / "sites.toml"
        self.config.write_text('''title = "x"

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
''', encoding="utf-8")

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
        self.assertEqual((shop.key, shop.name, shop.subtitle, shop.disallow, shop.version()), ("/shop", "Shop", "a shop", ("/api/",), "v1"))
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
            (tmp / "sites.toml").write_text('[server]\nport = 5123\n\n[[site]]\nmount = "/a"\npython = "App"\nentry = "a:site"\n',
                                            encoding="utf-8")
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
