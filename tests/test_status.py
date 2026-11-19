"""What is running: the git commit of a folder and the machine's numbers (homepage/status.py)."""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from homepage import status


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.git = self.tmp / ".git"
        (self.git / "refs" / "heads").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_commit_a_folder_has_checked_out(self):
        (self.git / "HEAD").write_text("ref: refs/heads/master\n", encoding="utf-8")
        self.assertEqual(status.git_head(self.tmp), ("", None))  # no commit yet
        (self.git / "packed-refs").write_text(
            "# pack-refs with: peeled fully-peeled sorted\n" + "1" * 40 + " refs/heads/master\n", encoding="utf-8"
        )
        commit, when = status.git_head(self.tmp)
        self.assertEqual(commit, "1" * 40)  # a fresh clone keeps its branch in packed-refs
        self.assertIsNotNone(when)
        self.assertEqual(when.utcoffset().total_seconds(), 9 * 3600)  # Japan's time
        (self.git / "refs" / "heads" / "master").write_text("2" * 40 + "\n", encoding="utf-8")
        self.assertEqual(status.git_head(self.tmp)[0], "2" * 40)  # where update.sh moves it
        (self.git / "HEAD").write_text("3" * 40 + "\n", encoding="utf-8")
        self.assertEqual(status.git_head(self.tmp)[0], "3" * 40)  # a detached checkout

    def test_a_worktree_and_folders_that_are_no_clone(self):
        (self.git / "HEAD").write_text("4" * 40, encoding="utf-8")
        other = self.tmp / "other"
        other.mkdir()
        (other / ".git").write_text("gitdir: ../.git\n", encoding="utf-8")
        self.assertEqual(status.git_head(other)[0], "4" * 40)
        self.assertEqual(status.git_head(self.tmp / "nowhere"), ("", None))
        (self.git / "HEAD").write_bytes(b"\xff\xfe")
        self.assertEqual(status.git_head(self.tmp), ("", None))

    def test_the_machines_numbers(self):
        found = status.machine(self.tmp)
        self.assertIn("disk", found)
        free, total = found["disk"]
        self.assertLessEqual(free, total)
        if Path("/proc/meminfo").exists():  # Linux (the VM); Windows has no /proc
            self.assertLessEqual(found["memory"][0], found["memory"][1])
            self.assertGreater(found["process"], 0)
        self.assertEqual(
            [status.size(n) for n in (512, 2048, 954 * 1024**2, 1.94 * 1024**3, 60 * 1024**3)],
            ["512 B", "2.0 KB", "954 MB", "1.9 GB", "60 GB"],
        )


if __name__ == "__main__":
    unittest.main()
