"""Core Database & Models Layer for DevVault.

Provides SQLite storage and schema management using Python's standard sqlite3 module.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
from typing import Generator, List, Optional, Sequence, Set, Tuple


@dataclass
class FileRecord:
    """Represents a scanned and indexed file."""

    path: str
    filename: str
    extension: str
    size_bytes: int
    modified_at: str  # ISO 8601 string
    content_hash: Optional[str] = None
    indexed_at: Optional[str] = None  # ISO 8601 string
    id: Optional[int] = None
    tags: List[str] = field(default_factory=list)


def get_default_db_path() -> Path:
    """Return the default path to the DevVault SQLite database (~/.devvault/vault.db)."""
    base_dir = Path.home() / ".devvault"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / "vault.db"


class DatabaseManager:
    """Manages SQLite database connections, schema migrations, and record operations."""

    def __init__(self, db_path: Optional[str | Path] = None) -> None:
        """Initialize the DatabaseManager.
        
        Args:
            db_path: Path to SQLite file, ':memory:', or None for default path.
        """
        if db_path is None:
            self.db_path = str(get_default_db_path())
        elif isinstance(db_path, Path):
            self.db_path = str(db_path)
        else:
            self.db_path = db_path

        self._mem_conn: Optional[sqlite3.Connection] = None
        if self.db_path == ":memory:":
            self._mem_conn = sqlite3.connect(":memory:")
            self._mem_conn.row_factory = sqlite3.Row
            self._mem_conn.execute("PRAGMA foreign_keys = ON;")
        elif self.db_path != ":memory:":
            parent_dir = os.path.dirname(os.path.abspath(self.db_path))
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

        self._init_db()

    def get_connection(self) -> sqlite3.Connection:
        """Create and return a configured sqlite3 connection with Row factory and WAL mode."""
        if self._mem_conn is not None:
            return self._mem_conn

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def close(self) -> None:
        """Close the persistent connection if one exists."""
        if self._mem_conn is not None:
            self._mem_conn.close()
            self._mem_conn = None

    def _init_db(self) -> None:
        """Initialize tables and indexes if they do not exist."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Files table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT UNIQUE NOT NULL,
                    filename TEXT NOT NULL,
                    extension TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    modified_at TEXT NOT NULL,
                    content_hash TEXT,
                    indexed_at TEXT NOT NULL
                );
                """
            )

            # Tags table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id INTEGER NOT NULL,
                    tag_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (file_id) REFERENCES files (id) ON DELETE CASCADE,
                    UNIQUE (file_id, tag_name)
                );
                """
            )

            # Performance indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_path ON files (path);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_filename ON files (filename);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_extension ON files (extension);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_size ON files (size_bytes);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_hash ON files (content_hash);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tags_name ON tags (tag_name);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tags_file_id ON tags (file_id);")

            conn.commit()

    def upsert_file(self, record: FileRecord) -> int:
        """Insert or update a file record and return its row ID."""
        now_iso = record.indexed_at or datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO files (path, filename, extension, size_bytes, modified_at, content_hash, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    filename = excluded.filename,
                    extension = excluded.extension,
                    size_bytes = excluded.size_bytes,
                    modified_at = excluded.modified_at,
                    content_hash = excluded.content_hash,
                    indexed_at = excluded.indexed_at;
                """,
                (
                    record.path,
                    record.filename,
                    record.extension,
                    record.size_bytes,
                    record.modified_at,
                    record.content_hash,
                    now_iso,
                ),
            )
            file_id = cursor.lastrowid
            
            # If updated an existing record, lastrowid might need explicit query
            if not file_id:
                cursor.execute("SELECT id FROM files WHERE path = ?", (record.path,))
                row = cursor.fetchone()
                file_id = row["id"] if row else 0

            # Upsert tags if provided in record
            if record.tags:
                for tag in record.tags:
                    tag_clean = tag.strip().lower()
                    if tag_clean:
                        cursor.execute(
                            """
                            INSERT OR IGNORE INTO tags (file_id, tag_name, created_at)
                            VALUES (?, ?, ?);
                            """,
                            (file_id, tag_clean, now_iso),
                        )

            conn.commit()
            return file_id

    def upsert_files_batch(self, records: Sequence[FileRecord]) -> int:
        """Efficiently batch insert or update multiple file records in a single transaction."""
        if not records:
            return 0

        now_iso = datetime.now(timezone.utc).isoformat()
        rows_to_insert = [
            (
                r.path,
                r.filename,
                r.extension,
                r.size_bytes,
                r.modified_at,
                r.content_hash,
                r.indexed_at or now_iso,
            )
            for r in records
        ]

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                """
                INSERT INTO files (path, filename, extension, size_bytes, modified_at, content_hash, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    filename = excluded.filename,
                    extension = excluded.extension,
                    size_bytes = excluded.size_bytes,
                    modified_at = excluded.modified_at,
                    content_hash = excluded.content_hash,
                    indexed_at = excluded.indexed_at;
                """,
                rows_to_insert,
            )
            conn.commit()
            return len(records)

    def get_file_by_path(self, path: str) -> Optional[FileRecord]:
        """Fetch a single file record and its associated tags by absolute path."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, path, filename, extension, size_bytes, modified_at, content_hash, indexed_at
                FROM files
                WHERE path = ?;
                """,
                (path,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            tags = self.get_tags_for_file_id(row["id"], conn=conn)
            return FileRecord(
                id=row["id"],
                path=row["path"],
                filename=row["filename"],
                extension=row["extension"],
                size_bytes=row["size_bytes"],
                modified_at=row["modified_at"],
                content_hash=row["content_hash"],
                indexed_at=row["indexed_at"],
                tags=tags,
            )

    def get_file_by_id(self, file_id: int) -> Optional[FileRecord]:
        """Fetch a single file record and its associated tags by file ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, path, filename, extension, size_bytes, modified_at, content_hash, indexed_at
                FROM files
                WHERE id = ?;
                """,
                (file_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            tags = self.get_tags_for_file_id(file_id, conn=conn)
            return FileRecord(
                id=row["id"],
                path=row["path"],
                filename=row["filename"],
                extension=row["extension"],
                size_bytes=row["size_bytes"],
                modified_at=row["modified_at"],
                content_hash=row["content_hash"],
                indexed_at=row["indexed_at"],
                tags=tags,
            )

    def delete_file_by_path(self, path: str) -> bool:
        """Delete a file record and cascade delete its tags by file path."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM files WHERE path = ?;", (path,))
            conn.commit()
            return cursor.rowcount > 0

    def delete_missing_files_in_directory(self, root_path: str, existing_paths: Set[str]) -> int:
        """Remove indexed files under root_path that no longer exist on the local disk.
        
        Args:
            root_path: Normalized root directory path string.
            existing_paths: Set of absolute paths found during active scan.
            
        Returns:
            Number of deleted stale records.
        """
        normalized_root = os.path.abspath(root_path)
        pattern = f"{normalized_root}%"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, path FROM files WHERE path LIKE ?;", (pattern,))
            rows = cursor.fetchall()
            
            stale_ids = [row["id"] for row in rows if row["path"] not in existing_paths]
            if not stale_ids:
                return 0

            cursor.executemany("DELETE FROM files WHERE id = ?;", [(sid,) for sid in stale_ids])
            conn.commit()
            return len(stale_ids)

    def add_tag(self, path: str, tag: str) -> bool:
        """Attach a custom tag to a file path. Returns True if successfully tagged."""
        tag_clean = tag.strip().lower()
        if not tag_clean:
            return False

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM files WHERE path = ?;", (path,))
            row = cursor.fetchone()
            if not row:
                return False

            file_id = row["id"]
            now_iso = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                """
                INSERT OR IGNORE INTO tags (file_id, tag_name, created_at)
                VALUES (?, ?, ?);
                """,
                (file_id, tag_clean, now_iso),
            )
            conn.commit()
            return cursor.rowcount > 0

    def remove_tag(self, path: str, tag: str) -> bool:
        """Remove a custom tag from a file path. Returns True if tag was removed."""
        tag_clean = tag.strip().lower()
        if not tag_clean:
            return False

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM files WHERE path = ?;", (path,))
            row = cursor.fetchone()
            if not row:
                return False

            file_id = row["id"]
            cursor.execute(
                "DELETE FROM tags WHERE file_id = ? AND tag_name = ?;",
                (file_id, tag_clean),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_tags_for_file_id(self, file_id: int, conn: Optional[sqlite3.Connection] = None) -> List[str]:
        """Fetch all tag names associated with a given file ID."""
        should_close = False
        if conn is None:
            conn = self.get_connection()
            if self._mem_conn is None:
                should_close = True

        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT tag_name FROM tags WHERE file_id = ? ORDER BY tag_name ASC;",
                (file_id,),
            )
            return [row["tag_name"] for row in cursor.fetchall()]
        finally:
            if should_close:
                conn.close()

    def get_tags_for_file(self, path: str) -> List[str]:
        """Fetch all tag names associated with a given file path."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM files WHERE path = ?;", (path,))
            row = cursor.fetchone()
            if not row:
                return []
            return self.get_tags_for_file_id(row["id"], conn=conn)

    def get_all_tags(self) -> List[Tuple[str, int]]:
        """Retrieve all distinct tags and their frequency counts."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT tag_name, COUNT(file_id) as count
                FROM tags
                GROUP BY tag_name
                ORDER BY count DESC, tag_name ASC;
                """
            )
            return [(row["tag_name"], row["count"]) for row in cursor.fetchall()]

    def count_files(self) -> int:
        """Return the total number of indexed files."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as total FROM files;")
            row = cursor.fetchone()
            return row["total"] if row else 0

    def clear_all(self) -> None:
        """Clear all indexed data from the database (useful for reset and testing)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM tags;")
            cursor.execute("DELETE FROM files;")
            conn.commit()
