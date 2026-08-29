"""Unit tests for DevVault Search Engine using Python's built-in unittest."""

import unittest

from devvault.database import DatabaseManager, FileRecord
from devvault.search import SearchEngine, SearchQuery


class TestSearchEngine(unittest.TestCase):
    """Test suite for search queries across filenames, wildcards, tags, extensions, sizes, and regex."""

    def setUp(self) -> None:
        """Populate an in-memory database with representative sample records."""
        self.db = DatabaseManager(db_path=":memory:")
        self.search_engine = SearchEngine(self.db)

        # Seed sample files
        self.records = [
            FileRecord(
                path="/workspace/src/app.py",
                filename="app.py",
                extension=".py",
                size_bytes=1024,
                modified_at="2026-08-20T10:00:00Z",
                content_hash="aaaa1111" + "0" * 56,
                tags=["backend", "python"],
            ),
            FileRecord(
                path="/workspace/src/utils.py",
                filename="utils.py",
                extension=".py",
                size_bytes=512,
                modified_at="2026-08-22T12:00:00Z",
                content_hash="bbbb2222" + "0" * 56,
                tags=["utils", "python"],
            ),
            FileRecord(
                path="/workspace/frontend/App.tsx",
                filename="App.tsx",
                extension=".tsx",
                size_bytes=2048,
                modified_at="2026-08-25T14:00:00Z",
                content_hash="cccc3333" + "0" * 56,
                tags=["frontend", "ui"],
            ),
            FileRecord(
                path="/workspace/docs/README.md",
                filename="README.md",
                extension=".md",
                size_bytes=300,
                modified_at="2026-08-28T09:00:00Z",
                content_hash="dddd4444" + "0" * 56,
                tags=["docs"],
            ),
            FileRecord(
                path="/workspace/data/large_dataset.csv",
                filename="large_dataset.csv",
                extension=".csv",
                size_bytes=10485760,  # 10 MB
                modified_at="2026-08-29T08:00:00Z",
                content_hash="eeee5555" + "0" * 56,
                tags=["data"],
            ),
        ]

        for r in self.records:
            self.db.upsert_file(r)

    def test_search_by_exact_and_partial_name(self) -> None:
        """Test searching with substring query."""
        results = self.search_engine.search_by_name("app")
        filenames = [r.filename for r in results]
        self.assertEqual(len(filenames), 2)
        self.assertIn("app.py", filenames)
        self.assertIn("App.tsx", filenames)

    def test_search_with_wildcard(self) -> None:
        """Test glob wildcard queries matching filenames."""
        res = self.search_engine.search(SearchQuery(query="*.tsx"))
        self.assertEqual(res.total_matches, 1)
        self.assertEqual(res.records[0].filename, "App.tsx")

    def test_search_by_extension(self) -> None:
        """Test extension filter with and without leading dot."""
        res_dot = self.search_engine.search_by_extension(".py")
        self.assertEqual(len(res_dot), 2)

        res_nodot = self.search_engine.search_by_extension("py")
        self.assertEqual(len(res_nodot), 2)

        res_md = self.search_engine.search_by_extension("md")
        self.assertEqual(len(res_md), 1)
        self.assertEqual(res_md[0].filename, "README.md")

    def test_search_by_tag(self) -> None:
        """Test tag search filtering."""
        python_files = self.search_engine.search_by_tag("python")
        self.assertEqual(len(python_files), 2)

        ui_files = self.search_engine.search_by_tag("ui")
        self.assertEqual(len(ui_files), 1)
        self.assertEqual(ui_files[0].filename, "App.tsx")

    def test_search_by_size_range(self) -> None:
        """Test filtering by minimum and maximum file sizes."""
        # Files between 400 and 1500 bytes (should match utils.py 512B and app.py 1024B)
        res = self.search_engine.search(
            SearchQuery(min_size_bytes=400, max_size_bytes=1500, sort_by="size")
        )
        self.assertEqual(res.total_matches, 2)
        filenames = [r.filename for r in res.records]
        self.assertEqual(filenames, ["utils.py", "app.py"])

    def test_search_by_date_range(self) -> None:
        """Test filtering by modification timestamp bounds."""
        res = self.search_engine.search(
            SearchQuery(modified_after="2026-08-24T00:00:00Z")
        )
        # Matches App.tsx, README.md, large_dataset.csv
        self.assertEqual(res.total_matches, 3)

    def test_search_by_hash_prefix(self) -> None:
        """Test lookup by SHA-256 prefix."""
        res = self.search_engine.search(SearchQuery(content_hash="aaaa1111"))
        self.assertEqual(res.total_matches, 1)
        self.assertEqual(res.records[0].filename, "app.py")

    def test_search_with_regex(self) -> None:
        """Test regex pattern matching across paths and filenames."""
        # Match filenames containing digits or ending in .csv
        res = self.search_engine.search(SearchQuery(regex=r"large_.*\.csv$"))
        self.assertEqual(len(res.records), 1)
        self.assertEqual(res.records[0].filename, "large_dataset.csv")

    def test_sorting_and_pagination(self) -> None:
        """Test sorting by size descending with limit and offset."""
        res = self.search_engine.search(
            SearchQuery(sort_by="size", sort_desc=True, limit=2, offset=0)
        )
        self.assertEqual(len(res.records), 2)
        self.assertEqual(res.records[0].filename, "large_dataset.csv")
        self.assertEqual(res.records[1].filename, "App.tsx")


if __name__ == "__main__":
    unittest.main()
