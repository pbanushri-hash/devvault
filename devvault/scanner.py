"""File Scanner & Hashing Utilities for DevVault.

Provides resilient recursive workspace scanning, metadata extraction,
and chunked SHA-256 content hashing using only the Python Standard Library.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
from typing import Callable, Generator, List, Optional, Set, Tuple


# Standard directories and patterns to skip by default for performance and safety
DEFAULT_IGNORED_DIRS: Set[str] = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    ".devvault",
}

# 64 KB chunk size for memory-efficient streaming hashing
HASH_CHUNK_SIZE = 64 * 1024


@dataclass
class ScannedFile:
    """Represents a discovered file with extracted metadata before database insertion."""

    path: str  # Absolute normalized path
    filename: str  # e.g., 'main.py'
    extension: str  # e.g., '.py' (lowercase)
    size_bytes: int
    modified_at: str  # ISO 8601 UTC timestamp
    content_hash: Optional[str] = None  # Computed on demand or during full scan


def compute_sha256(
    file_path: str | Path,
    chunk_size: int = HASH_CHUNK_SIZE,
    max_bytes: Optional[int] = None,
) -> Optional[str]:
    """Compute the SHA-256 hash of a file safely using chunked streaming.
    
    Args:
        file_path: Path to the target file.
        chunk_size: Number of bytes to read per iteration (default 64KB).
        max_bytes: Optional upper limit of bytes to hash (useful for quick prefix hashing).
        
    Returns:
        Hexadecimal SHA-256 hash string, or None if unreadable.
    """
    hasher = hashlib.sha256()
    bytes_read = 0

    try:
        with open(file_path, "rb") as f:
            while True:
                if max_bytes is not None:
                    remaining = max_bytes - bytes_read
                    if remaining <= 0:
                        break
                    to_read = min(chunk_size, remaining)
                else:
                    to_read = chunk_size

                chunk = f.read(to_read)
                if not chunk:
                    break

                hasher.update(chunk)
                bytes_read += len(chunk)

        return hasher.hexdigest()
    except (PermissionError, FileNotFoundError, OSError):
        return None


def get_file_metadata(file_path: str | Path, calculate_hash: bool = True) -> Optional[ScannedFile]:
    """Extract metadata and compute hash for a single file path safely.
    
    Args:
        file_path: Path to the file.
        calculate_hash: Whether to calculate SHA-256 immediately.
        
    Returns:
        ScannedFile dataclass instance, or None if the file is inaccessible/missing.
    """
    try:
        resolved_path = os.path.abspath(os.path.realpath(str(file_path)))
        stat_result = os.stat(resolved_path)

        # Exclude directories or special sockets/FIFOs
        if not os.path.isfile(resolved_path):
            return None

        filename = os.path.basename(resolved_path)
        _, ext = os.path.splitext(filename)
        extension = ext.lower()

        # Convert epoch timestamp to UTC ISO 8601 string
        mtime_dt = datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc)
        modified_at = mtime_dt.isoformat()

        content_hash = compute_sha256(resolved_path) if calculate_hash else None

        return ScannedFile(
            path=resolved_path,
            filename=filename,
            extension=extension,
            size_bytes=stat_result.st_size,
            modified_at=modified_at,
            content_hash=content_hash,
        )
    except (PermissionError, FileNotFoundError, OSError):
        return None


class WorkspaceScanner:
    """Recursively scans directory trees to extract file metadata while handling errors gracefully."""

    def __init__(
        self,
        ignored_dirs: Optional[Set[str]] = None,
        compute_hashes: bool = True,
        on_error: Optional[Callable[[str, Exception], None]] = None,
    ) -> None:
        """Initialize the scanner.
        
        Args:
            ignored_dirs: Set of directory names to skip during traversal.
            compute_hashes: Whether to calculate SHA-256 hash during scan.
            on_error: Optional callback receiving (path, exception) on I/O error.
        """
        self.ignored_dirs = set(ignored_dirs) if ignored_dirs is not None else DEFAULT_IGNORED_DIRS
        self.compute_hashes = compute_hashes
        self.on_error = on_error

    def scan_directory(
        self,
        root_dir: str | Path,
        max_depth: Optional[int] = None,
    ) -> Generator[ScannedFile, None, None]:
        """Scan a root directory recursively and yield ScannedFile objects.
        
        Args:
            root_dir: Root directory to begin traversal.
            max_depth: Optional maximum recursion depth (0 = root only).
            
        Yields:
            ScannedFile objects for all accessible files.
        """
        abs_root = os.path.abspath(os.path.realpath(str(root_dir)))
        if not os.path.exists(abs_root) or not os.path.isdir(abs_root):
            return

        # Track visited real directory paths to prevent infinite loops from symlinks
        visited_dirs: Set[str] = set()

        def _traverse(current_dir: str, current_depth: int) -> Generator[ScannedFile, None, None]:
            if max_depth is not None and current_depth > max_depth:
                return

            try:
                real_current = os.path.realpath(current_dir)
                if real_current in visited_dirs:
                    return
                visited_dirs.add(real_current)

                with os.scandir(current_dir) as entries:
                    subdirs: List[os.DirEntry] = []
                    for entry in entries:
                        try:
                            # Handle directories
                            if entry.is_dir(follow_symlinks=False):
                                if entry.name not in self.ignored_dirs and not entry.name.startswith("."):
                                    subdirs.append(entry)
                            # Handle files
                            elif entry.is_file(follow_symlinks=True):
                                try:
                                    stat_res = entry.stat(follow_symlinks=True)
                                    full_path = os.path.abspath(entry.path)
                                    filename = entry.name
                                    _, ext = os.path.splitext(filename)
                                    extension = ext.lower()

                                    mtime_dt = datetime.fromtimestamp(
                                        stat_res.st_mtime, tz=timezone.utc
                                    )
                                    modified_at = mtime_dt.isoformat()

                                    content_hash = (
                                        compute_sha256(full_path)
                                        if self.compute_hashes
                                        else None
                                    )

                                    yield ScannedFile(
                                        path=full_path,
                                        filename=filename,
                                        extension=extension,
                                        size_bytes=stat_res.st_size,
                                        modified_at=modified_at,
                                        content_hash=content_hash,
                                    )
                                except (PermissionError, FileNotFoundError, OSError) as e:
                                    if self.on_error:
                                        self.on_error(entry.path, e)
                                    continue
                        except (PermissionError, FileNotFoundError, OSError) as e:
                            if self.on_error:
                                self.on_error(entry.path, e)
                            continue

                    # Recurse into valid subdirectories
                    for subdir in subdirs:
                        yield from _traverse(subdir.path, current_depth + 1)

            except (PermissionError, FileNotFoundError, OSError) as e:
                if self.on_error:
                    self.on_error(current_dir, e)

        yield from _traverse(abs_root, 0)
