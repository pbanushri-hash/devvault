"""Unit tests for DevVault File Scanner & Hashing Utilities using Python's unittest."""

import hashlib
import os
from pathlib import Path
import tempfile
import unittest

from devvault.scanner import (
    DEFAULT_IGNORED_DIRS,
    ScannedFile,
    WorkspaceScanner,
    compute_sha256,
    get_file_metadata,
)


class TestScannerAndHashing(unittest.TestCase):
    """Test suite for workspace scanning, error resilience, and chunked SHA-256 hashing."""

    def setUp(self) -> None:
        """Create a structured temporary test folder hierarchy."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_path = Path(self.temp_dir.name)

        # Create files
        self.file1 = self.root_path / "hello.py"
        self.file1.write_text("print('hello world')", encoding="utf-8")

        self.file2 = self.root_path / "notes.TXT"
        self.file2.write_text("Some notes here", encoding="utf-8")

        # Create nested directory with files
        self.sub_dir = self.root_path / "src"
        self.sub_dir.mkdir()
        self.file3 = self.sub_dir / "app.py"
        self.file3.write_text("def run(): pass", encoding="utf-8")

        # Create ignored directory with a file
        self.ignored_dir = self.root_path / "node_modules"
        self.ignored_dir.mkdir()
        self.ignored_file = self.ignored_dir / "package.json"
        self.ignored_file.write_text('{"name": "test"}', encoding="utf-8")

        # Create hidden directory
        self.hidden_dir = self.root_path / ".hidden"
        self.hidden_dir.mkdir()
        self.hidden_file = self.hidden_dir / "secret.key"
        self.hidden_file.write_text("secret", encoding="utf-8")

    def tearDown(self) -> None:
        """Clean up temporary directory."""
        self.temp_dir.cleanup()

    def test_compute_sha256_exactness(self) -> None:
        """Test that compute_sha256 matches hashlib output exactly."""
        content = b"Zero Dependency Python Hackathon Project 2026"
        test_file = self.root_path / "hash_test.bin"
        test_file.write_bytes(content)

        expected_hash = hashlib.sha256(content).hexdigest()
        calculated_hash = compute_sha256(test_file)

        self.assertEqual(calculated_hash, expected_hash)

    def test_compute_sha256_prefix_mode(self) -> None:
        """Test partial prefix hashing using max_bytes parameter."""
        content = b"A" * 10000 + b"B" * 10000
        test_file = self.root_path / "prefix_test.bin"
        test_file.write_bytes(content)

        expected_prefix_hash = hashlib.sha256(b"A" * 1000).hexdigest()
        calculated_prefix_hash = compute_sha256(test_file, max_bytes=1000)

        self.assertEqual(calculated_prefix_hash, expected_prefix_hash)

    def test_compute_sha256_non_existent_file(self) -> None:
        """Test that compute_sha256 handles non-existent file paths gracefully."""
        result = compute_sha256(self.root_path / "does_not_exist.tmp")
        self.assertIsNone(result)

    def test_get_file_metadata(self) -> None:
        """Test single file metadata extraction."""
        meta = get_file_metadata(self.file1, calculate_hash=True)

        self.assertIsNotNone(meta)
        self.assertEqual(meta.filename, "hello.py")
        self.assertEqual(meta.extension, ".py")
        self.assertEqual(meta.size_bytes, len("print('hello world')"))
        self.assertIsNotNone(meta.content_hash)
        self.assertTrue(meta.modified_at.endswith("+00:00") or meta.modified_at.endswith("Z"))

    def test_scanner_directory_traversal_and_ignore_rules(self) -> None:
        """Test that scanner recursively discovers normal files while skipping ignored/hidden dirs."""
        scanner = WorkspaceScanner(compute_hashes=True)
        scanned_files = list(scanner.scan_directory(self.root_path))

        filenames = [f.filename for f in scanned_files]
        self.assertIn("hello.py", filenames)
        self.assertIn("notes.TXT", filenames)
        self.assertIn("app.py", filenames)

        # Node modules and hidden folder should be skipped
        self.assertNotIn("package.json", filenames)
        self.assertNotIn("secret.key", filenames)

        # Verify extension normalization (lowercased)
        notes_record = next(f for f in scanned_files if f.filename == "notes.TXT")
        self.assertEqual(notes_record.extension, ".txt")

    def test_scanner_max_depth_restriction(self) -> None:
        """Test scanning with max_depth=0 only retrieves root level items."""
        scanner = WorkspaceScanner()
        root_only_files = list(scanner.scan_directory(self.root_path, max_depth=0))
        filenames = [f.filename for f in root_only_files]

        self.assertIn("hello.py", filenames)
        self.assertIn("notes.TXT", filenames)
        self.assertNotIn("app.py", filenames)  # inside src/

    def test_scanner_error_callback(self) -> None:
        """Test scanner resiliently invokes error callback when encountering errors."""
        errors_reported = []

        def on_error(path: str, exc: Exception) -> None:
            errors_reported.append((path, exc))

        scanner = WorkspaceScanner(on_error=on_error)
        # Scan non-existent folder should gracefully finish with no items
        files = list(scanner.scan_directory(self.root_path / "non_existent_folder"))
        self.assertEqual(len(files), 0)


if __name__ == "__main__":
    unittest.main()
