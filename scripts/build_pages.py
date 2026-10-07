# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stephen Makonin
"""Export only the reviewed static landing page and self-contained study preview."""
from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
EXPORTS = {
    "index.html": "site/index.html",
    "study/index.html": "study/offline-display/index.html",
    "LICENSE": "LICENSE",
}


def build(destination: Path) -> None:
    destination = destination.resolve()
    if destination.exists():
        raise ValueError("Use a new output directory; no existing files will be overwritten.")
    if destination == ROOT or ROOT in destination.parents and destination.relative_to(ROOT).parts[0] != "runtime":
        raise ValueError("Within the repository, export only to ignored runtime/.")
    for source in EXPORTS.values():
        path = ROOT / source
        if not path.is_file() or path.is_symlink():
            raise ValueError("All publication inputs must be ordinary files.")
    html = (ROOT / EXPORTS["study/index.html"]).read_text()
    if "connect-src 'none'" not in html or "form-action 'none'" not in html:
        raise ValueError("The preview must retain its no-collection policy.")
    destination.mkdir(parents=True)
    for target, source in EXPORTS.items():
        path = destination / target
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / source, path)
    (destination / ".nojekyll").write_text("")
    for name in sorted(EXPORTS):
        digest = sha256((destination / name).read_bytes()).hexdigest()
        print(f"{name}: {digest}")
    print("Exported landing page and no-collection study preview; no server configuration or research records.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    build(parser.parse_args().output)
