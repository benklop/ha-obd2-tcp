"""Load obd2-mqtt profile JSON into entity descriptors."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .const import STATE_TYPE_CALC, STATE_TYPE_READ
from .expressions import ExprParser, eval_scale_expression
from .fuel_type_labels import sae_fuel_type_label

_LOGGER = logging.getLogger(__name__)


@dataclass
class ProfileEntity:
    state_type: int
    value_type: str
    name: str
    description: str
    icon: str
    unit: str
    device_class: str
    measurement: bool
    diagnostic: bool
    enabled: bool
    visible: bool
    interval: int
    expr: str | None = None
    pid_service: int | None = None
    pid_number: int | None = None
    num_responses: int = 1
    num_expected_bytes: int = 1
    scale_factor: float = 1.0
    bias: float = 0.0
    response_format: int = 0
    read_func: str | None = None
    value_format: str | None = None
    value_func: str | None = None
    value_expr: str | None = None
    header: int = 0


def _read_profile_json(path: Path) -> list[dict[str, Any]]:
    """Read and parse profile JSON (sync helper; run in executor)."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_profile_from_path(path: Path) -> list[ProfileEntity]:
    data = _read_profile_json(path)
    return parse_profile_array(data)


async def async_load_profile_from_path(hass: Any, path: Path) -> list[ProfileEntity]:
    """Async-safe profile load (does file IO off the event loop)."""
    data = await hass.async_add_executor_job(_read_profile_json, path)
    return parse_profile_array(data)


def load_profile_from_package(profile_name: str, component_dir: Path) -> list[ProfileEntity]:
    prof = component_dir / "profiles" / f"{profile_name}.json"
    if not prof.is_file():
        raise FileNotFoundError(f"Profile not found: {prof}")
    return load_profile_from_path(prof)


async def async_load_profile_from_package(
    hass: Any, profile_name: str, component_dir: Path
) -> list[ProfileEntity]:
    prof = component_dir / "profiles" / f"{profile_name}.json"
    if not prof.is_file():
        raise FileNotFoundError(f"Profile not found: {prof}")
    return await async_load_profile_from_path(hass, prof)


def list_available_profiles(component_dir: Path) -> list[str]:
    """Return sorted profile names (stem of each ``profiles/*.json`` file)."""
    prof_dir = component_dir / "profiles"
    if not prof_dir.is_dir():
        return []
    return sorted(p.stem for p in prof_dir.glob("*.json") if p.is_file())


def parse_profile_array(data: list[dict[str, Any]]) -> list[ProfileEntity]:
    entities: list[ProfileEntity] = []
    for row in data:
        try:
            entities.append(_parse_row(row))
        except (KeyError, TypeError, ValueError) as err:
            _LOGGER.warning("Skip invalid profile row: %s (%s)", row.get("name"), err)
    return entities


def _parse_row(row: dict[str, Any]) -> ProfileEntity:
    stype = int(row["type"])
    vt = str(row["valueType"])
    pid_block = row.get("pid") or {}
    scale_expr = pid_block.get("scaleFactor")
    if isinstance(scale_expr, str) and scale_expr.strip():
        try:
            scale_val = eval_scale_expression(scale_expr)
        except Exception:  # noqa: BLE001
            scale_val = 1.0
    else:
        scale_val = float(pid_block.get("scaleFactor") or 1)

    expr = row.get("expr")
    if expr is not None and not isinstance(expr, str):
        expr = None

    value_block = row.get("value") or {}
    return ProfileEntity(
        state_type=stype,
        value_type=vt,
        name=str(row["name"]),
        description=str(row.get("description") or row["name"]),
        icon=str(row.get("icon") or ""),
        unit=str(row.get("unit") or ""),
        device_class=str(row.get("deviceClass") or ""),
        measurement=bool(row.get("measurement", True)),
        diagnostic=bool(row.get("diagnostic", False)),
        enabled=bool(row.get("enabled", True)),
        visible=bool(row.get("visible", True)),
        interval=int(row.get("interval") or 100),
        expr=expr,
        pid_service=int(pid_block["service"]) if pid_block.get("service") is not None else None,
        pid_number=int(pid_block["pid"]) if pid_block.get("pid") is not None else None,
        num_responses=int(pid_block.get("numResponses") or 1),
        num_expected_bytes=int(pid_block.get("numExpectedBytes") or 1),
        scale_factor=scale_val,
        bias=float(pid_block.get("bias") or 0),
        response_format=int(pid_block.get("responseFormat") or 0),
        read_func=row.get("readFunc"),
        value_format=value_block.get("format"),
        value_func=value_block.get("func"),
        value_expr=value_block.get("expr"),
        header=int(pid_block.get("header") or 0),
    )


def decode_pid_bytes(data: list[int], num_expected: int, scale: float, bias: float) -> float:
    """Big-endian combine first num_expected bytes, then scale and bias."""
    nb = min(num_expected, len(data))
    if nb == 0:
        return 0.0
    raw = 0
    for i in range(nb):
        raw = (raw << 8) | data[i]
    return raw * scale + bias


def cast_value(value: float, value_type: str) -> float | int | bool:
    if value_type == "int":
        return int(round(value))
    if value_type == "bool":
        return bool(int(value))
    return float(value)


def format_sensor_native(
    value: float | int | bool,
    value_type: str,
    fmt: str | None,
    func: str | None,
    expr: str | None,
    payload: str | None,
) -> float | int | str:
    """Apply value.format / value.func for HA state (simplified)."""
    if func == "toBitStr" and value_type == "int":
        return format(int(value), "b").zfill(32)
    if func == "saeFuelType" and value_type == "int":
        return sae_fuel_type_label(int(value))
    if func == "toMiles" and value_type == "int":
        return int(round(int(value) / 1.60934))
    if func == "toMiles" and value_type == "float":
        return round(float(value) / 1.60934, 2)
    if func == "toGallons" and value_type == "float":
        return round(float(value) / 3.7854, 2)
    if func == "toMPG" and value_type == "float":
        v = float(value)
        return round(0.0 if v == 0 else 235.214583333333 / v, 2)
    if func == "payload":
        return payload or ""
    if expr and fmt:
        p = ExprParser()

        def _vr(name: str) -> float:
            n = name.lstrip("$")
            if n == "value":
                if isinstance(value, bool):
                    return 1.0 if value else 0.0
                return float(value)
            return 0.0

        p.set_variable_resolve_function(_vr)
        ev = p.eval_exp(expr)
        if value_type == "int":
            return int(round(ev))
        if value_type == "float":
            return round(ev, 4)
    if fmt:
        if value_type == "int":
            return fmt % int(value)
        if value_type == "float":
            return fmt % float(value)
    if value_type == "int":
        return int(round(float(value)))
    if value_type == "bool":
        return bool(int(float(value)))
    return float(value)
