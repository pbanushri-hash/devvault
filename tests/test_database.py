"""Unit tests for DevVault Database & Models Layer using Python's built-in unittest."""

from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
import unittest

from devvault.database import DatabaseManager, FileRecord


class TestDatabaseManager(unittest.TestCase):
    """Test suite for DatabaseManager operations and schema enforcement."""

    def setUp(self) -> None:
        """Create a fresh in-memory database instance for each test case."""
        self.db = DatabaseManager(db_path=":memory:")

    def test_schema_initialization(self) -> None:
        """Verify that tables and indexes are created properly upon initialization."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = {row["name"] for row in cursor.fetchall()}
            self.assertIn("files", tables)
            self.assertIn("tags", tables)

    def test_upsert_and_get_file(self) -> None:
        """Test inserting a new file and fetching it by path and id."""
        record = FileRecord(
            path="/workspace/src/main.py",
            filename="main.py",
            extension=".py",
            size_bytes=1024,
            modified_at="2026-08-29T10:00:00Z",
            content_hash="abc123sha256hash",
            tags=["python", "entrypoint"],
        )

        file_id = self.db.upsert_file(record)
        self.assertGreater(file_id, 0)
        self.assertEqual(self.db.count_files(), 1)

        # Retrieve by path
        fetched_path = self.db.get_file_by_path("/workspace/src/main.py")
        self.assertIsNotNone(fetched_path)
        self.assertEqual(fetched_path.filename, "main.py")
        self.assertEqual(fetched_path.size_bytes, 1024)
        self.assertEqual(fetched_path.content_hash, "abc123sha256hash")
        self.assertIn("python", fetched_path.tags)
        self.assertIn("entrypoint", fetched_path.tags)

        # Retrieve by id
        fetched_id = self.db.get_file_by_id(file_id)
        self.assertIsNotNone(fetched_id)
        self.assertEqual(fetched_id.path, "/workspace/src/main.py")

    def test_upsert_update_existing_file(self) -> None:
        """Test updating an existing file record with changed size and hash."""
        record_v1 = FileRecord(
            path="/workspace/readme.md",
            filename="readme.md",
            extension=".md",
            size_bytes=500,
            modified_at="2026-08-29T10:00:00Z",
            content_hash="hash_v1",
        )
        self.db.upsert_file(record_v1)

        record_v2 = FileRecord(
            path="/workspace/readme.md",
            filename="readme.md",
            extension=".md",
            size_bytes=850,
            modified_at="2026-08-29T11:00:00Z",
            content_hash="hash_v2",
        )
        self.db.upsert_file(record_v2)

        self.assertEqual(self.db.count_files(), 1)
        fetched = self.db.get_file_by_path("/workspace/readme.md")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.size_bytes, 850)
        self.assertEqual(fetched.content_hash, "hash_v2")

    def test_batch_upsert_files(self) -> None:
        """Test bulk batch insertion of file records in a single transaction."""
        records = [
            FileRecord(
                path=f"/workspace/module_{i}.py",
                filename=f"module_{i}.py",
                extension=".py",
                size_bytes=i * 100,
                modified_at="2026-08-29T10:00:00Z",
                content_hash=f"hash_{i}",
            )
            for i in range(10)
        ]

        count = self.db.upsert_files_batch(records)
        self.assertEqual(count, 10)
        self.assertEqual(self.db.count_files(), 10)

    def test_tag_management(self) -> None:
        """Test adding, querying, and removing tags from indexed files."""
        record = FileRecord(
            path="/workspace/app.py",
            filename="app.py",
            extension=".py",
            size_bytes=2048,
            modified_at="2026-08-29T10:00:00Z",
        )
        self.db.upsert_file(record)

        # Add tags
        self.assertTrue(self.db.add_tag("/workspace/app.py", "backend"))
        self.assertTrue(self.db.add_tag("/workspace/app.py", "critical"))
        # Adding duplicate tag should not fail or duplicate
        self.assertFalse(self.db.add_tag("/workspace/app.py", "backend"))

        tags = self.db.get_tags_for_file("/workspace/app.py")
        self.assertEqual(sorted(tags), ["backend", "critical"])

        # Tag frequency
        all_tags = self.db.get_all_tags()
        self.assertEqual(len(all_tags), 2)

        # Remove tag
        self.assertTrue(self.db.remove_tag("/workspace/app.py", "critical"))
        remaining_tags = self.db.get_tags_for_file("/workspace/app.py")
        self.assertEqual(remaining_tags, ["backend"])

    def test_delete_file_and_cascade_tags(self) -> None:
        """Test deleting a file deletes its entry and cascade deletes its tags."""
        record = FileRecord(
            path="/workspace/config.json",
            filename="config.json",
            extension=".json",
            size_bytes=120,
            modified_at="2026-08-29T10:00:00Z",
            tags=["config"],
        )
        self.db.upsert_file(record)
        self.assertEqual(len(self.db.get_tags_for_file("/workspace/config.json")), 1)

        # Delete file
        deleted = self.db.delete_file_by_path("/workspace/config.json")
        self.assertTrue(deleted)
        self.assertEqual(self.db.count_files(), 0)
        self.assertEqual(len(self.db.get_tags_for_file("/workspace/config.json")), 0)

    def test_delete_missing_files_in_directory(self) -> None:
        """Test cleanup of removed disk files from a target folder index."""
        records = [
            FileRecord(
                path=f"/workspace/src/file{i}.py",
                filename=f"file{i}.py",
                extension=".py",
                size_bytes=100,
                modified_at="2026-08-29T10:00:00Z",
            )
            for i in range(1, 4)
        ]
        self.db.upsert_files_batch(records)
        self.assertEqual(self.db.count_files(), 3)

        # Assume file3 was deleted on disk
        active_paths = {"/workspace/src/file1.py", "/workspace/src/file2.py"}
        stale_deleted = self.db.delete_missing_files_in_directory("/workspace/src", active_paths)
        self.assertEqual(stale_deleted, 1)
        self.assertEqual(self.db.count_files(), 2)
        self.assertIsNone(self.db.get_file_by_path("/workspace/src/file3.py"))

    def test_file_based_persistence(self) -> None:
        """Test database persistence across instance lifecycles using a temp file."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_db_path = tmp.name

        try:
            # First instance writes record
            db1 = DatabaseManager(db_path=tmp_db_path)
            db1.upsert_file(
                FileRecord(
                    path="/workspace/persistent.txt",
                    filename="persistent.txt",
                    extension=".txt",
                    size_bytes=42,
                    modified_at="2026-08-29T10:00:00Z",
                )
            )

            # Second instance reads record
            db2 = DatabaseManager(db_path=tmp_db_path)
            record = db2.get_file_by_path("/workspace/persistent.txt")
            self.assertIsNotNone(record)
            self.assertEqual(record.filename, "persistent.txt")
            self.assertEqual(record.size_bytes, 42)
        finally:
            if os.path.exists(tmp_db_path):
                os.remove(tmp_db_path)


if __name__ == "__main__":
    unittest.main()
