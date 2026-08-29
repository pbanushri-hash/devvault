"""Report Generation Module for DevVault.

Exports workspace analysis, search results, duplicate groups, and inventory
into JSON, CSV, and formatted Plain Text using only the Python Standard Library.
"""

import csv
from dataclasses import asdict
from datetime import datetime, timezone
import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, TextIO

from devvault.database import FileRecord
from devvault.duplicates import DuplicateReport
from devvault.search import SearchResult
from devvault.statistics import WorkspaceStats, format_bytes


class ReportGenerator:
    """Generates structured reports in JSON, CSV, and Plain Text formats."""

    @staticmethod
    def stats_to_json(stats: WorkspaceStats, indent: int = 2) -> str:
        """Serialize WorkspaceStats into formatted JSON string."""
        data: Dict[str, Any] = {
            "generated_at": stats.generated_at,
            "summary": {
                "total_files": stats.total_files,
                "total_storage_bytes": stats.total_storage_bytes,
                "total_storage_formatted": format_bytes(stats.total_storage_bytes),
                "total_tags": stats.total_tags,
            },
            "extensions": [
                {
                    "extension": e.extension,
                    "file_count": e.file_count,
                    "total_size_bytes": e.total_size_bytes,
                    "total_size_formatted": format_bytes(e.total_size_bytes),
                    "percentage_storage": e.percentage_storage,
                    "percentage_files": e.percentage_files,
                }
                for e in stats.extensions
            ],
            "largest_files": [
                {
                    "path": f.path,
                    "filename": f.filename,
                    "size_bytes": f.size_bytes,
                    "size_formatted": format_bytes(f.size_bytes),
                    "modified_at": f.modified_at,
                    "tags": f.tags,
                }
                for f in stats.largest_files
            ],
            "duplicates": (
                {
                    "total_groups": stats.duplicate_report.total_groups,
                    "total_duplicate_files": stats.duplicate_report.total_duplicate_files,
                    "total_wasted_bytes": stats.duplicate_report.total_wasted_bytes,
                    "total_wasted_formatted": format_bytes(stats.duplicate_report.total_wasted_bytes),
                    "groups": [
                        {
                            "content_hash": g.content_hash,
                            "size_bytes": g.size_bytes,
                            "size_formatted": format_bytes(g.size_bytes),
                            "file_count": g.file_count,
                            "wasted_bytes": g.wasted_bytes,
                            "files": [f.path for f in g.files],
                        }
                        for g in stats.duplicate_report.groups
                    ],
                }
                if stats.duplicate_report
                else None
            ),
        }
        return json.dumps(data, indent=indent)

    @staticmethod
    def stats_to_csv(stats: WorkspaceStats) -> str:
        """Export workspace extension and file breakdown into a multi-section CSV string."""
        output = io.StringIO()
        writer = csv.writer(output)

        # Section 1: Summary
        writer.writerow(["--- WORKSPACE SUMMARY ---"])
        writer.writerow(["Metric", "Value", "Formatted"])
        writer.writerow(["Total Files", stats.total_files, ""])
        writer.writerow(["Total Storage (Bytes)", stats.total_storage_bytes, format_bytes(stats.total_storage_bytes)])
        writer.writerow(["Total Distinct Tags", stats.total_tags, ""])
        writer.writerow([])

        # Section 2: Extension Breakdown
        writer.writerow(["--- EXTENSION BREAKDOWN ---"])
        writer.writerow(["Extension", "File Count", "Size (Bytes)", "Size (Formatted)", "% Storage", "% Files"])
        for e in stats.extensions:
            writer.writerow([
                e.extension,
                e.file_count,
                e.total_size_bytes,
                format_bytes(e.total_size_bytes),
                f"{e.percentage_storage}%",
                f"{e.percentage_files}%",
            ])
        writer.writerow([])

        # Section 3: Largest Files
        writer.writerow(["--- TOP LARGEST FILES ---"])
        writer.writerow(["Filename", "Size (Bytes)", "Size (Formatted)", "Modified At", "Path", "Tags"])
        for f in stats.largest_files:
            writer.writerow([
                f.filename,
                f.size_bytes,
                format_bytes(f.size_bytes),
                f.modified_at,
                f.path,
                ";".join(f.tags),
            ])

        return output.getvalue()

    @staticmethod
    def stats_to_text(stats: WorkspaceStats) -> str:
        """Render a clean, human-readable terminal/plain text report."""
        lines: List[str] = []
        divider = "=" * 70
        subdivider = "-" * 70

        lines.append(divider)
        lines.append("  DEVVAULT WORKSPACE ANALYSIS REPORT")
        lines.append(f"  Generated at: {stats.generated_at}")
        lines.append(divider)
        lines.append("")
        lines.append("OVERVIEW:")
        lines.append(f"  Total Indexed Files:  {stats.total_files:,}")
        lines.append(f"  Total Storage Size:   {format_bytes(stats.total_storage_bytes)} ({stats.total_storage_bytes:,} bytes)")
        lines.append(f"  Total Unique Tags:    {stats.total_tags:,}")
        if stats.duplicate_report:
            lines.append(f"  Duplicate Groups:     {stats.duplicate_report.total_groups:,}")
            lines.append(f"  Duplicate Files:      {stats.duplicate_report.total_duplicate_files:,}")
            lines.append(f"  Wasted Space:         {format_bytes(stats.duplicate_report.total_wasted_bytes)}")
        lines.append("")

        lines.append(subdivider)
        lines.append("TOP EXTENSIONS:")
        lines.append(f"  {'Extension':<12} {'Files':<10} {'Storage':<14} {'% Space':<10} {'% Files':<10}")
        lines.append("  " + "-" * 56)
        for e in stats.extensions[:10]:
            lines.append(
                f"  {e.extension:<12} {e.file_count:<10,d} {format_bytes(e.total_size_bytes):<14} {e.percentage_storage:<9.1f}% {e.percentage_files:<9.1f}%"
            )
        lines.append("")

        if stats.largest_files:
            lines.append(subdivider)
            lines.append("TOP LARGEST FILES:")
            for idx, lf in enumerate(stats.largest_files[:10], 1):
                tags_str = f" [tags: {', '.join(lf.tags)}]" if lf.tags else ""
                lines.append(f"  {idx:>2}. {format_bytes(lf.size_bytes):<10} {lf.filename}{tags_str}")
                lines.append(f"      Path: {lf.path}")
            lines.append("")

        if stats.duplicate_report and stats.duplicate_report.groups:
            lines.append(subdivider)
            lines.append(f"DUPLICATE CLUSTERS ({len(stats.duplicate_report.groups)} groups):")
            for idx, g in enumerate(stats.duplicate_report.groups[:5], 1):
                lines.append(f"  Group #{idx}: SHA256 {g.content_hash[:12]}... ({format_bytes(g.size_bytes)} each, {g.file_count} copies, {format_bytes(g.wasted_bytes)} wasted)")
                for f in g.files:
                    lines.append(f"    - {f.path}")
            if len(stats.duplicate_report.groups) > 5:
                lines.append(f"    ... and {len(stats.duplicate_report.groups) - 5} more groups.")
            lines.append("")

        lines.append(divider)
        return "\n".join(lines)

    @staticmethod
    def search_results_to_json(results: SearchResult, indent: int = 2) -> str:
        """Serialize search results to JSON format."""
        data = {
            "total_matches": results.total_matches,
            "returned_count": len(results.records),
            "files": [
                {
                    "path": r.path,
                    "filename": r.filename,
                    "extension": r.extension,
                    "size_bytes": r.size_bytes,
                    "size_formatted": format_bytes(r.size_bytes),
                    "modified_at": r.modified_at,
                    "content_hash": r.content_hash,
                    "tags": r.tags,
                }
                for r in results.records
            ],
        }
        return json.dumps(data, indent=indent)

    @staticmethod
    def search_results_to_csv(results: SearchResult) -> str:
        """Export search results to CSV format."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Filename", "Extension", "Size (Bytes)", "Size (Formatted)", "Modified At", "Path", "Tags", "SHA-256"])
        for r in results.records:
            writer.writerow([
                r.filename,
                r.extension,
                r.size_bytes,
                format_bytes(r.size_bytes),
                r.modified_at,
                r.path,
                ";".join(r.tags),
                r.content_hash or "",
            ])
        return output.getvalue()

    @staticmethod
    def save_report(content: str, output_path: str | Path) -> None:
        """Save report content string to target file on disk safely."""
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
