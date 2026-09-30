# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stephen Makonin
"""Run the local utility-display proof of concept."""
import argparse
from wattdialogue.server import serve

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--source-root", help="Existing frozen archive location; upstream files remain read-only.")
    parser.add_argument("--env-file", help="Existing server-only configuration file (no credential copying).")
    args = parser.parse_args()
    serve(args.port, args.source_root, args.env_file)
