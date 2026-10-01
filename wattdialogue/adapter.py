# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stephen Makonin
"""Read-only, reference-free replay of frozen HyNILM component estimates."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
import math
import threading

import numpy as np

MODEL_VERSION = "quiet_fusion_v3a/control/P"
COMPONENT_CAPACITY = 24
BLOCKS = {
    "R1Hz": (17422, 17428, 17452, 17602, 18179),
    "AMPds2": (15431, 15437, 15461, 15611, 16161),
}
CADENCE_S = {"R1Hz": 1.0, "AMPds2": 60.0}
INFERENCE_PERIOD_S = {"R1Hz": 5.0, "AMPds2": 60.0}
BOUNDARIES = {
    "R1Hz": "R1Hz independently metered residential main aggregate",
    "AMPds2": "AMPds2 MHE = WHE - rental suite (RSE) - garage (GRE)",
}


def parse_time(value: Any, name: str = "time") -> float:
    """Accept finite Unix seconds or an ISO 8601 timestamp with an offset."""
    if isinstance(value, bool):
        raise ValueError(f"{name} must be Unix seconds or timezone-aware ISO 8601")
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{name} must be Unix seconds or timezone-aware ISO 8601") from exc
        if parsed.tzinfo is None:
            raise ValueError(f"{name} needs an explicit timezone offset")
        result = parsed.timestamp()
    else:
        raise ValueError(f"{name} must be Unix seconds or timezone-aware ISO 8601")
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    try:
        datetime.fromtimestamp(result, timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError(f"{name} is outside the supported timestamp range") from exc
    return result


def iso_time(value: float | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), timezone.utc).isoformat().replace("+00:00", "Z")


def component_id(value: Any) -> str:
    if isinstance(value, bool):
        raise ValueError("component_id must identify a component slot from 0 to 23")
    if isinstance(value, int):
        index = value
    elif isinstance(value, str):
        suffix = value.removeprefix("component_")
        if not suffix.isdigit():
            raise ValueError("component_id must be component_000 through component_023")
        index = int(suffix)
    else:
        raise ValueError("component_id must be component_000 through component_023")
    if not 0 <= index < COMPONENT_CAPACITY:
        raise ValueError("component_id must be component_000 through component_023")
    return f"component_{index:03d}"


@dataclass(frozen=True)
class ReplayDataset:
    recording: str
    block_id: int
    mode: str
    t: np.ndarray
    aggregate_w: np.ndarray
    components_w: np.ndarray
    content_hash: str
    model_version: str = MODEL_VERSION
    synthetic_fixture: bool = False

    @property
    def cadence_s(self) -> float:
        return CADENCE_S[self.recording]

    @property
    def block_start(self) -> float:
        return float(self.t[0])

    @property
    def block_end(self) -> float:
        return float(self.t[-1] + self.cadence_s)

    def metadata(self) -> dict:
        source = source_metadata(self.synthetic_fixture)
        boundary = source["boundaries"][self.recording]
        return {
            **{k: v for k, v in source.items() if k not in ("boundaries", "household_labels")},
            "recording": self.recording,
            "home_id": self.recording,
            "block_id": self.block_id,
            "mode": self.mode,
            "model_version": self.model_version,
            "boundary": boundary,
            "recording_label": source["household_labels"][self.recording],
            "units": {"power": "W", "energy": "kWh"},
            "timezone": "America/Vancouver",
            "native_interval_s": self.cadence_s,
            "inference_interval_s": INFERENCE_PERIOD_S[self.recording],
            "start": iso_time(self.block_start),
            "end": iso_time(self.block_end),
            "interval_start": iso_time(self.block_start),
            "interval_end": iso_time(self.block_end),
            "available_at": iso_time(self.block_end),
            "start_unix": self.block_start,
            "end_unix": self.block_end,
            "rows": len(self.t),
            "component_capacity": COMPONENT_CAPACITY,
            "component_capacity_is_appliance_count": False,
            "evidence_content_hash": self.content_hash,
            "split": "synthetic_demonstration" if self.synthetic_fixture else "development" if self.block_id == BLOCKS[self.recording][0] else "reserved_replay",
            "scope": "Synthetic demonstration only; no household measurement, learned NILM run or experimental result." if self.synthetic_fixture else "Historical replay of user-provided frozen verification snapshots; archive authenticity requires operator verification.",
            "measurement_convention": "Native sample held over its declared interval; R1Hz integration uses the documented one-second zero-order-hold approximation.",
            "timing": "Generated vectors are held over synthetic inference intervals; completed-interval and post-block revision availability are demonstrated, not evidence of learned causal inference." if self.synthetic_fixture else "Immediate vectors already apply from their causal effective timestamps; a measured interval is available only when complete. Revised vectors are available after this UTC block ends.",
        }

    def select(self, start=None, end=None, as_of=None) -> dict:
        start = self.block_start if start is None else parse_time(start, "start")
        end = self.block_end if end is None else parse_time(end, "end")
        as_of = self.block_end if as_of is None else parse_time(as_of, "as_of")
        if end <= start:
            raise ValueError("end must be later than start")
        if self.mode == "revised" and as_of < self.block_end:
            raise ValueError("Daily revised estimates are available only after the UTC block ends")
        interval_end = self.t + self.cadence_s
        overlap = np.maximum(0.0, np.minimum(interval_end, end) - np.maximum(self.t, start))
        # A clipped subinterval still cannot use an unfinished measurement mean.
        available = (interval_end <= as_of) & (overlap > 0)
        weights = np.where(available, overlap, 0.0)
        meter_valid = available & np.isfinite(self.aggregate_w)
        component_valid = meter_valid & np.isfinite(self.components_w).all(axis=1)
        requested = end - start
        meter_seconds = float(overlap[meter_valid].sum())
        component_seconds = float(overlap[component_valid].sum())
        present_seconds = float(overlap.sum())
        completed_seconds = float(weights.sum())
        in_block_seconds = max(0.0, min(end, self.block_end) - max(start, self.block_start))
        latest_meter = float(interval_end[meter_valid].max()) if meter_valid.any() else None
        latest_effective = float(self.t[component_valid].max()) if component_valid.any() else None
        return {
            "start": start, "end": end, "as_of": as_of,
            "overlap": overlap, "weights": weights,
            "meter_valid": meter_valid, "component_valid": component_valid,
            "latest_meter": latest_meter, "latest_effective": latest_effective,
            "coverage": {
                "requested_seconds": requested,
                "present_seconds": present_seconds,
                "completed_seconds": completed_seconds,
                "valid_meter_seconds": meter_seconds,
                "valid_component_seconds": component_seconds,
                "outside_block_seconds": max(0.0, requested - in_block_seconds),
                "absent_interval_seconds": max(0.0, in_block_seconds - present_seconds),
                "not_yet_available_seconds": max(0.0, present_seconds - completed_seconds),
                "missing_meter_seconds": max(0.0, completed_seconds - meter_seconds),
                "invalid_component_seconds": max(0.0, meter_seconds - component_seconds),
                "fraction": min(1.0, meter_seconds / requested),
                "component_fraction": min(1.0, component_seconds / requested),
                "complete": math.isclose(meter_seconds, requested, rel_tol=0, abs_tol=1e-6),
                "component_complete": math.isclose(component_seconds, requested, rel_tol=0, abs_tol=1e-6),
            },
        }


def source_metadata(synthetic: bool) -> dict:
    if synthetic:
        from . import demo_data
        return {"synthetic_fixture": True, "input_kind": "synthetic", "model_version": demo_data.MODEL_VERSION,
                "data_source": "Wholly synthetic deterministic demonstration traces; no household measurements.",
                "household_labels": dict(demo_data.HOUSEHOLD_LABELS), "boundaries": dict(demo_data.BOUNDARIES)}
    return {"synthetic_fixture": False, "input_kind": "archive_replay", "model_version": MODEL_VERSION,
            "data_source": "Explicitly supplied frozen replay archive; contents require operator verification.",
            "household_labels": {"R1Hz": "R1Hz archive replay", "AMPds2": "AMPds2 archive replay"},
            "boundaries": dict(BOUNDARIES)}


class ReplayStore:
    def __init__(self, root: str | Path | None = None):
        self.synthetic_fixture = root is None
        self.root = None if root is None else Path(root)
        if self.root is not None and (self.root / "runs").is_dir():
            self.root = self.root / "runs"
        self._cache: OrderedDict[tuple, ReplayDataset] = OrderedDict()
        self._cache_lock = threading.RLock()

    @property
    def model_version(self) -> str:
        return self.source_metadata()["model_version"]

    def source_metadata(self) -> dict:
        return source_metadata(self.synthetic_fixture)

    def boundary(self, recording: str) -> str:
        if recording not in BLOCKS:
            raise ValueError("recording must be R1Hz or AMPds2")
        return self.source_metadata()["boundaries"][recording]

    def list_blocks(self, recording: str | None = None) -> dict[str, list[int]]:
        if recording is not None and (not isinstance(recording, str) or recording not in BLOCKS):
            raise ValueError("recording must be R1Hz or AMPds2")
        return {k: list(v) for k, v in BLOCKS.items() if recording is None or recording == k}

    def snapshot(self, recording, block_id):
        """Frozen replay files never change during a run; this store is its view.

        A mutable adapter must return an immutable view covering both estimate
        modes, metadata and model version, captured atomically before query work.
        """
        return self

    def load(self, recording: str, block_id: int | str, mode: str = "online") -> ReplayDataset:
        # An eviction must not interleave a cache hit, LRU update and return.
        # Miss construction is serialized to avoid duplicate large allocations.
        with self._cache_lock:
            return self._load(recording, block_id, mode)

    def _load(self, recording: str, block_id: int | str, mode: str = "online") -> ReplayDataset:
        if not isinstance(recording, str) or recording not in BLOCKS:
            raise ValueError("recording must be R1Hz or AMPds2")
        if isinstance(block_id, bool) or not str(block_id).isdigit():
            raise ValueError("block_id must be a listed integer block ID")
        block = int(block_id)
        if block not in BLOCKS[recording]:
            raise ValueError("block_id is not a listed block for this home")
        if mode not in ("online", "revised"):
            raise ValueError("mode must be online or revised")
        key = recording, block, mode
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        try:
            if self.synthetic_fixture:
                from .demo_data import synthetic_arrays
                archive = synthetic_arrays(recording, block)
                t = np.asarray(archive["t"], dtype=np.float64).copy()
                aggregate = np.asarray(archive["P"][:, 0], dtype=np.float64).copy()
                components = np.asarray(archive[f"control_P_{mode}"], dtype=np.float64).copy()
            else:
                path = self.root / recording / "verification" / f"{block}.npz"
                # Whitelist members, discard reference columns before they can
                # enter any application object; never read I or joint-valid.
                with np.load(path, allow_pickle=False) as archive:
                    t = np.asarray(archive["t"], dtype=np.float64).copy()
                    matrix = archive["P"]
                    if matrix.ndim != 2 or matrix.shape[1] < 1:
                        raise ValueError("Replay aggregate has an invalid shape")
                    aggregate = np.asarray(matrix[:, 0], dtype=np.float64).copy()
                    components = np.asarray(archive[f"control_P_{mode}"], dtype=np.float64).copy()
        except (OSError, KeyError) as exc:
            raise ValueError("The requested replay block is unavailable or incomplete") from exc
        if t.ndim != 1 or not len(t) or aggregate.shape != t.shape or components.shape != (len(t), COMPONENT_CAPACITY):
            raise ValueError("Replay arrays have inconsistent dimensions")
        if not np.isfinite(t).all() or np.any(np.diff(t) < CADENCE_S[recording]):
            raise ValueError("Replay timestamps must advance without overlapping native intervals")
        digest = sha256(f"{self.model_version}/{recording}/{block}/{mode}".encode())
        for array in (t, aggregate, components):
            digest.update(array.tobytes())
            array.setflags(write=False)
        dataset = ReplayDataset(recording, block, mode, t, aggregate, components, digest.hexdigest(), self.model_version, self.synthetic_fixture)
        self._cache[key] = dataset
        while len(self._cache) > 4:
            self._cache.popitem(last=False)
        return dataset

    def metadata(self, recording: str, block_id: int | str) -> dict:
        return self.load(recording, block_id).metadata()
