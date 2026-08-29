"""DevVault - Developer Workspace Indexer, Search Engine, & Analytics.

Zero external dependencies. Pure Python Standard Library.
"""

from devvault.database import DatabaseManager, FileRecord
from devvault.duplicates import DuplicateDetector, DuplicateGroup, DuplicateReport
from devvault.indexer import IndexStats, WorkspaceIndexer
from devvault.reports import ReportGenerator
from devvault.scanner import ScannedFile, WorkspaceScanner, compute_sha256
from devvault.search import SearchEngine, SearchQuery, SearchResult
from devvault.statistics import ExtensionStat, StatisticsEngine, WorkspaceStats, format_bytes
from devvault.tags import TagManager, TagSummary

__version__ = "1.0.0"
__all__ = [
    "compute_sha256",
    "DatabaseManager",
    "DuplicateDetector",
    "DuplicateGroup",
    "DuplicateReport",
    "ExtensionStat",
    "FileRecord",
    "format_bytes",
    "IndexStats",
    "ReportGenerator",
    "ScannedFile",
    "SearchEngine",
    "SearchQuery",
    "SearchResult",
    "StatisticsEngine",
    "TagManager",
    "TagSummary",
    "WorkspaceIndexer",
    "WorkspaceScanner",
    "WorkspaceStats",
]
