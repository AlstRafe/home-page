"""The cloud server's Python helpers (deploy/): moving News Site's data from the PC and the daily backup.
Run: python -m unittest discover -s tests"""

from __future__ import annotations

import calendar
import io
import json
import sqlite3
import sys
import tarfile
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy"))
import backup
import import_news_data
import keepalive
import livecheck
import migrate

PC_ARTICLES = r"C:\Users\someone\Documents\Claude\News Site\work\app\articles"


def make_pc(folder: Path) -> Path:
    """A PC's Home Page with News Site beside it, as sites.toml names it."""
    (folder / "Home Page").mkdir(parents=True)
    (folder / "Home Page" / "sites.toml").write_text(
        '[[site]]\nmount = "/news"\npython = "../News Site/work/app"\nentry = "newsreader.hosting:site"\n',
        encoding="utf-8",
    )
    app = folder / "News Site" / "work" / "app"
    (app / "instance").mkdir(parents=True)
    (app / "articles" / "NAVER NEWS").mkdir(parents=True)
    (app / "articles" / "NAVER NEWS" / "a.html").write_text("<p>a</p>", encoding="utf-8")
    instance = app / "instance"
    (instance / "settings.json").write_text(
        json.dumps({"library_dir": PC_ARTICLES, "start_at_logon": True, "provider": "azure"})
    )
    (instance / "collector.json").write_text(json.dumps({"library_root": PC_ARTICLES}))
    for name in ("collector-task.json", "hosted.json", "server-task.json"):
        (instance / name).write_text("{}")
    (instance / "collector.lock").write_bytes(b"\0")
    (instance / "secret_key").write_bytes(b"k" * 32)
    db = sqlite3.connect(instance / "library.sqlite3")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, title TEXT)")
    db.execute("INSERT INTO articles (title) VALUES ('kept')")
    db.commit()
    db.close()
    return app


class FakeKeyring(types.ModuleType):
    def __init__(self):
        super().__init__("keyring")
        self.saved = {}

    def set_password(self, service, name, value):
        self.saved[(service, name)] = value


class MoveDataTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.pc_app = make_pc(self.folder / "pc")
        self.archive = self.folder / "news-data.tar.gz"
        with (
            mock.patch.object(migrate, "HOME", self.folder / "pc" / "Home Page"),
            mock.patch.object(migrate, "read_secrets", return_value={"azure_api_key": "secret-1"}),
        ):
            self.assertEqual(migrate.news_app(), self.pc_app.resolve())
            migrate.pack(migrate.news_app(), self.archive)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.folder, ignore_errors=True)

    def test_the_archive_has_the_data_and_none_of_the_windows_records(self):
        with tarfile.open(self.archive) as tar:
            names = set(tar.getnames())
        self.assertIn("instance/library.sqlite3", names)
        self.assertIn("instance/settings.json", names)
        self.assertIn("articles/NAVER NEWS/a.html", names)
        self.assertIn("secrets.json", names)
        for name in ("collector-task.json", "hosted.json", "server-task.json", "collector.lock"):
            self.assertNotIn(f"instance/{name}", names)

    def test_a_missing_pc_folder_falls_back_to_the_articles_beside_the_app(self):
        self.assertEqual(migrate.library_folder(self.pc_app), self.pc_app / "articles")

    def test_the_server_takes_it_in_and_keeps_what_it_had(self):
        app = self.folder / "srv" / "app"
        (app / "instance").mkdir(parents=True)
        (app / "instance" / "settings.json").write_text("{}")
        keyring = FakeKeyring()
        with mock.patch.dict(sys.modules, {"keyring": keyring}):
            code = import_news_data.main([str(self.archive), str(app), str(self.folder / "srv" / "backup")])
        self.assertEqual(code, 0)
        settings = json.loads((app / "instance" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(
            (settings["library_dir"], settings["start_at_logon"], settings["provider"]), ("", False, "azure")
        )
        self.assertEqual(
            json.loads((app / "instance" / "collector.json").read_text())["library_root"],
            str((app / "articles").resolve()),
        )
        self.assertTrue((app / "articles" / "NAVER NEWS" / "a.html").is_file())
        db = sqlite3.connect(app / "instance" / "library.sqlite3")
        self.assertEqual(db.execute("SELECT title FROM articles").fetchall(), [("kept",)])
        db.close()
        self.assertFalse((app / "instance" / "secrets.json").exists())
        self.assertFalse((app / ".import").exists())
        self.assertEqual(keyring.saved, {("NewsHtmlReader", "azure_api_key"): "secret-1"})
        kept = list((self.folder / "srv" / "backup").glob("before-import-*/instance/settings.json"))
        self.assertEqual(len(kept), 1)


class BackupTest(unittest.TestCase):
    def test_a_copy_a_day_and_only_the_newest_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            instance = make_pc(Path(folder) / "pc") / "instance"
            target = Path(folder) / "backup"
            for stamp in ("20260101-000000", "20260102-000000", "20260103-000000"):
                (target / f"news-instance-{stamp}.tar.gz").parent.mkdir(exist_ok=True)
                (target / f"news-instance-{stamp}.tar.gz").write_bytes(b"old")
            self.assertEqual(backup.main([str(instance), str(target), "2"]), 0)
            kept = sorted(path.name for path in target.glob("news-instance-*.tar.gz"))
            self.assertEqual(len(kept), 2)
            self.assertEqual(kept[0], "news-instance-20260103-000000.tar.gz")
            with tarfile.open(target / kept[1]) as tar:
                names = set(tar.getnames())
                self.assertIn("instance/library.sqlite3", names)
                self.assertNotIn("instance/collector.lock", names)
                safe = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}  # Python 3.11.4 and later
                tar.extract("instance/library.sqlite3", folder, **safe)
            db = sqlite3.connect(Path(folder) / "instance" / "library.sqlite3")
            self.assertEqual(db.execute("SELECT title FROM articles").fetchall(), [("kept",)])
            db.close()

    def test_a_failed_copy_leaves_nothing_behind_and_keep_0_still_keeps_the_new_one(self):
        with tempfile.TemporaryDirectory() as folder:
            instance = make_pc(Path(folder) / "pc") / "instance"
            target = Path(folder) / "backup"
            with mock.patch.object(backup.sqlite3, "connect", side_effect=backup.sqlite3.OperationalError("locked")):
                with self.assertRaises(backup.sqlite3.OperationalError):
                    backup.main([str(instance), str(target)])
            self.assertEqual([path.name for path in target.iterdir()], [])  # no .part, no temporary folder
            self.assertEqual(backup.main([str(instance), str(target), "0"]), 0)
            self.assertEqual(len(list(target.glob("news-instance-*.tar.gz"))), 1)


class KeepaliveTest(unittest.TestCase):
    def test_the_busy_loop_steps_aside_whenever_anything_else_wants_a_cpu(self):
        loads = iter(["0.10 0.20 0.30 3/180 4242\n"] * 3 + ["0.10 0.20 0.30 1/180 4242\n"] * 1000)
        with (
            mock.patch("builtins.open", side_effect=lambda *a, **k: io.StringIO(next(loads))),
            mock.patch.object(keepalive, "YIELD", 0.01),
            mock.patch.object(keepalive.time, "sleep") as slept,
        ):
            keepalive.busy(0.05, cpus=1)
        self.assertEqual(slept.call_count, 3)  # once for each look that found the sites busy
        with mock.patch("builtins.open", side_effect=OSError):
            self.assertFalse(keepalive.others_running())  # no /proc (not Linux): just work
        with mock.patch("builtins.open", side_effect=lambda *a, **k: io.StringIO("0 0 0 2/180 1\n")):
            self.assertFalse(keepalive.others_running(own=2))  # its two workers alone
            self.assertTrue(keepalive.others_running(own=1))

    def test_it_works_only_during_the_night_hours(self):
        at = lambda hour, minute=0: calendar.timegm((2026, 11, 2, hour, minute, 0))
        night = keepalive.hours(keepalive.NIGHT)
        self.assertEqual(night, {18, 19})  # 03:00-05:00 in Japan
        self.assertEqual(keepalive.work_seconds(at(17, 59), night), 0)
        self.assertEqual(keepalive.work_seconds(at(18), night), 2 * 3600)
        self.assertEqual(keepalive.work_seconds(at(19, 30), night), 1800)
        self.assertEqual(keepalive.work_seconds(at(20), night), 0)
        self.assertEqual(keepalive.work_seconds(at(0, 30), keepalive.hours("23-1")), 1800)
        self.assertEqual(keepalive.hours(""), set())  # never
        self.assertEqual(keepalive.hours("night"), set())


class LivecheckTest(unittest.TestCase):
    def answers(self, *bodies):
        """fetch() answering /version.json with these bodies in turn (None: the VM does not answer)."""
        said = iter(bodies)

        def fetch(url):
            body = next(said)
            if body is None:
                raise ConnectionError(url)
            return (200, {}, json.dumps(body).encode(), 0.1) if isinstance(body, dict) else (404, {}, b"", 0.1)

        return mock.patch.object(livecheck, "fetch", fetch)

    def test_after_a_push_it_waits_until_the_pushed_commit_is_live(self):
        old, new = {"versions": {"/": "a" * 40, "/val": "c" * 40}}, {"versions": {"/": "b" * 40}}
        # before this code was deployed (404), during the restart (no answer), the old code, then the new
        with self.answers("missing", None, old, new), mock.patch("sys.stdout", io.StringIO()) as out:
            self.assertEqual(livecheck.wait_for("https://x", "b" * 40, step=0), [])
        self.assertIn("反映を確認: / は bbbbbbb", out.getvalue())
        with self.answers(old), mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(livecheck.wait_for("https://x", "c" * 40, "/val", step=0), [])
        with self.answers(old, old), mock.patch("sys.stdout", io.StringIO()):
            problems = livecheck.wait_for("https://x", "b" * 40, limit=0, step=0)
        self.assertEqual(problems, ["/: bbbbbbb が 0 分たっても反映されません（いま aaaaaaa）"])


if __name__ == "__main__":
    unittest.main()
