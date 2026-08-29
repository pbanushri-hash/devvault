"""Search Engine for DevVault.

Provides flexible, parameterized search querying across filenames, paths,
extensions, file sizes, date ranges, tags, and content hashes using only the Python Standard Library.
"""

from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Any, List, Optional, Tuple

from devvault.database import DatabaseManager, FileRecord


@dataclass
class SearchQuery:
    """Represents search filters and parameters for querying indexed files."""

    query: Optional[str] = None  # Text/wildcard query for filename or path
    extension: Optional[str] = None  # e.g., '.py' or 'py'
    tag: Optional[str] = None  # Exact tag name to filter by
    min_size_bytes: Optional[int] = None
    max_size_bytes: Optional[int] = None
    modified_after: Optional[str] = None  # ISO 8601 string or YYYY-MM-DD
    modified_before: Optional[str] = None  # ISO 8601 string or YYYY-MM-DD
    content_hash: Optional[str] = None  # Exact SHA-256 hash or prefix
    regex: Optional[str] = None  # Regular expression pattern to match filenames/paths
    limit: int = 100
    offset: int = 0
    sort_by: str = "filename"  # 'filename', 'size', 'modified_at', 'path'
    sort_desc: bool = False


@dataclass
class SearchResult:
    """Contains search execution results and metadata."""

    records: List[FileRecord] = field(default_factory=list)
    total_matches: int = 0
    query: SearchQuery = field(default_factory=SearchQuery)


class SearchEngine:
    """Executes high-performance parameterized queries against the DevVault database."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        """Initialize the SearchEngine.

        Args:
            db_manager: DatabaseManager instance connected to the SQLite index.
        """
        self.db_manager = db_manager

    def search(self, query_params: SearchQuery) -> SearchResult:
        """Execute a search with the given SearchQuery filters and return SearchResult.

        Args:
            query_params: SearchQuery instance containing search filters.

        Returns:
            SearchResult containing matching FileRecord list and total match count.
        """
        conditions: List[str] = []
        params: List[Any] = []

        # 1. Text Query (Filename or Path wildcard)
        if query_params.query:
            cleaned_q = query_params.query.strip()
            # If user included wildcards like *, transform to SQL %
            if "*" in cleaned_q or "?" in cleaned_q:
                sql_pattern = cleaned_q.replace("*", "%").replace("?", "_")
            else:
                sql_pattern = f"%{cleaned_q}%"
            conditions.append("(f.filename LIKE ? OR f.path LIKE ?)")
            params.extend([sql_pattern, sql_pattern])

        # 2. Extension filter
        if query_params.extension:
            ext = query_params.extension.strip().lower()
            if not ext.startswith("."):
                ext = f".{ext}"
            conditions.append("f.extension = ?")
            params.append(ext)

        # 3. Tag filter
        if query_params.tag:
            clean_tag = query_params.tag.strip().lower()
            conditions.append("EXISTS (SELECT 1 FROM tags t WHERE t.file_id = f.id AND t.tag_name = ?)")
            params.append(clean_tag)

        # 4. Size bounds
        if query_params.min_size_bytes is not None:
            conditions.append("f.size_bytes >= ?")
            params.append(query_params.min_size_bytes)
        if query_params.max_size_bytes is not None:
            conditions.append("f.size_bytes <= ?")
            params.append(query_params.max_size_bytes)

        # 5. Modification date bounds
        if query_params.modified_after:
            conditions.append("f.modified_at >= ?")
            params.append(query_params.modified_after)
        if query_params.modified_before:
            conditions.append("f.modified_at <= ?")
            params.append(query_params.modified_before)

        # 6. Hash filter
        if query_params.content_hash:
            clean_hash = query_params.content_hash.strip().lower()
            if len(clean_hash) < 64:
                conditions.append("f.content_hash LIKE ?")
                params.append(f"{clean_hash}%")
            else:
                conditions.append("f.content_hash = ?")
                params.append(clean_hash)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # Mapping sort keys
        sort_map = {
            "filename": "f.filename",
            "size": "f.size_bytes",
            "modified_at": "f.modified_at",
            "path": "f.path",
            "indexed_at": "f.indexed_at",
        }
        order_column = sort_map.get(query_params.sort_by.lower(), "f.filename")
        direction = "DESC" if query_params.sort_desc else "ASC"
        order_clause = f"ORDER BY {order_column} {direction}"

        # Count total matches query
        count_sql = f"SELECT COUNT(DISTINCT f.id) as total FROM files f {where_clause};"

        # Data query
        data_sql = f"""
            SELECT f.id, f.path, f.filename, f.extension, f.size_bytes, f.modified_at, f.content_hash, f.indexed_at
            FROM files f
            {where_clause}
            {order_clause}
            LIMIT ? OFFSET ?;
        """

        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()

            # Execute count
            cursor.execute(count_sql, params)
            count_row = cursor.fetchone()
            total_matches = count_row["total"] if count_row else 0

            # Execute data fetch
            data_params = list(params) + [max(1, query_params.limit), max(0, query_params.offset)]
            cursor.execute(data_sql, data_params)
            rows = cursor.fetchall()

            records: List[FileRecord] = []
            regex_compiled = re.compile(query_params.regex, re.IGNORECASE) if query_params.regex else None

            for row in rows:
                # Apply Python regex filter in post-processing if specified
                if regex_compiled:
                    if not (regex_compiled.search(row["filename"]) or regex_compiled.search(row["path"])):
                        continue

                tags = self.db_manager.get_tags_for_file_id(row["id"], conn=conn)
                records.append(
                    FileRecord(
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
                )

            # If regex post-filter was applied, adjust count to matching items
            if regex_compiled:
                total_matches = len(records)

            return SearchResult(
                records=records,
                total_matches=total_matches,
                query=query_params,
            )

    def search_by_name(self, name_query: str, limit: int = 50) -> List[FileRecord]:
        """Convenience method for quick filename search."""
        res = self.search(SearchQuery(query=name_query, limit=limit))
        return res.records

    def search_by_extension(self, extension: str, limit: int = 50) -> List[FileRecord]:
        """Convenience method for extension-based lookup."""
        res = self.search(SearchQuery(extension=extension, limit=limit))
        return res.records

    def search_by_tag(self, tag: str, limit: int = 50) -> List[FileRecord]:
        """Convenience method for tag-based lookup."""
        res = self.search(SearchQuery(tag=tag, limit=limit))
        return res.records
