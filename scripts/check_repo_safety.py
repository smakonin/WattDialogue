# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stephen Makonin
"""Check tracked Git blobs without displaying secret contents."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PARTS = {"runtime", "private", "private-data", "replay-data", "datasets", "data", "runs", "__pycache__"}
GENERATED = {"benchmark/questions.jsonl", "benchmark/dev_questions.jsonl", "benchmark/manifest.json", "benchmark/protocol.json"}
TOKEN = re.compile(rb"(?:sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")


def findings(path: str, data: bytes) -> list[str]:
    parts = Path(path).parts
    name = Path(path).name
    problems = []
    if (name == ".env" or name.startswith(".env.") and name != ".env.example"
            or name.startswith("PRIVATE_") or any(p in FORBIDDEN_PARTS for p in parts)
            or path in GENERATED or Path(path).suffix.lower() in {".npz", ".npy", ".csv", ".pem", ".key"}):
        problems.append("private_or_generated_file")
    if TOKEN.search(data):
        problems.append("credential_pattern")
    if name == ".env.example":
        for line in data.decode("utf-8").splitlines():
            if re.match(r"\s*(?:export\s+)?OPENAI_API_KEY(?:_BACKUP)?\s*=", line):
                value = line.split("=", 1)[1].strip().strip("\"'")
                if value:
                    problems.append("populated_key_template")
    return sorted(set(problems))


def audit(root=ROOT) -> dict:
    root = Path(root)
    tracked = subprocess.run(["git", "ls-files", "--cached", "-z"], cwd=root,
                             check=True, capture_output=True).stdout.split(b"\0")
    failures = []
    count = 0
    for item in tracked:
        if not item:
            continue
        name = item.decode("utf-8")
        content = subprocess.run(["git", "show", ":" + name], cwd=root,
                                 check=True, capture_output=True).stdout
        count += 1
        reasons = findings(name, content)
        if reasons:
            failures.append({"file": name, "reasons": reasons})
    return {"passed": count > 0 and not failures, "tracked_files": count, "findings": failures}


if __name__ == "__main__":
    try:
        report = audit()
    except (OSError, subprocess.CalledProcessError, UnicodeError):
        print(json.dumps({"passed": False, "error": "Run this check inside the Git repository after staging files."}))
        raise SystemExit(1)
    print(json.dumps(report))
    sys.exit(0 if report["passed"] else 1)
