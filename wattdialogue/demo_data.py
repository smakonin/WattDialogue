# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stephen Makonin
"""Wholly synthetic, deterministic demonstration signals; no household data."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# Recording and block keys are compatibility aliases, not the source of traces.
from .adapter import BLOCKS, CADENCE_S, COMPONENT_CAPACITY, INFERENCE_PERIOD_S

MODEL_VERSION = "synthetic-demo-v1/control/P"
GENERATOR_VERSION = "wattdialogue-synthetic-v1"
DURATION_S = 6 * 3600
START_UNIX = int(datetime(2025, 1, 15, 8, tzinfo=timezone.utc).timestamp())
HOUSEHOLD_LABELS = {"R1Hz": "Synthetic home 1", "AMPds2": "Synthetic home 2"}
BOUNDARIES = {home: f"{label} aggregate; generated values, no physical meter"
              for home, label in HOUSEHOLD_LABELS.items()}


def synthetic_arrays(recording: str, block_id: int | str) -> dict[str, np.ndarray]:
    """Generate interval power and illustrative anonymous component vectors.

    No random seed, reference labels, original measurements or private files are
    used. Missingness and negative residual are intentional teaching examples.
    """
    if recording not in BLOCKS or isinstance(block_id, bool) or not str(block_id).isdigit() or int(block_id) not in BLOCKS[recording]:
        raise ValueError("Choose a listed synthetic recording and block")
    index = BLOCKS[recording].index(int(block_id))
    cadence = int(CADENCE_S[recording])
    elapsed = np.arange(0, DURATION_S, cadence, dtype=np.int64)
    phase = np.floor(elapsed / INFERENCE_PERIOD_S[recording]) * INFERENCE_PERIOD_S[recording]
    factor = 1.0 if recording == "R1Hz" else 1.2
    components = np.zeros((len(elapsed), COMPONENT_CAPACITY), dtype=np.float64)
    components[:, 0] = factor * (85 + 4 * index) * ((phase % 1800) < 600)
    components[:, 1] = factor * (900 + 20 * index) * (((phase >= 3600) & (phase < 4020)) | ((phase >= 12600) & (phase < 13080)))
    components[:, 2] = factor * (450 + 15 * index) * (((phase % 1200) < 360) & (phase < 18000))
    components[:, 3] = factor * (30 + 2 * index)
    background = factor * (65 + 8 * np.sin(2 * np.pi * elapsed / 3600))
    aggregate = components.sum(axis=1) + background
    # Simulated allocation error, not a fifth known physical appliance.
    components[:, 4] = factor * 120 * ((phase >= 9000) & (phase < 9900))
    revised = components.copy()
    revised[:, 4] *= .25
    revised[:, 0] *= .96
    aggregate[elapsed == 10800] = np.nan
    components[elapsed == 14400, 23] = np.nan
    revised[elapsed == 14400, 23] = np.nan
    present = elapsed != 7200
    start = START_UNIX + (index + (12 if recording == "AMPds2" else 0)) * 86400
    return {"t": start + elapsed[present], "P": aggregate[present, None],
            "control_P_online": components[present], "control_P_revised": revised[present]}


def write_demo_npz(root: str | Path) -> dict[str, list[int]]:
    """Export only generated channels for an independent replay arithmetic oracle."""
    root = Path(root)
    for recording, blocks in BLOCKS.items():
        directory = root / recording / "verification"
        directory.mkdir(parents=True, exist_ok=True)
        for block in blocks:
            np.savez_compressed(directory / f"{block}.npz", **synthetic_arrays(recording, block))
    return {home: list(blocks) for home, blocks in BLOCKS.items()}
