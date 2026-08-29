"""Workspace Statistics Module for DevVault.

Computes storage breakdowns, extension distributions, largest files,
and duplicate metrics using only the Python Standard Library.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from devvault.database import DatabaseManager, FileRecord
from devvault.duplicates import DuplicateDetector, DuplicateReport


@dataclass
class ExtensionStat:
    """Statistics for a specific file extension."""

    extension: str
    file_count: int
    total_size_bytes: int
    percentage_storage: float = 0.0
    percentage_files: float = 0.0


@dataclass
class WorkspaceStats:
    """Comprehensive workspace analysis metrics."""

    total_files: int = 0
    total_storage_bytes: int = 0
    total_tags: int = 0
    extensions: List[ExtensionStat] = field(default_factory=list)
    largest_files: List[FileRecord] = field(default_factory=list)
    duplicate_report: Optional[DuplicateReport] = None
    oldest_file: Optional[FileRecord] = None
    newest_file: Optional[FileRecord] = None
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def format_bytes(size_bytes: int) -> str:
    """Format byte counts into human-readable strings (B, KB, MB, GB)."""
    if size_bytes < 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)
    unit_idx = 0
    while size >= 1024.0 and unit_idx < len(units) - 1:
        size /= 1024.0
        unit_idx += 1
    if unit_idx == 0:
        return f"{int(size)} {units[unit_idx]}"
    return f"{size:.2f} {units[unit_idx]}"


class StatisticsEngine:
    """Analyzes indexed metadata to produce storage and usage summaries."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        """Initialize StatisticsEngine.

        Args:
            db_manager: DatabaseManager instance for SQLite queries.
        """
        self.db_manager = db_manager
        self.duplicate_detector = DuplicateDetector(db_manager)

    def calculate_stats(
        self,
        top_extensions_limit: int = 15,
        largest_files_limit: int = 10,
        include_duplicates: bool = True,
    ) -> WorkspaceStats:
        """Compute aggregated statistics for all indexed workspace files.

        Args:
            top_extensions_limit: Number of top file extensions to return.
            largest_files_limit: Number of largest files to return.
            include_duplicates: Whether to compute duplicate file metrics.

        Returns:
            WorkspaceStats dataclass with computed metrics.
        """
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Total files and total size
            cursor.execute("SELECT COUNT(*) as total_files, COALESCE(SUM(size_bytes), 0) as total_size FROM files;")
            row_summary = cursor.fetchone()
            total_files = row_summary["total_files"] if row_summary else 0
            total_size = row_summary["total_size"] if row_summary else 0

            # 2. Total unique tags
            cursor.execute("SELECT COUNT(DISTINCT tag_name) as total_tags FROM tags;")
            row_tags = cursor.fetchone()
            total_tags = row_tags["total_tags"] if row_tags else 0

            # 3. Extension distribution
            cursor.execute(
                """
                SELECT extension, COUNT(*) as count, SUM(size_bytes) as size
                FROM files
                GROUP BY extension
                ORDER BY size DESC, count DESC
                LIMIT ?;
                """,
                (top_extensions_limit,),
            )
            ext_rows = cursor.fetchall()
            extensions: List[ExtensionStat] = []
            for er in ext_rows:
                ext_name = er["extension"] or "(no ext)"
                ext_count = er["count"]
                ext_size = er["size"]
                pct_storage = (ext_size / total_size * 100.0) if total_size > 0 else 0.0
                pct_files = (ext_count / total_files * 100.0) if total_files > 0 else 0.0
                extensions.append(
                    ExtensionStat(
                        extension=ext_name,
                        file_count=ext_count,
                        total_size_bytes=ext_size,
                        percentage_storage=round(pct_storage, 2),
                        percentage_files=round(pct_files, 2),
                    )
                )

            # 4. Largest files
            cursor.execute(
                """
                SELECT id, path, filename, extension, size_bytes, modified_at, content_hash, indexed_at
                FROM files
                ORDER BY size_bytes DESC, path ASC
                LIMIT ?;
                """,
                (largest_files_limit,),
            )
            largest_rows = cursor.fetchall()
            largest_files: List[FileRecord] = [
                FileRecord(
                    id=lr["id"],
                    path=lr["path"],
                    filename=lr["filename"],
                    extension=lr["extension"],
                    size_bytes=lr["size_bytes"],
                    modified_at=lr["modified_at"],
                    content_hash=lr["content_hash"],
                    indexed_at=lr["indexed_at"],
                    tags=self.db_manager.get_tags_for_file_id(lr["id"], conn=conn),
                )
                for lr in largest_rows
            ]

            # 5. Oldest and newest files
            cursor.execute(
                """
                SELECT id, path, filename, extension, size_bytes, modified_at, content_hash, indexed_at
                FROM files
                WHERE modified_at IS NOT NULL AND modified_at != ''
                ORDER BY modified_at ASC
                LIMIT 1;
                """
            )
            oldest_row = cursor.fetchone()
            oldest_file = (
                FileRecord(
                    id=oldest_row["id"],
                    path=oldest_row["path"],
                    filename=oldest_row["filename"],
                    extension=oldest_row["extension"],
                    size_bytes=oldest_row["size_bytes"],
                    modified_at=oldest_row["modified_at"],
                    content_hash=oldest_row["content_hash"],
                    indexed_at=oldest_row["indexed_at"],
                )
                if oldest_row
                else None
            )

            cursor.execute(
                """
                SELECT id, path, filename, extension, size_bytes, modified_at, content_hash, indexed_at
                FROM files
                WHERE modified_at IS NOT NULL AND modified_at != ''
                ORDER BY modified_at DESC
                LIMIT 1;
                """
            )
            newest_row = cursor.fetchone()
            newest_file = (
                FileRecord(
                    id=newest_row["id"],
                    path=newest_row["path"],
                    filename=newest_row["filename"],
                    extension=newest_row["extension"],
                    size_bytes=newest_row["size_bytes"],
                    modified_at=newest_row["modified_at"],
                    content_hash=newest_row["content_hash"],
                    indexed_at=newest_row["indexed_at"],
                )
                if newest_row
                else None
            )

        # 6. Duplicates calculation
        dup_report = self.duplicate_detector.find_duplicates_in_index() if include_duplicates else None

        return WorkspaceStats(
            total_files=total_files,
            total_storage_bytes=total_size,
            total_tags=total_tags,
            extensions=extensions,
            largest_files=largest_files,
            duplicate_report=dup_report,
            oldest_file=oldest_file,
            newest_file=newest_file,
        )
