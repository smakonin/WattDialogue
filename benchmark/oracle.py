# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stephen Makonin
"""Independent numerical oracle. Never imports the bridge or uses reference channels.

The archive's power rows cover [t, t + native cadence), not the gap to the
next timestamp. A row may be integrated only after that whole interval is
available. A clipped query does not make a future meter row available early.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
import re

import numpy as np

CADENCE = {"demo_1s": 1.0, "demo_60s": 60.0}
DEFAULT_MODEL_VERSION = "synthetic-demo-v1/control/P"


def file_hash(path):
    digest = sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def timestamp(value):
    """Accept finite Unix seconds or an ISO timestamp with an explicit zone."""
    if isinstance(value, (bool, np.bool_)):
        raise ValueError("A boolean is not a timestamp")
    if isinstance(value, (int, float, np.integer, np.floating)):
        result = float(value)
    elif isinstance(value, str):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("An ISO timestamp must include its time zone")
        result = dt.timestamp()
    else:
        raise ValueError("Expected Unix seconds or a zoned ISO timestamp")
    if not np.isfinite(result):
        raise ValueError("Time must be finite")
    return result


@dataclass(frozen=True)
class OracleDataset:
    recording: str
    block_id: str
    t: np.ndarray
    aggregate: np.ndarray
    components: np.ndarray
    cadence: float
    source_sha256: str = "synthetic-fixture"
    evidence_content_hash: str = ""
    boundary: str = "Declared synthetic aggregate"
    model_version: str = DEFAULT_MODEL_VERSION

    def __post_init__(self):
        if not isinstance(self.recording, str) or not self.recording:
            raise ValueError("A recording identifier is required")
        if self.t.ndim != 1 or len(self.t) == 0:
            raise ValueError("Timestamp vector must be nonempty")
        if self.aggregate.shape != self.t.shape:
            raise ValueError("Aggregate shape does not match timestamps")
        if self.components.shape != (len(self.t), 24):
            raise ValueError("Expected 24 anonymous component slots")
        if not np.all(np.isfinite(self.t)) or np.any(np.diff(self.t) < self.cadence):
            raise ValueError("Overlapping, duplicated, or unordered meter intervals")
        if not np.isfinite(self.cadence) or self.cadence <= 0:
            raise ValueError("Cadence must be positive")
        # Independent implementation of the frozen public evidence encoding;
        # this hashes whitelisted arrays only, rather than the reference-bearing NPZ.
        digest = sha256(f"{self.model_version}/{self.recording}/{self.block_id}/online".encode())
        for array in (self.t, self.aggregate, self.components):
            digest.update(np.asarray(array, dtype=np.float64).tobytes())
        object.__setattr__(self, "evidence_content_hash", digest.hexdigest())

    @property
    def start(self):
        return float(self.t[0])

    @property
    def end(self):
        return float(self.t[-1] + self.cadence)


def load_dataset(path, recording, block_id=None, *, cadence=None, boundary="Declared synthetic aggregate", model_version=DEFAULT_MODEL_VERSION):
    """Only these three original fields are read; even `valid` is excluded."""
    cadence = CADENCE.get(recording) if cadence is None else cadence
    if cadence is None:
        raise ValueError("Supply the documented native cadence; it is never inferred across gaps")
    with np.load(Path(path), allow_pickle=False) as archive:
        t = np.asarray(archive["t"], dtype=np.float64).copy()
        aggregate = np.asarray(archive["P"][:, 0], dtype=np.float64).copy()
        components = np.asarray(archive["control_P_online"], dtype=np.float64).copy()
    return OracleDataset(recording, str(block_id or Path(path).stem), t,
                         aggregate, components, float(cadence), file_hash(path),
                         boundary=boundary, model_version=model_version)


def _integrate(power, seconds, mask):
    if not np.any(mask):
        return None
    return float(np.sum(power[mask] * seconds[mask], dtype=np.float64) / 3_600_000.0)


def summarize(dataset, start, end, as_of, component_id=None):
    start, end, as_of = map(timestamp, (start, end, as_of))
    if end <= start:
        raise ValueError("end must exceed start")
    row_end = dataset.t + dataset.cadence
    overlap = np.maximum(0, np.minimum(row_end, end) - np.maximum(dataset.t, start))
    available = row_end <= as_of
    meter_mask = (overlap > 0) & available & np.isfinite(dataset.aggregate)
    component_mask = meter_mask & np.all(np.isfinite(dataset.components), axis=1)
    observed = float(np.sum(overlap[meter_mask]))
    component_observed = float(np.sum(overlap[component_mask]))
    duration = end - start
    component_energy = {
        f"component_{i:03d}": _integrate(dataset.components[:, i], overlap, component_mask)
        for i in range(24)
    }
    residual = dataset.aggregate - np.sum(dataset.components, axis=1)
    energy = _integrate(dataset.aggregate, overlap, meter_mask)
    fields = {
        "energy_kwh": energy,
        "average_power_w": None if energy is None else energy * 3_600_000.0 / observed,
        "peak_power_w": float(np.max(dataset.aggregate[meter_mask])) if np.any(meter_mask) else None,
        "coverage_fraction": observed / duration,
        "observed_seconds": observed,
        "component_coverage_fraction": component_observed / duration,
        "component_energy_kwh": component_energy,
        "signed_residual_energy_kwh": _integrate(residual, overlap, component_mask),
        "unexplained_energy_kwh": _integrate(np.maximum(residual, 0), overlap, component_mask),
        "overallocated_energy_kwh": _integrate(np.maximum(-residual, 0), overlap, component_mask),
    }
    if component_id is not None:
        if not re.fullmatch(r"component_\d{3}", component_id) or component_id not in component_energy:
            raise ValueError("Unknown component slot")
        fields["component_energy_kwh"] = component_energy[component_id]
    through = float(np.max(row_end[available & np.isfinite(dataset.aggregate)])) if np.any(available & np.isfinite(dataset.aggregate)) else None
    used_through = float(np.max(row_end[meter_mask])) if np.any(meter_mask) else None
    status = "no_data" if observed == 0 else ("ok" if np.isclose(observed, duration, rtol=0, atol=1e-8) else "partial")
    return {
        "status": status,
        "fields": fields,
        "evidence": {
            "recording": dataset.recording, "block_id": dataset.block_id,
            "measurement_boundary": dataset.boundary,
            "model_version": dataset.model_version,
            "mode": "online", "start": start, "end": end, "as_of": as_of,
            "native_cadence_seconds": dataset.cadence,
            "coverage_fraction": (component_observed if component_id is not None else observed) / duration,
            "meter_coverage_fraction": observed / duration,
            "component_coverage_fraction": component_observed / duration,
            "observed_seconds": observed, "requested_seconds": duration,
            "available_through": through, "used_through": used_through,
            "stale_seconds": None if through is None else max(0.0, as_of - through),
            "source_sha256": dataset.source_sha256,
            "evidence_content_hash": dataset.evidence_content_hash,
        },
    }


def compare_periods(dataset, period_a, period_b, as_of):
    a = summarize(dataset, period_a["start"], period_a["end"], as_of)
    b = summarize(dataset, period_b["start"], period_b["end"], as_of)
    ea, eb = a["fields"]["energy_kwh"], b["fields"]["energy_kwh"]
    difference = None if ea is None or eb is None else eb - ea
    return {
        "status": "ok" if a["status"] == b["status"] == "ok" else "insufficient_evidence",
        "fields": {
            "period_a_energy_kwh": ea, "period_b_energy_kwh": eb,
            "difference_kwh": difference,
            "difference_percent": None if difference is None or ea == 0 else 100.0 * difference / ea,
            "period_a_coverage_fraction": a["fields"]["coverage_fraction"],
            "period_b_coverage_fraction": b["fields"]["coverage_fraction"],
        },
        "evidence": [a["evidence"], b["evidence"]],
    }


def association_category(reference_energies, share_threshold=0.80, min_energy_kwh=0.01):
    """Optional private label-scoring rule; never accepts or returns appliance names.

    Call only in a separate reference-evaluation process. This classifies one
    component's externally computed reference association, not physical identity.
    `split` needs multi-component information and is intentionally not inferred.
    """
    values = np.asarray(reference_energies, dtype=float)
    if values.ndim != 1 or not np.all(np.isfinite(values)) or np.any(values < 0):
        raise ValueError("Association energies must be a finite nonnegative vector")
    total = float(values.sum())
    if total < min_energy_kwh or len(values) == 0:
        return {"category": "unmatched", "dominant_index": None}
    i = int(np.argmax(values))
    return {"category": "single_reference" if values[i] / total >= share_threshold else "mixed",
            "dominant_index": i if values[i] / total >= share_threshold else None}
