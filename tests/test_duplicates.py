"""Unit tests for DevVault Duplicate Detection Engine using Python's unittest."""

import os
from pathlib import Path
import tempfile
import unittest

from devvault.database import DatabaseManager, FileRecord
from devvault.duplicates import DuplicateDetector, DuplicateGroup, DuplicateReport


class TestDuplicateDetector(unittest.TestCase):
    """Test suite for duplicate file grouping and fast two-tier hashing."""

    def setUp(self) -> None:
        """Create a temporary workspace directory with duplicate and unique files."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_path = Path(self.temp_dir.name)

        # Content samples
        self.content_a = b"Exact identical content across multiple files" * 20
        self.content_b = b"Another different unique payload" * 15
        self.content_c = b"Exact identical content across multiple files" * 20  # Same as A

        # Create files
        (self.root_path / "orig_a.txt").write_bytes(self.content_a)
        (self.root_path / "copy_a.txt").write_bytes(self.content_a)
        (self.root_path / "backup_a.data").write_bytes(self.content_c)
        (self.root_path / "unique_b.txt").write_bytes(self.content_b)

        # In-memory database
        self.db = DatabaseManager(db_path=":memory:")
        self.detector = DuplicateDetector(self.db)

    def tearDown(self) -> None:
        """Clean up temporary workspace directory."""
        self.temp_dir.cleanup()

    def test_find_duplicates_in_index(self) -> None:
        """Test finding duplicate clusters from pre-indexed SQLite records."""
        # Insert records into DB with identical content_hash
        hash_a = "aaaa9999" + "0" * 56
        hash_b = "bbbb8888" + "0" * 56

        self.db.upsert_file(
            FileRecord(
                path="/workspace/doc1.txt",
                filename="doc1.txt",
                extension=".txt",
                size_bytes=1000,
                modified_at="2026-08-20T10:00:00Z",
                content_hash=hash_a,
            )
        )
        self.db.upsert_file(
            FileRecord(
                path="/workspace/backup/doc1_copy.txt",
                filename="doc1_copy.txt",
                extension=".txt",
                size_bytes=1000,
                modified_at="2026-08-21T10:00:00Z",
                content_hash=hash_a,
            )
        )
        self.db.upsert_file(
            FileRecord(
                path="/workspace/unique.txt",
                filename="unique.txt",
                extension=".txt",
                size_bytes=500,
                modified_at="2026-08-20T10:00:00Z",
                content_hash=hash_b,
            )
        )

        report: DuplicateReport = self.detector.find_duplicates_in_index()
        self.assertEqual(report.total_groups, 1)
        self.assertEqual(report.total_duplicate_files, 2)
        self.assertEqual(report.total_wasted_bytes, 1000)  # 1 extra copy of 1000 bytes

        group = report.groups[0]
        self.assertEqual(group.content_hash, hash_a)
        self.assertEqual(len(group.files), 2)
        paths = [f.path for f in group.files]
        self.assertIn("/workspace/doc1.txt", paths)
        self.assertIn("/workspace/backup/doc1_copy.txt", paths)

    def test_scan_and_find_duplicates_on_disk(self) -> None:
        """Test on-disk two-tier duplicate scanner."""
        report = self.detector.scan_and_find_duplicates(self.root_path)

        self.assertEqual(report.total_groups, 1)
        self.assertEqual(report.total_duplicate_files, 3)  # orig_a, copy_a, backup_a

        group = report.groups[0]
        self.assertEqual(group.size_bytes, len(self.content_a))
        self.assertEqual(group.wasted_bytes, len(self.content_a) * 2)  # 2 redundant copies

        filenames = [f.filename for f in group.files]
        self.assertIn("orig_a.txt", filenames)
        self.assertIn("copy_a.txt", filenames)
        self.assertIn("backup_a.data", filenames)
        self.assertNotIn("unique_b.txt", filenames)

    def test_empty_workspace_duplicates(self) -> None:
        """Test duplicate detection on an empty folder."""
        empty_temp = tempfile.TemporaryDirectory()
        try:
            report = self.detector.scan_and_find_duplicates(empty_temp.name)
            self.assertEqual(report.total_groups, 0)
            self.assertEqual(report.total_duplicate_files, 0)
            self.assertEqual(report.total_wasted_bytes, 0)
        finally:
            empty_temp.cleanup()


if __name__ == "__main__":
    unittest.main()
