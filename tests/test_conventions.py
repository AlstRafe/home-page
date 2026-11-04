"""docs/CONVENTIONS.md keeps up with the files it describes. Run: python -m unittest discover -s tests"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "CONVENTIONS.md"


class ConventionsTest(unittest.TestCase):
    def setUp(self):
        self.guide = GUIDE.read_text(encoding="utf-8")

    def test_the_ruff_version_is_the_one_ci_runs(self):
        versions = set(re.findall(r"ruff@([\d.]+)", (ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8")))
        self.assertEqual(len(versions), 1, versions)
        (version,) = versions
        self.assertIn(f"uvx ruff@{version} format .", self.guide)
        self.assertRegex(self.guide, rf"\| Ruff +\| {re.escape(version)} +\|")
        self.assertIn(f"uvx ruff@{version} format .", (ROOT / "README.md").read_text("utf-8"))

    def test_the_tool_versions_are_the_ones_in_package_json(self):
        tools = json.loads((ROOT / "package.json").read_text("utf-8"))["devDependencies"]
        for name, version in tools.items():
            with self.subTest(name):
                self.assertRegex(version, r"^\d+\.\d+\.\d+$", "pin the exact version")
                self.assertIn(version, self.guide)

    def test_links_to_files_of_this_repository_lead_somewhere(self):
        links = re.findall(r"\]\((\.\./[^)#]+)\)", self.guide)
        self.assertTrue(links)
        for link in links:
            with self.subTest(link):
                self.assertTrue((GUIDE.parent / link).resolve().exists())

    def test_links_inside_the_page_name_a_heading(self):
        slugs = {
            re.sub(r"[^\w\- ]", "", line.lstrip("#").strip().lower()).replace(" ", "-")
            for line in self.guide.splitlines()
            if line.startswith("#")
        }
        for anchor in re.findall(r"\]\(#([^)]+)\)", self.guide):
            with self.subTest(anchor):
                self.assertIn(anchor, slugs)


if __name__ == "__main__":
    unittest.main()
