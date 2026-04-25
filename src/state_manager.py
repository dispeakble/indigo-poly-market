from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class PositionSnapshot(BaseModel):
    market_slug: str
    outcome: str
    size_usdc: float = Field(ge=0)
    avg_entry_price: float = Field(ge=0, le=1)
    current_price: float = Field(ge=0, le=1)
    unrealized_pnl: float = 0.0


class RuntimeState(BaseModel):
    last_poll_ts: float | None = None
    copied_wallets: list[str] = Field(default_factory=list)
    source_positions: dict[str, dict[str, float]] = Field(default_factory=dict)
    # key: f"{market_slug}:{outcome}"
    copied_positions: dict[str, PositionSnapshot] = Field(default_factory=dict)


class StateManager:
    def __init__(self, state_path: str | Path = "state.json") -> None:
        self.state_path = Path(state_path)
        self._lock = threading.RLock()
        self._state = self._load()

    def _load(self) -> RuntimeState:
        if not self.state_path.exists():
            return RuntimeState()
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        return RuntimeState(**data)

    def _flush(self) -> None:
        payload = self._state.model_dump()
        self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def save(self) -> None:
        with self._lock:
            self._flush()

    def get_state(self) -> RuntimeState:
        with self._lock:
            return RuntimeState(**self._state.model_dump())

    def update(self, **kwargs: Any) -> RuntimeState:
        with self._lock:
            current = self._state.model_dump()
            current.update(kwargs)
            self._state = RuntimeState(**current)
            self._flush()
            return RuntimeState(**self._state.model_dump())

    def upsert_position(self, key: str, position: PositionSnapshot) -> None:
        with self._lock:
            self._state.copied_positions[key] = position
            self._flush()

    def remove_position(self, key: str) -> None:
        with self._lock:
            self._state.copied_positions.pop(key, None)
            self._flush()

    def set_source_positions(self, positions: dict[str, dict[str, float]]) -> None:
        with self._lock:
            self._state.source_positions = positions
            self._flush()
