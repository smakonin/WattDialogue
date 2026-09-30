# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stephen Makonin
"""Create a separate reference-free local bundle from authorised HyNILM outputs."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wattdialogue.adapter import ReplayStore


def export(source_root, output):
    source_root = Path(source_root).resolve()
    output = Path(output).resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError("Keep replay exports outside the code repository.")
    if output == source_root or source_root in output.parents:
        raise ValueError("Keep the export separate from the source archive.")
    if output.exists():
        raise ValueError("Choose a new output directory; existing data will not be replaced.")
    store = ReplayStore(source_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="wattdialogue-replay-", dir=output.parent))
    try:
        files = []
        for home, blocks in store.list_blocks().items():
            for block in blocks:
                online = store.load(home, block, "online")
                revised = store.load(home, block, "revised")
                if not np.array_equal(online.t, revised.t):
                    raise ValueError("Immediate and revised observations do not share timestamps.")
                relative = Path("runs") / home / "verification" / f"{block}.npz"
                destination = temporary / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                np.savez_compressed(destination, t=online.t, P=online.aggregate_w[:, None],
                                    control_P_online=online.components_w, control_P_revised=revised.components_w)
                files.append({"file": relative.as_posix(), "rows": len(online.t),
                              "online_content_hash": online.content_hash, "revised_content_hash": revised.content_hash})
        manifest = {"input_kind": "archive_replay", "synthetic_fixture": False,
                    "private_local_bundle": True, "arrays": ["t", "P[:,0]", "control_P_online", "control_P_revised"],
                    "model_version": store.source_metadata()["model_version"], "files": files,
                    "notes": ["No submeter references, reference labels, joint validity mask or credentials.",
                              "Aggregate activity remains household data; this bundle is not a public release."]}
        (temporary / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {"files": len(files), "output": str(output), "references_excluded": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, help="Authorised existing archive; never modified.")
    parser.add_argument("--output", required=True, help="New local directory outside the code repository.")
    args = parser.parse_args()
    try:
        print(json.dumps(export(args.source_root, args.output)))
    except (ValueError, FileNotFoundError) as exc:
        parser.exit(1, str(exc) + "\n")
