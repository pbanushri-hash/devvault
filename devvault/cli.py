"""Command-Line Interface (CLI) for DevVault.

Provides high-performance subcommands for indexing, searching, duplicate detection,
tagging, workspace statistics, and multi-format report exports using only the Python Standard Library.
"""

import argparse
from datetime import datetime
import os
from pathlib import Path
import sys
from typing import List, Optional

from devvault.database import DatabaseManager, get_default_db_path
from devvault.duplicates import DuplicateDetector
from devvault.indexer import WorkspaceIndexer
from devvault.reports import ReportGenerator
from devvault.search import SearchEngine, SearchQuery
from devvault.statistics import StatisticsEngine, format_bytes
from devvault.tags import TagManager


# ANSI Terminal Colors (Zero dependency terminal styling)
COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"
COLOR_DIM = "\033[2m"
COLOR_GREEN = "\033[32m"
COLOR_CYAN = "\033[36m"
COLOR_YELLOW = "\033[33m"
COLOR_RED = "\033[31m"
COLOR_MAGENTA = "\033[35m"
COLOR_BLUE = "\033[34m"


def _colorize(text: str, color_code: str, use_color: bool = True) -> str:
    """Format string with ANSI escape code if color is enabled."""
    if not use_color or not sys.stdout.isatty():
        return text
    return f"{color_code}{text}{COLOR_RESET}"


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level CLI argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="devvault",
        description="DevVault - Local Developer Workspace Search Engine & Analysis Suite (Zero Dependency)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  devvault index ./my-project
  devvault search "auth" --ext py
  devvault duplicates ./my-project
  devvault duplicates --from-index
  devvault tag ./src/main.py --add backend
  devvault stats
  devvault report --format json --output report.json
        """,
    )

    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Custom SQLite database file path (default: ~/.devvault/vault.db)",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colored output in terminal",
    )

    subparsers = parser.add_subparsers(dest="command", title="Commands", required=True)

    # 1. INDEX
    p_index = subparsers.add_parser("index", help="Scan and index a directory into the DevVault database")
    p_index.add_argument("folder", type=str, help="Target workspace directory to scan")
    p_index.add_argument("--force-rehash", action="store_true", help="Force re-calculating SHA-256 for all files")
    p_index.add_argument("--no-prune", action="store_true", help="Do not prune removed files from index")
    p_index.add_argument("--batch-size", type=int, default=500, help="Database write batch size (default: 500)")

    # 2. SEARCH
    p_search = subparsers.add_parser("search", help="Search indexed files by query, extension, tag, or size")
    p_search.add_argument("query", nargs="?", default=None, help="Search query string or glob pattern (e.g. '*.ts')")
    p_search.add_argument("--ext", "--extension", dest="extension", type=str, default=None, help="Filter by file extension")
    p_search.add_argument("--tag", type=str, default=None, help="Filter by custom tag")
    p_search.add_argument("--min-size", type=int, default=None, help="Minimum file size in bytes")
    p_search.add_argument("--max-size", type=int, default=None, help="Maximum file size in bytes")
    p_search.add_argument("--regex", type=str, default=None, help="Regular expression pattern to filter results")
    p_search.add_argument("--sort", choices=["filename", "size", "modified_at", "path"], default="filename", help="Sort field")
    p_search.add_argument("--desc", action="store_true", help="Sort in descending order")
    p_search.add_argument("--limit", type=int, default=50, help="Maximum results to return (default: 50)")

    # 3. DUPLICATES
    p_dup = subparsers.add_parser("duplicates", help="Find identical duplicate files by SHA-256 content hash")
    p_dup.add_argument("folder", nargs="?", default=None, help="Scan folder directly for duplicates on disk")
    p_dup.add_argument("--from-index", action="store_true", help="Find duplicates directly from pre-indexed database")
    p_dup.add_argument("--min-size", type=int, default=1, help="Minimum file size in bytes (default: 1)")

    # 4. STATS
    p_stats = subparsers.add_parser("stats", help="Display workspace statistics, storage usage, and top extensions")
    p_stats.add_argument("--top", type=int, default=10, help="Number of top extensions & largest files to display")

    # 5. TAG
    p_tag = subparsers.add_parser("tag", help="Manage custom tags for indexed files")
    p_tag.add_argument("file", nargs="?", default=None, help="Target file path to tag/untag")
    p_tag.add_argument("--add", type=str, default=None, help="Add tag to file")
    p_tag.add_argument("--remove", type=str, default=None, help="Remove tag from file")
    p_tag.add_argument("--list", action="store_true", help="List all tags and their frequency counts")
    p_tag.add_argument("--auto", action="store_true", help="Auto-tag files by standard developer extensions")
    p_tag.add_argument("--bulk-ext", nargs=2, metavar=("EXT", "TAG"), help="Bulk assign TAG to all files with EXT")

    # 6. REPORT
    p_report = subparsers.add_parser("report", help="Generate a comprehensive workspace analysis report")
    p_report.add_argument("--format", choices=["text", "json", "csv"], default="text", help="Output format")
    p_report.add_argument("--output", "-o", type=str, default=None, help="Save report to specified file path")

    return parser


def handle_index(args: argparse.Namespace, db: DatabaseManager, use_color: bool) -> int:
    """Handle 'index' subcommand."""
    folder_path = os.path.abspath(args.folder)
    if not os.path.isdir(folder_path):
        print(_colorize(f"Error: Directory does not exist: {folder_path}", COLOR_RED, use_color), file=sys.stderr)
        return 1

    print(_colorize(f"[*] Indexing workspace: {folder_path} ...", COLOR_CYAN, use_color))

    def on_progress(count: int, file_path: str) -> None:
        if count % 250 == 0:
            print(f"    ... scanned {count:,} files (current: {os.path.basename(file_path)})")

    indexer = WorkspaceIndexer(
        db_manager=db,
        batch_size=args.batch_size,
        progress_callback=on_progress,
    )

    stats = indexer.index_directory(
        target_dir=folder_path,
        prune_missing=not args.no_prune,
        force_rehash=args.force_rehash,
    )

    print(_colorize("[+] Indexing complete!", COLOR_GREEN, use_color))
    print(f"    Total scanned: {stats.total_scanned:,}")
    print(f"    Total indexed: {stats.total_indexed:,}")
    print(f"    Unchanged skipped: {stats.total_skipped:,}")
    if stats.total_pruned > 0:
        print(f"    Stale pruned:  {stats.total_pruned:,}")
    if stats.total_errors > 0:
        print(_colorize(f"    Errors:        {stats.total_errors:,}", COLOR_YELLOW, use_color))
    print(f"    Duration:      {stats.duration_seconds:.2f}s")
    return 0


def handle_search(args: argparse.Namespace, db: DatabaseManager, use_color: bool) -> int:
    """Handle 'search' subcommand."""
    engine = SearchEngine(db)
    query_params = SearchQuery(
        query=args.query,
        extension=args.extension,
        tag=args.tag,
        min_size_bytes=args.min_size,
        max_size_bytes=args.max_size,
        regex=args.regex,
        sort_by=args.sort,
        sort_desc=args.desc,
        limit=args.limit,
    )

    res = engine.search(query_params)
    if not res.records:
        print(_colorize("No matching files found.", COLOR_YELLOW, use_color))
        return 0

    print(_colorize(f"Found {res.total_matches:,} matches (showing {len(res.records)}):", COLOR_GREEN, use_color))
    print("-" * 80)
    for r in res.records:
        tags_str = f" [{_colorize(', '.join(r.tags), COLOR_MAGENTA, use_color)}]" if r.tags else ""
        size_str = _colorize(f"{format_bytes(r.size_bytes):>9}", COLOR_CYAN, use_color)
        print(f"  {size_str}  {_colorize(r.filename, COLOR_BOLD, use_color)}{tags_str}")
        print(f"             {_colorize(r.path, COLOR_DIM, use_color)}")
    print("-" * 80)
    return 0


def handle_duplicates(args: argparse.Namespace, db: DatabaseManager, use_color: bool) -> int:
    """Handle 'duplicates' subcommand."""
    detector = DuplicateDetector(db)

    if args.folder:
        folder_path = os.path.abspath(args.folder)
        print(_colorize(f"[*] Scanning for duplicates on disk: {folder_path} ...", COLOR_CYAN, use_color))
        report = detector.scan_and_find_duplicates(folder_path, min_size_bytes=args.min_size)
    else:
        print(_colorize("[*] Checking for duplicates from index database ...", COLOR_CYAN, use_color))
        report = detector.find_duplicates_in_index(min_size_bytes=args.min_size)

    if not report.groups:
        print(_colorize("[+] No duplicate files detected!", COLOR_GREEN, use_color))
        return 0

    print(_colorize(f"[!] Found {report.total_groups:,} duplicate groups ({report.total_duplicate_files:,} files, {format_bytes(report.total_wasted_bytes)} recoverable space):", COLOR_YELLOW, use_color))
    print("=" * 80)
    for idx, g in enumerate(report.groups, 1):
        print(f"Group #{idx} (SHA-256: {_colorize(g.content_hash[:16] + '...', COLOR_DIM, use_color)})")
        print(f"  Size: {format_bytes(g.size_bytes)} each | Copies: {g.file_count} | Redundant: {_colorize(format_bytes(g.wasted_bytes), COLOR_RED, use_color)}")
        for f in g.files:
            print(f"    - {f.path}")
        print()
    print("=" * 80)
    return 0


def handle_stats(args: argparse.Namespace, db: DatabaseManager, use_color: bool) -> int:
    """Handle 'stats' subcommand."""
    engine = StatisticsEngine(db)
    stats = engine.calculate_stats(top_extensions_limit=args.top, largest_files_limit=args.top)
    text_report = ReportGenerator.stats_to_text(stats)
    print(text_report)
    return 0


def handle_tag(args: argparse.Namespace, db: DatabaseManager, use_color: bool) -> int:
    """Handle 'tag' subcommand."""
    manager = TagManager(db)

    # List tags
    if args.list:
        tags = manager.list_all_tags()
        if not tags:
            print(_colorize("No tags found in database.", COLOR_YELLOW, use_color))
            return 0
        print(_colorize(f"Existing Tags ({len(tags)}):", COLOR_GREEN, use_color))
        for t in tags:
            print(f"  - {_colorize(t.tag_name, COLOR_MAGENTA, use_color)}: {t.file_count:,} file(s)")
        return 0

    # Auto tag
    if args.auto:
        print(_colorize("[*] Auto-tagging common developer asset extensions...", COLOR_CYAN, use_color))
        res = manager.auto_tag_common_types()
        for tag, count in res.items():
            print(f"  Tagged {count:,} files as '{_colorize(tag, COLOR_MAGENTA, use_color)}'")
        return 0

    # Bulk extension tag
    if args.bulk_ext:
        ext, tag_name = args.bulk_ext
        count = manager.tag_by_extension(ext, tag_name)
        print(_colorize(f"[+] Successfully tagged {count:,} '{ext}' files with '{tag_name}'.", COLOR_GREEN, use_color))
        return 0

    # File specific actions
    if args.file:
        file_path = os.path.abspath(args.file)
        if args.add:
            ok = manager.add_tag_to_file(file_path, args.add)
            if ok:
                print(_colorize(f"[+] Tag '{args.add}' added to {file_path}", COLOR_GREEN, use_color))
            else:
                print(_colorize(f"Failed to add tag. Is the file indexed in DevVault?", COLOR_RED, use_color), file=sys.stderr)
                return 1
        elif args.remove:
            ok = manager.remove_tag_from_file(file_path, args.remove)
            if ok:
                print(_colorize(f"[+] Tag '{args.remove}' removed from {file_path}", COLOR_GREEN, use_color))
            else:
                print(_colorize(f"Tag not found on specified file.", COLOR_YELLOW, use_color))
        else:
            tags = manager.get_file_tags(file_path)
            if tags:
                print(f"Tags for {file_path}: {_colorize(', '.join(tags), COLOR_MAGENTA, use_color)}")
            else:
                print(_colorize(f"No tags found for {file_path}", COLOR_YELLOW, use_color))
        return 0

    print(_colorize("Please specify an action (e.g., --add, --remove, --list, --auto). Use --help for usage.", COLOR_YELLOW, use_color))
    return 1


def handle_report(args: argparse.Namespace, db: DatabaseManager, use_color: bool) -> int:
    """Handle 'report' subcommand."""
    engine = StatisticsEngine(db)
    stats = engine.calculate_stats()

    if args.format == "json":
        output_content = ReportGenerator.stats_to_json(stats)
    elif args.format == "csv":
        output_content = ReportGenerator.stats_to_csv(stats)
    else:
        output_content = ReportGenerator.stats_to_text(stats)

    if args.output:
        ReportGenerator.save_report(output_content, args.output)
        print(_colorize(f"[+] Report saved to {os.path.abspath(args.output)}", COLOR_GREEN, use_color))
    else:
        print(output_content)

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint function."""
    parser = build_parser()
    args = parser.parse_args(argv)

    use_color = not args.no_color
    db = DatabaseManager(db_path=args.db)

    handlers = {
        "index": handle_index,
        "search": handle_search,
        "duplicates": handle_duplicates,
        "stats": handle_stats,
        "tag": handle_tag,
        "report": handle_report,
    }

    handler = handlers.get(args.command)
    if not handler:
        parser.print_help()
        return 1

    try:
        return handler(args, db, use_color)
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.", file=sys.stderr)
        return 130
    except Exception as e:
        print(_colorize(f"Error: {e}", COLOR_RED, use_color), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
