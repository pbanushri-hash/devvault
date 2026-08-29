"""Duplicate File Detection Engine for DevVault.

Identifies duplicate files using a two-stage strategy (file size grouping -> SHA-256 hash clustering)
using only the Python Standard Library.
"""

from collections import defaultdict
from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from devvault.database import DatabaseManager, FileRecord
from devvault.scanner import WorkspaceScanner, compute_sha256


@dataclass
class DuplicateGroup:
    """Represents a set of duplicate files sharing identical content."""

    content_hash: str
    size_bytes: int
    files: List[FileRecord] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        """Return number of duplicates in this group."""
        return len(self.files)

    @property
    def wasted_bytes(self) -> int:
        """Bytes consumed beyond a single original copy."""
        if len(self.files) <= 1:
            return 0
        return (len(self.files) - 1) * self.size_bytes


@dataclass
class DuplicateReport:
    """Summary of duplicate detection analysis."""

    total_groups: int = 0
    total_duplicate_files: int = 0
    total_wasted_bytes: int = 0
    groups: List[DuplicateGroup] = field(default_factory=list)


class DuplicateDetector:
    """Detects duplicate files within the indexed database or directly in a directory."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        """Initialize the DuplicateDetector.

        Args:
            db_manager: DatabaseManager instance connected to the SQLite index.
        """
        self.db_manager = db_manager

    def find_duplicates_in_index(
        self,
        min_size_bytes: int = 1,
        folder_prefix: Optional[str] = None,
    ) -> DuplicateReport:
        """Find duplicate files using already computed hashes in the database.

        Args:
            min_size_bytes: Minimum file size to consider (defaults to 1 byte, ignores empty files).
            folder_prefix: Optional path prefix to restrict analysis to a specific directory.

        Returns:
            DuplicateReport containing all duplicate clusters and wasted storage statistics.
        """
        conditions: List[str] = [
            "content_hash IS NOT NULL",
            "content_hash != ''",
            "size_bytes >= ?",
        ]
        params: List[object] = [min_size_bytes]

        if folder_prefix:
            norm_prefix = os.path.abspath(folder_prefix)
            conditions.append("path LIKE ?")
            params.append(f"{norm_prefix}%")

        where_clause = f"WHERE {' AND '.join(conditions)}"

        # Query hashes having count > 1
        query = f"""
            SELECT content_hash, size_bytes, COUNT(id) as count
            FROM files
            {where_clause}
            GROUP BY content_hash, size_bytes
            HAVING count > 1
            ORDER BY (size_bytes * (count - 1)) DESC;
        """

        groups: List[DuplicateGroup] = []
        total_dup_files = 0
        total_wasted = 0

        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            dup_hashes = cursor.fetchall()

            for row in dup_hashes:
                chash = row["content_hash"]
                csize = row["size_bytes"]

                # Fetch all files matching this hash
                file_query = f"""
                    SELECT id, path, filename, extension, size_bytes, modified_at, content_hash, indexed_at
                    FROM files
                    WHERE content_hash = ?
                    {f"AND path LIKE ?" if folder_prefix else ""}
                    ORDER BY modified_at ASC;
                """
                file_params = [chash, f"{os.path.abspath(folder_prefix)}%"] if folder_prefix else [chash]

                cursor.execute(file_query, file_params)
                file_rows = cursor.fetchall()

                file_records = [
                    FileRecord(
                        id=fr["id"],
                        path=fr["path"],
                        filename=fr["filename"],
                        extension=fr["extension"],
                        size_bytes=fr["size_bytes"],
                        modified_at=fr["modified_at"],
                        content_hash=fr["content_hash"],
                        indexed_at=fr["indexed_at"],
                        tags=self.db_manager.get_tags_for_file_id(fr["id"], conn=conn),
                    )
                    for fr in file_rows
                ]

                if len(file_records) > 1:
                    group = DuplicateGroup(
                        content_hash=chash,
                        size_bytes=csize,
                        files=file_records,
                    )
                    groups.append(group)
                    total_dup_files += len(file_records)
                    total_wasted += group.wasted_bytes

        return DuplicateReport(
            total_groups=len(groups),
            total_duplicate_files=total_dup_files,
            total_wasted_bytes=total_wasted,
            groups=groups,
        )

    def scan_and_find_duplicates(
        self,
        directory: str | Path,
        min_size_bytes: int = 1,
    ) -> DuplicateReport:
        """Scan a directory on disk directly, grouping duplicates with two-tier hashing.

        Algorithm:
        1. Fast Traversal: Gather (path, size).
        2. Group by file size: Files with unique sizes are impossible duplicates and are immediately discarded.
        3. Prefix Hash: For collisions in size, compute a quick 4KB prefix SHA-256 to discard non-matches without reading the full file.
        4. Full SHA-256: Compute complete hash only on files sharing both identical size and identical prefix.

        Args:
            directory: Directory path to scan for duplicates.
            min_size_bytes: Minimum file size to check.

        Returns:
            DuplicateReport of identical files found on disk.
        """
        abs_dir = os.path.abspath(os.path.realpath(str(directory)))
        if not os.path.exists(abs_dir) or not os.path.isdir(abs_dir):
            return DuplicateReport()

        scanner = WorkspaceScanner(compute_hashes=False)
        size_buckets: Dict[int, List[str]] = defaultdict(list)

        # Stage 1: Group by file size
        for item in scanner.scan_directory(abs_dir):
            if item.size_bytes >= min_size_bytes:
                size_buckets[item.size_bytes].append(item.path)

        # Discard unique sizes
        candidate_sizes = {s: paths for s, paths in size_buckets.items() if len(paths) > 1}

        # Stage 2: Prefix hash filter (4 KB)
        prefix_buckets: Dict[Tuple[int, str], List[str]] = defaultdict(list)
        for size, paths in candidate_sizes.items():
            for p in paths:
                prefix = compute_sha256(p, max_bytes=4096)
                if prefix:
                    prefix_buckets[(size, prefix)].append(p)

        # Stage 3: Full hash on matching prefix groups
        hash_buckets: Dict[Tuple[int, str], List[str]] = defaultdict(list)
        for (size, _), paths in prefix_buckets.items():
            if len(paths) > 1:
                for p in paths:
                    full_hash = compute_sha256(p)
                    if full_hash:
                        hash_buckets[(size, full_hash)].append(p)

        groups: List[DuplicateGroup] = []
        total_dup_files = 0
        total_wasted = 0

        for (size, full_hash), paths in hash_buckets.items():
            if len(paths) > 1:
                records = [
                    FileRecord(
                        path=p,
                        filename=os.path.basename(p),
                        extension=os.path.splitext(p)[1].lower(),
                        size_bytes=size,
                        modified_at="",
                        content_hash=full_hash,
                    )
                    for p in paths
                ]
                group = DuplicateGroup(
                    content_hash=full_hash,
                    size_bytes=size,
                    files=records,
                )
                groups.append(group)
                total_dup_files += len(records)
                total_wasted += group.wasted_bytes

        # Sort largest wasted space first
        groups.sort(key=lambda g: g.wasted_bytes, reverse=True)

        return DuplicateReport(
            total_groups=len(groups),
            total_duplicate_files=total_dup_files,
            total_wasted_bytes=total_wasted,
            groups=groups,
        )
