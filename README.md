# DevVault 🗄️

> **High-Performance Local Workspace Indexer, Search Engine, & Analysis Suite.**
> **Zero External Dependencies** — Built 100% with the Python Standard Library.

---

## 🌟 Key Features

- **⚡ Lightning-Fast Incremental Indexer**: Scans directory trees recursively, intelligently skips `.git`, `node_modules`, `__pycache__`, and hidden files, and performs differential re-indexing using mtime/size guards to avoid redundant SHA-256 computation.
- **🔍 Versatile Search Engine**: Sub-millisecond queries supporting substring searches, glob wildcards (`*`, `?`), extension filters, custom tags, size ranges, date ranges, and Python regex matching.
- **🧬 Two-Tier Duplicate Detection**: Multi-stage disk and index duplicate clustering (file size grouping $\rightarrow$ 4KB prefix hash $\rightarrow$ full SHA-256) calculating recoverable disk space.
- **🏷️ Flexible Tagging System**: Tag files individually, query by tag, or auto-tag by standard developer extensions (Python, TypeScript, Web, Config, Docs, Database).
- **📊 Analytics & Multi-Format Reports**: Instant storage breakdowns, extension distributions, top largest files, and exports to **JSON**, **CSV**, and formatted **Plain Text**.
- **🛡️ 100% Zero Dependencies**: Runs everywhere Python 3.8+ is installed (`sqlite3`, `hashlib`, `argparse`, `dataclasses`, `pathlib`).

---

## 🚀 Quick Start

### 1. Run DevVault CLI
You can run DevVault directly via Python:

```bash
# As a Python module
python3 -m devvault --help

# Or via the root script
python3 devvault.py --help
```

---

## 💻 CLI Commands & Usage

### 1. Index a Workspace Directory
Scans and indexes files into an optimized local SQLite database (stored at `~/.devvault/vault.db` by default):

```bash
# Index current directory
python3 devvault.py index .

# Index a specific project
python3 devvault.py index /path/to/project

# Force re-hashing of all files
python3 devvault.py index /path/to/project --force-rehash
```

### 2. Search Indexed Files
Query your indexed workspace with flexible filters:

```bash
# General query or glob pattern
python3 devvault.py search "auth"
python3 devvault.py search "*.tsx"

# Filter by extension and sort by size
python3 devvault.py search --ext py --sort size --desc

# Filter by custom tag and size range
python3 devvault.py search --tag backend --min-size 1024

# Search using regular expressions
python3 devvault.py search --regex r"test_.*\.py$"
```

### 3. Duplicate Detection
Find identical redundant files and compute recoverable disk space:

```bash
# Find duplicates across indexed files in database
python3 devvault.py duplicates --from-index

# Scan any folder on disk directly without prior indexing
python3 devvault.py duplicates /path/to/downloads
```

### 4. Workspace Statistics
Inspect storage usage, top extensions, and largest files:

```bash
python3 devvault.py stats
```

### 5. Tag Management
Organize files with custom developer tags:

```bash
# Add tag to a file
python3 devvault.py tag ./src/main.py --add backend

# List all existing tags
python3 devvault.py tag --list

# Bulk tag all Python files
python3 devvault.py tag --bulk-ext py python

# Automatically tag common developer assets
python3 devvault.py tag --auto
```

### 6. Export Reports
Generate detailed analysis reports in JSON, CSV, or Text format:

```bash
# Terminal summary
python3 devvault.py report

# Export JSON to file
python3 devvault.py report --format json --output report.json

# Export CSV to file
python3 devvault.py report --format csv --output report.csv
```

---

## 🧪 Running Unit Tests

Run the complete test suite using Python's built-in `unittest` runner:

```bash
python3 -m unittest discover -s tests -v
```

---

## 🏗️ Architecture & Modules

```
devvault/
├── __init__.py      # Package exports and public API
├── __main__.py      # Entry point for python3 -m devvault
├── cli.py           # Command-Line Interface (argparse)
├── database.py      # SQLite WAL-mode schema and persistence
├── duplicates.py    # Multi-tier duplicate detection engine
├── indexer.py       # Differential incremental workspace indexer
├── reports.py       # Multi-format report exporter (JSON, CSV, Text)
├── scanner.py       # Directory traversal and SHA-256 hasher
├── search.py        # Parameterized query and regex search engine
├── statistics.py    # Storage metrics & extension aggregations
└── tags.py          # Custom tagging and heuristic tagging engine

tests/
├── test_cli.py
├── test_database.py
├── test_duplicates.py
├── test_indexer.py
├── test_reports.py
├── test_scanner.py
├── test_search.py
└── test_tags.py
```

---

## 🔒 Zero External Dependency Guarantee

DevVault uses **only** modules from the Python Standard Library:
`argparse`, `collections`, `contextlib`, `csv`, `dataclasses`, `datetime`, `hashlib`, `io`, `json`, `os`, `pathlib`, `re`, `sqlite3`, `sys`, `tempfile`, `typing`, `unittest`. No `pip install` required!
