"""Tag Management Module for DevVault.

Provides tag addition, removal, querying, bulk tagging, and auto-tagging
operations using only the Python Standard Library.
"""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from devvault.database import DatabaseManager, FileRecord
from devvault.search import SearchEngine, SearchQuery


@dataclass
class TagSummary:
    """Represents a tag and its usage frequency across indexed files."""

    tag_name: str
    file_count: int


class TagManager:
    """Handles custom tags and bulk-tagging operations on indexed files."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        """Initialize TagManager.

        Args:
            db_manager: DatabaseManager instance for SQLite interactions.
        """
        self.db_manager = db_manager
        self.search_engine = SearchEngine(db_manager)

    def add_tag_to_file(self, file_path: str | Path, tag: str) -> bool:
        """Add a custom tag to a file by its path.

        Args:
            file_path: Relative or absolute path to the indexed file.
            tag: Tag name to attach.

        Returns:
            True if tag was successfully added, False otherwise.
        """
        abs_path = os.path.abspath(os.path.realpath(str(file_path)))
        return self.db_manager.add_tag(abs_path, tag)

    def remove_tag_from_file(self, file_path: str | Path, tag: str) -> bool:
        """Remove a custom tag from a file by its path.

        Args:
            file_path: Relative or absolute path to the indexed file.
            tag: Tag name to remove.

        Returns:
            True if tag was removed, False if file or tag was not found.
        """
        abs_path = os.path.abspath(os.path.realpath(str(file_path)))
        return self.db_manager.remove_tag(abs_path, tag)

    def get_file_tags(self, file_path: str | Path) -> List[str]:
        """Retrieve all tags for a file path."""
        abs_path = os.path.abspath(os.path.realpath(str(file_path)))
        return self.db_manager.get_tags_for_file(abs_path)

    def list_all_tags(self) -> List[TagSummary]:
        """List all unique tags and their occurrence counts."""
        raw_tags = self.db_manager.get_all_tags()
        return [TagSummary(tag_name=name, file_count=count) for name, count in raw_tags]

    def get_files_with_tag(self, tag: str, limit: int = 100) -> List[FileRecord]:
        """Find all indexed files associated with a specific tag."""
        return self.search_engine.search_by_tag(tag, limit=limit)

    def tag_by_extension(self, extension: str, tag: str) -> int:
        """Bulk tag all indexed files having a specific file extension.

        Args:
            extension: Extension (e.g. '.py' or 'py').
            tag: Tag name to assign.

        Returns:
            Count of newly tagged files.
        """
        clean_ext = extension.strip().lower()
        if not clean_ext.startswith("."):
            clean_ext = f".{clean_ext}"

        matching_files = self.search_engine.search_by_extension(clean_ext, limit=100000)
        tagged_count = 0

        for f in matching_files:
            if self.add_tag_to_file(f.path, tag):
                tagged_count += 1

        return tagged_count

    def auto_tag_common_types(self) -> Dict[str, int]:
        """Convenience heuristic to auto-tag standard developer assets.

        Returns:
            Dictionary mapping tag names to number of files tagged.
        """
        rules = {
            "python": [".py", ".pyw", ".pyi"],
            "typescript": [".ts", ".tsx"],
            "javascript": [".js", ".jsx", ".mjs"],
            "web": [".html", ".css", ".scss"],
            "config": [".json", ".yaml", ".yml", ".toml", ".ini", ".env"],
            "docs": [".md", ".rst", ".txt", ".pdf"],
            "images": [".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"],
            "database": [".sql", ".sqlite", ".db"],
        }

        results: Dict[str, int] = {}
        for tag, extensions in rules.items():
            total = 0
            for ext in extensions:
                total += self.tag_by_extension(ext, tag)
            if total > 0:
                results[tag] = total

        return results
