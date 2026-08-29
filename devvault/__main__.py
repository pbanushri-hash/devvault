"""Executable launcher for running DevVault as a module (`python3 -m devvault`)."""

import sys
from devvault.cli import main

if __name__ == "__main__":
    sys.exit(main())
