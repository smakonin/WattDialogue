# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stephen Makonin
"""Read server-only configuration without evaluating shell expressions."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {"OPENAI_API_KEY", "OPENAI_API_KEY_BACKUP", "WATTDIALOGUE_MODEL",
           "WATTDIALOGUE_LIVE_CALL_LIMIT"}


def env_values(path: Path) -> dict[str, str]:
    values = {key: os.environ.get(key, "") for key in ALLOWED}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.removeprefix("export ").split("=", 1)
            if key.strip() in ALLOWED:
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                if value:
                    values[key.strip()] = value
    return values


@dataclass(repr=False)
class Settings:
    primary_key: str = field(default="", repr=False)
    backup_key: str = field(default="", repr=False)
    model: str = "gpt-5.4-mini"
    live_call_limit: int = 8
    env_file: Path = field(default_factory=lambda: ROOT / ".env.local")

    def __repr__(self) -> str:
        return f"Settings(model={self.model!r}, keys_configured={bool(self.primary_key or self.backup_key)})"

    @classmethod
    def load(cls, env_file: Path | str | None = None) -> "Settings":
        path = Path(env_file) if env_file else ROOT / ".env.local"
        values = env_values(path)
        try:
            limit = int(values.get("WATTDIALOGUE_LIVE_CALL_LIMIT", "") or 8)
        except ValueError as exc:
            raise ValueError("The live call limit must be an integer.") from exc
        if not 1 <= limit <= 1000:
            raise ValueError("The live call limit must be between 1 and 1000.")
        return cls(values.get("OPENAI_API_KEY", ""), values.get("OPENAI_API_KEY_BACKUP", ""),
                   values.get("WATTDIALOGUE_MODEL", "") or "gpt-5.4-mini", limit, path)

    def public_status(self) -> dict:
        return {"api_available": bool(self.primary_key or self.backup_key),
                "backup_available": bool(self.backup_key), "model": self.model,
                "live_call_limit": self.live_call_limit}
