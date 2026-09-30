# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stephen Makonin
"""Separate, versioned human annotations; these never alter NILM inference."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import copy
import json
import os
import tempfile
import threading

from .adapter import BLOCKS, MODEL_VERSION, component_id, iso_time, parse_time

STATUSES = ("unknown", "candidate", "occupant-confirmed", "verified")


class LabelRegistry:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else None
        self._lock = threading.RLock()
        self._records = {}
        if self.path is not None and self.path.exists():
            payload = json.loads(self.path.read_text())
            if payload.get("schema_version") != 1:
                raise ValueError("Unsupported label registry schema")
            self._records = payload.get("records", {})

    @staticmethod
    def _key(recording, component, model_version):
        if not isinstance(recording, str) or recording not in BLOCKS:
            raise ValueError("Label home must be R1Hz or AMPds2")
        if not isinstance(model_version, str) or not model_version:
            raise ValueError("A nonempty model_version is required")
        return f"{recording}/{model_version}/{component_id(component)}"

    def get(self, recording, component, model_version=MODEL_VERSION, as_of=None):
        key = self._key(recording, component, model_version)
        limit = float("inf") if as_of is None else parse_time(as_of, "as_of")
        with self._lock:
            eligible = [r for r in self._records.get(key, []) if r["available_at_unix"] <= limit]
            if eligible:
                return copy.deepcopy(max(eligible, key=lambda r: (r["available_at_unix"], r["revision"])))
        return {
            "home_id": recording, "component_id": component_id(component),
            "model_version": model_version, "status": "unknown", "label": None,
            "source": None, "evidence": None, "alternatives": [],
            "definitive_identity": False, "available_at": None,
            "available_at_unix": None, "revision": 0,
            "identity_note": "An anonymous model slot has no verified physical appliance identity.",
        }

    def set_label(self, recording, component, label, status="candidate", source=None,
                  evidence=None, alternatives=None, model_version=MODEL_VERSION,
                  available_at=None, definitive=False):
        key = self._key(recording, component, model_version)
        if status not in STATUSES:
            raise ValueError("Label status must be unknown, candidate, occupant-confirmed or verified")
        if definitive and status != "verified":
            raise ValueError("An unverified annotation cannot assert definitive appliance identity")
        if status != "unknown" and (not isinstance(label, str) or not label.strip()):
            raise ValueError("A nonempty label is required")
        if status != "unknown" and (not source or not evidence):
            raise ValueError("Label annotations require their source and evidence")
        source_kind = source.get("kind") if isinstance(source, dict) else source
        if status == "verified" and source_kind != "independent_verification":
            raise ValueError("Verified identity requires explicit independent_verification evidence")
        if status == "occupant-confirmed" and source_kind not in ("occupant", "occupant_confirmation"):
            raise ValueError("Occupant-confirmed labels require an occupant source")
        alternatives = [] if alternatives is None else alternatives
        if not isinstance(alternatives, list):
            raise ValueError("alternatives must be a JSON list")
        available = datetime.now(timezone.utc).timestamp() if available_at is None else parse_time(available_at, "available_at")
        # Validate JSON safety before modifying or persisting the registry.
        try:
            json.dumps({"source": source, "evidence": evidence, "alternatives": alternatives}, allow_nan=False)
        except (ValueError, TypeError) as exc:
            raise ValueError("Label evidence must be finite JSON-serializable data") from exc
        with self._lock:
            history = self._records.setdefault(key, [])
            record = {
                "home_id": recording, "component_id": component_id(component),
                "model_version": model_version, "status": status,
                "label": None if status == "unknown" else label.strip(),
                "source": copy.deepcopy(source), "evidence": copy.deepcopy(evidence),
                "alternatives": copy.deepcopy(alternatives),
                "definitive_identity": status == "verified",
                "available_at": iso_time(available), "available_at_unix": available,
                "revision": len(history) + 1,
                "identity_note": "Independently verified annotation." if status == "verified" else "Human annotation; physical component identity is not independently verified.",
            }
            history.append(record)
            self._save()
            return copy.deepcopy(record)

    def propose(self, recording, component, label, *, source, evidence, alternatives=None,
                model_version=MODEL_VERSION, available_at=None):
        return self.set_label(recording, component, label, "candidate", source, evidence,
                              alternatives, model_version, available_at)

    def confirm(self, recording, component, label, *, evidence, alternatives=None,
                model_version=MODEL_VERSION, available_at=None):
        return self.set_label(recording, component, label, "occupant-confirmed", "occupant",
                              evidence, alternatives, model_version, available_at)

    def _save(self):
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".labels-", suffix=".json", dir=self.path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as stream:
                json.dump({"schema_version": 1, "records": self._records}, stream, allow_nan=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
