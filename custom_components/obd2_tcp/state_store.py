"""Per-state values, timestamps, and raw payloads for READ/CALC (firmware TypedOBDState)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class StateEntry:
    name: str
    value: float | int | bool = 0
    old_value: float | int | bool = 0
    last_update: float = 0.0
    previous_update: float = 0.0
    payload: str | None = None


class StateStore:
    """Holds runtime state for profile entities."""

    def __init__(self) -> None:
        self._states: dict[str, StateEntry] = {}
        self._monotonic_origin = time.monotonic()

    def millis(self) -> float:
        """Milliseconds since store creation (firmware millis() analog)."""
        return (time.monotonic() - self._monotonic_origin) * 1000.0

    def ensure(self, name: str) -> StateEntry:
        if name not in self._states:
            self._states[name] = StateEntry(name=name)
        return self._states[name]

    def get_entry(self, name: str) -> StateEntry | None:
        return self._states.get(name)

    def get_numeric(self, name: str) -> float:
        ent = self._states.get(name)
        if ent is None:
            return 0.0
        v = ent.value
        if isinstance(v, bool):
            return 1.0 if v else 0.0
        return float(v)

    def set_value(
        self,
        name: str,
        value: float | int | bool,
        payload: str | None = None,
    ) -> None:
        ent = self.ensure(name)
        now = self.millis()
        ent.old_value = ent.value
        ent.previous_update = ent.last_update
        ent.value = value
        ent.last_update = now
        if payload is not None:
            ent.payload = payload

    def invalidate(self, name: str) -> None:
        """Mark a state as having no valid sample (e.g. OBD NO DATA when ignition/engine off)."""
        ent = self.ensure(name)
        ent.old_value = ent.value
        ent.previous_update = ent.last_update
        ent.value = 0
        ent.last_update = 0.0
        ent.payload = None

    def extract_payload_bytes(
        self, name: str, start_1based: int, end_1based_exclusive: int | None
    ) -> float:
        """Firmware OBDState: $var.b[i] or $var.b[i:j] (j is exclusive upper byte index)."""
        ent = self._states.get(name)
        if not ent or not ent.payload:
            return 0.0
        p = ent.payload.replace(" ", "").replace("\r", "").replace("\n", "")
        if end_1based_exclusive is None:
            end_1based_exclusive = start_1based + 1
        sidx = (start_1based - 1) * 2
        eidx = (end_1based_exclusive - 1) * 2
        if sidx < 0 or eidx > len(p) or sidx >= eidx:
            return 0.0
        try:
            return float(int(p[sidx:eidx], 16))
        except ValueError:
            return 0.0
