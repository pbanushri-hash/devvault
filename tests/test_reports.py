"""Unit tests for DevVault Statistics and Report Generation modules."""

import json
import os
from pathlib import Path
import tempfile
import unittest

from devvault.database import DatabaseManager, FileRecord
from devvault.reports import ReportGenerator
from devvault.search import SearchResult
from devvault.statistics import StatisticsEngine, WorkspaceStats, format_bytes


class TestStatisticsAndReports(unittest.TestCase):
    """Test suite for statistics calculation, byte formatting, and JSON/CSV/Text report exports."""

    def setUp(self) -> None:
        """Create sample records in an in-memory database."""
        self.db = DatabaseManager(db_path=":memory:")
        self.stats_engine = StatisticsEngine(self.db)

        # Seed records with known values and duplicate hashes
        dup_hash = "11112222" + "0" * 56
        self.records = [
            FileRecord(
                path="/workspace/src/app.py",
                filename="app.py",
                extension=".py",
                size_bytes=1048576,  # 1 MB
                modified_at="2026-08-20T10:00:00Z",
                content_hash=dup_hash,
                tags=["backend", "core"],
            ),
            FileRecord(
                path="/workspace/backup/app_copy.py",
                filename="app_copy.py",
                extension=".py",
                size_bytes=1048576,  # 1 MB duplicate
                modified_at="2026-08-21T10:00:00Z",
                content_hash=dup_hash,
            ),
            FileRecord(
                path="/workspace/data/info.json",
                filename="info.json",
                extension=".json",
                size_bytes=524288,  # 512 KB
                modified_at="2026-08-22T10:00:00Z",
                content_hash="33334444" + "0" * 56,
                tags=["data"],
            ),
            FileRecord(
                path="/workspace/docs/README.md",
                filename="README.md",
                extension=".md",
                size_bytes=1024,  # 1 KB
                modified_at="2026-08-23T10:00:00Z",
                content_hash="55556666" + "0" * 56,
            ),
        ]
        for r in self.records:
            self.db.upsert_file(r)

    def test_format_bytes(self) -> None:
        """Test formatting integers into human-readable byte strings."""
        self.assertEqual(format_bytes(500), "500 B")
        self.assertEqual(format_bytes(1024), "1.00 KB")
        self.assertEqual(format_bytes(1048576), "1.00 MB")
        self.assertEqual(format_bytes(1073741824), "1.00 GB")

    def test_calculate_stats(self) -> None:
        """Test comprehensive statistics calculation."""
        stats = self.stats_engine.calculate_stats()

        self.assertEqual(stats.total_files, 4)
        self.assertEqual(stats.total_storage_bytes, 1048576 + 1048576 + 524288 + 1024)
        self.assertEqual(stats.total_tags, 3)  # backend, core, data

        # Extensions
        ext_map = {e.extension: e for e in stats.extensions}
        self.assertIn(".py", ext_map)
        self.assertEqual(ext_map[".py"].file_count, 2)
        self.assertEqual(ext_map[".py"].total_size_bytes, 2097152)

        # Largest files
        self.assertEqual(len(stats.largest_files), 4)
        top_two_names = [f.filename for f in stats.largest_files[:2]]
        self.assertIn("app.py", top_two_names)
        self.assertIn("app_copy.py", top_two_names)

        # Duplicates
        self.assertIsNotNone(stats.duplicate_report)
        self.assertEqual(stats.duplicate_report.total_groups, 1)
        self.assertEqual(stats.duplicate_report.total_duplicate_files, 2)
        self.assertEqual(stats.duplicate_report.total_wasted_bytes, 1048576)

    def test_stats_to_json(self) -> None:
        """Test serializing statistics to JSON."""
        stats = self.stats_engine.calculate_stats()
        json_str = ReportGenerator.stats_to_json(stats)
        data = json.loads(json_str)

        self.assertEqual(data["summary"]["total_files"], 4)
        self.assertEqual(data["duplicates"]["total_groups"], 1)
        self.assertEqual(len(data["extensions"]), 3)

    def test_stats_to_csv(self) -> None:
        """Test exporting statistics to CSV format."""
        stats = self.stats_engine.calculate_stats()
        csv_str = ReportGenerator.stats_to_csv(stats)

        self.assertIn("--- WORKSPACE SUMMARY ---", csv_str)
        self.assertIn("--- EXTENSION BREAKDOWN ---", csv_str)
        self.assertIn(".py,2,2097152", csv_str)
        self.assertIn("--- TOP LARGEST FILES ---", csv_str)
        self.assertIn("app.py", csv_str)

    def test_stats_to_text(self) -> None:
        """Test rendering plain text report."""
        stats = self.stats_engine.calculate_stats()
        text_str = ReportGenerator.stats_to_text(stats)

        self.assertIn("DEVVAULT WORKSPACE ANALYSIS REPORT", text_str)
        self.assertIn("Total Indexed Files:  4", text_str)
        self.assertIn("TOP EXTENSIONS:", text_str)
        self.assertIn(".py", text_str)

    def test_save_report_to_disk(self) -> None:
        """Test saving report to temporary file on disk."""
        stats = self.stats_engine.calculate_stats()
        text_str = ReportGenerator.stats_to_text(stats)

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = Path(tmp_dir) / "sub" / "report.txt"
            ReportGenerator.save_report(text_str, out_file)
            self.assertTrue(out_file.exists())
            self.assertEqual(out_file.read_text(encoding="utf-8"), text_str)


if __name__ == "__main__":
    unittest.main()
