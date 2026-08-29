"""Unit tests for DevVault CLI module."""

import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from devvault.cli import build_parser, main
from devvault.database import DatabaseManager, FileRecord


class TestCLI(unittest.TestCase):
    """Test suite for DevVault CLI commands and argument parsing."""

    def setUp(self) -> None:
        """Create temporary workspace and database."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace_dir = Path(self.temp_dir.name) / "workspace"
        self.workspace_dir.mkdir(parents=True)
        self.db_file = Path(self.temp_dir.name) / "test_vault.db"

        # Create sample files
        (self.workspace_dir / "app.py").write_text("print('hello')", encoding="utf-8")
        (self.workspace_dir / "utils.py").write_text("def helper(): pass", encoding="utf-8")
        (self.workspace_dir / "dup_app.py").write_text("print('hello')", encoding="utf-8")  # duplicate of app.py

    def tearDown(self) -> None:
        """Clean up temporary directory."""
        self.temp_dir.cleanup()

    def run_cli(self, args: list) -> tuple[int, str, str]:
        """Execute CLI command with stdout and stderr captured."""
        base_args = ["--db", str(self.db_file), "--no-color"] + args
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with patch("sys.stdout", out_buf), patch("sys.stderr", err_buf):
            exit_code = main(base_args)
        return exit_code, out_buf.getvalue(), err_buf.getvalue()

    def test_cli_index_and_search(self) -> None:
        """Test 'index' then 'search' CLI commands."""
        # 1. Index
        code, out, err = self.run_cli(["index", str(self.workspace_dir)])
        self.assertEqual(code, 0)
        self.assertIn("Indexing complete!", out)
        self.assertIn("Total indexed: 3", out)

        # 2. Search
        code, out, err = self.run_cli(["search", "app"])
        self.assertEqual(code, 0)
        self.assertIn("Found 2 matches", out)
        self.assertIn("app.py", out)
        self.assertIn("dup_app.py", out)

    def test_cli_duplicates(self) -> None:
        """Test 'duplicates' CLI command."""
        self.run_cli(["index", str(self.workspace_dir)])
        code, out, err = self.run_cli(["duplicates", "--from-index"])
        self.assertEqual(code, 0)
        self.assertIn("Found 1 duplicate groups", out)
        self.assertIn("app.py", out)
        self.assertIn("dup_app.py", out)

    def test_cli_stats_and_report(self) -> None:
        """Test 'stats' and 'report' commands."""
        self.run_cli(["index", str(self.workspace_dir)])

        # Stats
        code, out, err = self.run_cli(["stats"])
        self.assertEqual(code, 0)
        self.assertIn("DEVVAULT WORKSPACE ANALYSIS REPORT", out)
        self.assertIn(".py", out)

        # Report JSON
        report_path = Path(self.temp_dir.name) / "out.json"
        code, out, err = self.run_cli(["report", "--format", "json", "-o", str(report_path)])
        self.assertEqual(code, 0)
        self.assertTrue(report_path.exists())
        self.assertIn('"total_files": 3', report_path.read_text(encoding="utf-8"))

    def test_cli_tagging(self) -> None:
        """Test 'tag' CLI operations."""
        self.run_cli(["index", str(self.workspace_dir)])
        target_file = str(self.workspace_dir / "app.py")

        # Add tag
        code, out, err = self.run_cli(["tag", target_file, "--add", "backend"])
        self.assertEqual(code, 0)
        self.assertIn("Tag 'backend' added", out)

        # List tags
        code, out, err = self.run_cli(["tag", "--list"])
        self.assertEqual(code, 0)
        self.assertIn("backend: 1 file(s)", out)

        # Remove tag
        code, out, err = self.run_cli(["tag", target_file, "--remove", "backend"])
        self.assertEqual(code, 0)
        self.assertIn("Tag 'backend' removed", out)


if __name__ == "__main__":
    unittest.main()
