"""Unit tests for DevVault Tag Management Module using Python's built-in unittest."""

import os
from pathlib import Path
import unittest

from devvault.database import DatabaseManager, FileRecord
from devvault.tags import TagManager, TagSummary


class TestTagManager(unittest.TestCase):
    """Test suite for tagging operations, querying, and bulk extensions tagging."""

    def setUp(self) -> None:
        """Populate an in-memory database with sample records."""
        self.db = DatabaseManager(db_path=":memory:")
        self.tag_manager = TagManager(self.db)

        # Seed records
        self.file1 = FileRecord(
            path=os.path.abspath("/workspace/main.py"),
            filename="main.py",
            extension=".py",
            size_bytes=1000,
            modified_at="2026-08-20T10:00:00Z",
        )
        self.file2 = FileRecord(
            path=os.path.abspath("/workspace/helper.py"),
            filename="helper.py",
            extension=".py",
            size_bytes=500,
            modified_at="2026-08-21T10:00:00Z",
        )
        self.file3 = FileRecord(
            path=os.path.abspath("/workspace/readme.md"),
            filename="readme.md",
            extension=".md",
            size_bytes=300,
            modified_at="2026-08-22T10:00:00Z",
        )

        self.db.upsert_files_batch([self.file1, self.file2, self.file3])

    def test_add_and_get_tags(self) -> None:
        """Test attaching tags to files and reading them back."""
        self.assertTrue(self.tag_manager.add_tag_to_file(self.file1.path, "core"))
        self.assertTrue(self.tag_manager.add_tag_to_file(self.file1.path, "cli"))

        tags = self.tag_manager.get_file_tags(self.file1.path)
        self.assertEqual(sorted(tags), ["cli", "core"])

    def test_remove_tag(self) -> None:
        """Test tag deletion from a file."""
        self.tag_manager.add_tag_to_file(self.file1.path, "deprecated")
        self.assertIn("deprecated", self.tag_manager.get_file_tags(self.file1.path))

        self.assertTrue(self.tag_manager.remove_tag_from_file(self.file1.path, "deprecated"))
        self.assertNotIn("deprecated", self.tag_manager.get_file_tags(self.file1.path))

    def test_list_all_tags_and_summaries(self) -> None:
        """Test listing unique tags with aggregate counts."""
        self.tag_manager.add_tag_to_file(self.file1.path, "python")
        self.tag_manager.add_tag_to_file(self.file2.path, "python")
        self.tag_manager.add_tag_to_file(self.file3.path, "docs")

        summaries = self.tag_manager.list_all_tags()
        self.assertEqual(len(summaries), 2)

        python_summary = next(s for s in summaries if s.tag_name == "python")
        self.assertEqual(python_summary.file_count, 2)

    def test_get_files_with_tag(self) -> None:
        """Test searching files that possess a given tag."""
        self.tag_manager.add_tag_to_file(self.file1.path, "entrypoint")
        files = self.tag_manager.get_files_with_tag("entrypoint")

        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].filename, "main.py")

    def test_tag_by_extension(self) -> None:
        """Test bulk tagging files by extension."""
        count = self.tag_manager.tag_by_extension("py", "code")
        self.assertEqual(count, 2)

        files = self.tag_manager.get_files_with_tag("code")
        self.assertEqual(len(files), 2)
        filenames = [f.filename for f in files]
        self.assertIn("main.py", filenames)
        self.assertIn("helper.py", filenames)

    def test_auto_tag_common_types(self) -> None:
        """Test auto-tagging heuristics across known developer extensions."""
        results = self.tag_manager.auto_tag_common_types()
        self.assertIn("python", results)
        self.assertIn("docs", results)
        self.assertEqual(results["python"], 2)
        self.assertEqual(results["docs"], 1)


if __name__ == "__main__":
    unittest.main()
