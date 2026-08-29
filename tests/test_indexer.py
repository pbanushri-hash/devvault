"""Unit tests for DevVault Indexing Engine using Python's built-in unittest."""

import os
from pathlib import Path
import tempfile
import time
import unittest

from devvault.database import DatabaseManager
from devvault.indexer import IndexStats, WorkspaceIndexer


class TestWorkspaceIndexer(unittest.TestCase):
    """Test suite for incremental workspace indexing, batching, and cache pruning."""

    def setUp(self) -> None:
        """Create a temporary workspace directory and an in-memory test database."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace_path = Path(self.temp_dir.name)

        # Setup sample files
        self.file1 = self.workspace_path / "module_a.py"
        self.file1.write_text("def func_a(): return 42\n", encoding="utf-8")

        self.file2 = self.workspace_path / "data.json"
        self.file2.write_text('{"key": "value"}', encoding="utf-8")

        self.nested_dir = self.workspace_path / "subpkg"
        self.nested_dir.mkdir()
        self.file3 = self.nested_dir / "module_b.py"
        self.file3.write_text("def func_b(): return 99\n", encoding="utf-8")

        self.db = DatabaseManager(db_path=":memory:")

    def tearDown(self) -> None:
        """Clean up temporary workspace."""
        self.temp_dir.cleanup()

    def test_initial_full_indexing(self) -> None:
        """Test scanning and indexing a workspace directory from scratch."""
        indexer = WorkspaceIndexer(db_manager=self.db, batch_size=2)
        stats: IndexStats = indexer.index_directory(self.workspace_path)

        self.assertEqual(stats.total_scanned, 3)
        self.assertEqual(stats.total_indexed, 3)
        self.assertEqual(stats.total_skipped, 0)
        self.assertEqual(stats.total_pruned, 0)
        self.assertEqual(stats.total_errors, 0)
        self.assertEqual(self.db.count_files(), 3)

        # Verify indexed content in DB
        record_a = self.db.get_file_by_path(str(self.file1))
        self.assertIsNotNone(record_a)
        self.assertEqual(record_a.filename, "module_a.py")
        self.assertEqual(record_a.extension, ".py")
        self.assertIsNotNone(record_a.content_hash)

    def test_incremental_indexing_skips_unchanged_files(self) -> None:
        """Test that unchanged files avoid re-hashing and are counted as skipped."""
        indexer = WorkspaceIndexer(db_manager=self.db)
        
        # First index
        stats1 = indexer.index_directory(self.workspace_path)
        self.assertEqual(stats1.total_scanned, 3)
        self.assertEqual(stats1.total_indexed, 3)
        self.assertEqual(stats1.total_skipped, 0)

        # Second index without file changes
        stats2 = indexer.index_directory(self.workspace_path)
        self.assertEqual(stats2.total_scanned, 3)
        self.assertEqual(stats2.total_indexed, 3)
        self.assertEqual(stats2.total_skipped, 3)  # All 3 hashes reused

    def test_incremental_indexing_detects_modified_files(self) -> None:
        """Test modifying a file causes only the modified file to be re-hashed."""
        indexer = WorkspaceIndexer(db_manager=self.db)
        indexer.index_directory(self.workspace_path)

        # Sleep slightly to ensure mtime changes
        time.sleep(0.05)

        # Modify file1
        self.file1.write_text("def func_a_modified(): return 100\n", encoding="utf-8")

        stats = indexer.index_directory(self.workspace_path)
        self.assertEqual(stats.total_scanned, 3)
        self.assertEqual(stats.total_skipped, 2)  # 2 unchanged, 1 re-hashed
        self.assertEqual(stats.total_indexed, 3)

    def test_pruning_deleted_files_from_index(self) -> None:
        """Test removing a file from disk and indexing prunes it from the database."""
        indexer = WorkspaceIndexer(db_manager=self.db)
        indexer.index_directory(self.workspace_path)
        self.assertEqual(self.db.count_files(), 3)

        # Delete file2 from disk
        self.file2.unlink()

        stats = indexer.index_directory(self.workspace_path, prune_missing=True)
        self.assertEqual(stats.total_scanned, 2)
        self.assertEqual(stats.total_pruned, 1)
        self.assertEqual(self.db.count_files(), 2)
        self.assertIsNone(self.db.get_file_by_path(str(self.file2)))

    def test_progress_callback(self) -> None:
        """Test progress tracking callback triggers for every discovered file."""
        progress_calls = []

        def on_progress(count: int, file_path: str) -> None:
            progress_calls.append((count, file_path))

        indexer = WorkspaceIndexer(db_manager=self.db, progress_callback=on_progress)
        indexer.index_directory(self.workspace_path)

        self.assertEqual(len(progress_calls), 3)
        self.assertEqual(progress_calls[-1][0], 3)

    def test_non_existent_target_directory(self) -> None:
        """Test indexing a non-existent directory handles error cleanly."""
        errors = []

        def on_error(path: str, exc: Exception) -> None:
            errors.append((path, exc))

        indexer = WorkspaceIndexer(db_manager=self.db, error_callback=on_error)
        stats = indexer.index_directory(self.workspace_path / "does_not_exist")

        self.assertEqual(stats.total_errors, 1)
        self.assertEqual(len(errors), 1)


if __name__ == "__main__":
    unittest.main()
