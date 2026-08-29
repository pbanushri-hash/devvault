"""Indexing Engine for DevVault.

Coordinates workspace scanning, change detection (smart hash skipping),
batch database upserts, and stale record pruning using only the Python Standard Library.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import time
from typing import Callable, List, Optional, Set

from devvault.database import DatabaseManager, FileRecord
from devvault.scanner import ScannedFile, WorkspaceScanner, compute_sha256


@dataclass
class IndexStats:
    """Summary statistics produced by an indexing operation."""

    target_directory: str
    total_scanned: int = 0
    total_indexed: int = 0
    total_skipped: int = 0  # Unchanged files skipped from re-hashing
    total_pruned: int = 0   # Removed stale records from database
    total_errors: int = 0
    duration_seconds: float = 0.0


class WorkspaceIndexer:
    """Orchestrates filesystem scanning, incremental hashing, and database indexing."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        batch_size: int = 500,
        ignored_dirs: Optional[Set[str]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        error_callback: Optional[Callable[[str, Exception], None]] = None,
    ) -> None:
        """Initialize the WorkspaceIndexer.

        Args:
            db_manager: DatabaseManager instance for persistence.
            batch_size: Number of records to batch per database transaction.
            ignored_dirs: Directory names to ignore during scanning.
            progress_callback: Callback receiving (count, current_file_path).
            error_callback: Callback receiving (file_path, exception).
        """
        self.db_manager = db_manager
        self.batch_size = max(1, batch_size)
        self.ignored_dirs = ignored_dirs
        self.progress_callback = progress_callback
        self.error_callback = error_callback

    def index_directory(
        self,
        target_dir: str | Path,
        prune_missing: bool = True,
        force_rehash: bool = False,
    ) -> IndexStats:
        """Index all files in target_dir into the DevVault database.

        Optimizations:
        - Compares modification timestamp and file size against existing records in DB.
          If unchanged and not force_rehash, skips expensive full disk SHA-256 computation.
        - Batches database writes inside atomic transactions.
        - Prunes database entries for files deleted on disk under target_dir.

        Args:
            target_dir: Workspace directory path to index.
            prune_missing: If True, delete DB entries for files no longer on disk.
            force_rehash: If True, re-hash all files even if mtime/size match.

        Returns:
            IndexStats summary dataclass.
        """
        start_time = time.time()
        abs_target = os.path.abspath(os.path.realpath(str(target_dir)))

        stats = IndexStats(target_directory=abs_target)

        if not os.path.exists(abs_target) or not os.path.isdir(abs_target):
            if self.error_callback:
                self.error_callback(abs_target, FileNotFoundError(f"Directory not found: {abs_target}"))
            stats.total_errors += 1
            stats.duration_seconds = time.time() - start_time
            return stats

        # Scanner initially runs with compute_hashes=False for maximum traversal speed.
        # Hashes are computed selectively if the file is new or modified.
        scanner = WorkspaceScanner(
            ignored_dirs=self.ignored_dirs,
            compute_hashes=False,
            on_error=self._handle_scan_error(stats),
        )

        existing_paths_on_disk: Set[str] = set()
        batch: List[FileRecord] = []
        now_iso = datetime.now(timezone.utc).isoformat()

        for scanned_file in scanner.scan_directory(abs_target):
            stats.total_scanned += 1
            existing_paths_on_disk.add(scanned_file.path)

            if self.progress_callback:
                self.progress_callback(stats.total_scanned, scanned_file.path)

            # Check if file exists in DB to perform smart incremental hashing
            existing_record = self.db_manager.get_file_by_path(scanned_file.path)
            content_hash: Optional[str] = None

            if (
                not force_rehash
                and existing_record is not None
                and existing_record.size_bytes == scanned_file.size_bytes
                and existing_record.modified_at == scanned_file.modified_at
                and existing_record.content_hash is not None
            ):
                # Unchanged file: reuse cached hash without reading file bytes again
                content_hash = existing_record.content_hash
                stats.total_skipped += 1
            else:
                # New or modified file: compute SHA-256
                content_hash = compute_sha256(scanned_file.path)
                if content_hash is None:
                    stats.total_errors += 1

            record = FileRecord(
                path=scanned_file.path,
                filename=scanned_file.filename,
                extension=scanned_file.extension,
                size_bytes=scanned_file.size_bytes,
                modified_at=scanned_file.modified_at,
                content_hash=content_hash,
                indexed_at=now_iso,
            )
            batch.append(record)

            if len(batch) >= self.batch_size:
                self._flush_batch(batch, stats)

        # Flush remaining records
        if batch:
            self._flush_batch(batch, stats)

        # Prune deleted files if requested
        if prune_missing:
            pruned_count = self.db_manager.delete_missing_files_in_directory(
                abs_target, existing_paths_on_disk
            )
            stats.total_pruned = pruned_count

        stats.duration_seconds = max(0.001, time.time() - start_time)
        return stats

    def _flush_batch(self, batch: List[FileRecord], stats: IndexStats) -> None:
        """Write a batch of records to the database and update stats."""
        try:
            inserted = self.db_manager.upsert_files_batch(batch)
            stats.total_indexed += inserted
        except Exception as e:
            stats.total_errors += len(batch)
            if self.error_callback:
                self.error_callback("batch_upsert", e)
        finally:
            batch.clear()

    def _handle_scan_error(self, stats: IndexStats) -> Callable[[str, Exception], None]:
        """Return an error callback that increments stats and delegates to user callback."""
        def _callback(path: str, exc: Exception) -> None:
            stats.total_errors += 1
            if self.error_callback:
                self.error_callback(path, exc)

        return _callback
