"""SAE J1979 / ISO 15031-5 PID 0x51 fuel type codes — human-readable labels."""

from __future__ import annotations

from typing import Final

# ISO 15031-5 / SAE J1979-DA fuel type enumeration (single data byte).
SAE_FUEL_TYPE_NAMES: Final[dict[int, str]] = {
    0: "Not available",
    1: "Gasoline",
    2: "Methanol",
    3: "Ethanol",
    4: "Diesel",
    5: "LPG",
    6: "CNG",
    7: "Propane",
    8: "Electric",
    9: "Bi-fuel running gasoline",
    10: "Bi-fuel running methanol",
    11: "Bi-fuel running ethanol",
    12: "Bi-fuel running LPG",
    13: "Bi-fuel running CNG",
    14: "Bi-fuel running propane",
    15: "Bi-fuel running electricity",
    16: "Bi-fuel electric motor and combustion",
    17: "Hybrid gasoline",
    18: "Hybrid ethanol",
    19: "Hybrid diesel",
    20: "Hybrid electric",
    21: "Hybrid running electric and combustion",
    22: "Hybrid regenerative",
    23: "Bi-fuel running diesel",
}


def sae_fuel_type_label(code: int) -> str:
    """Return a display string for a PID 0x51 fuel type byte."""
    c = int(code) & 0xFF
    return SAE_FUEL_TYPE_NAMES.get(c, f"Unknown ({c})")


def fuel_type_config_select_options() -> list[dict[str, str]]:
    """Options for the config flow SelectSelector (value = decimal string, label = name)."""
    return [
        {"value": str(k), "label": v}
        for k, v in sorted(SAE_FUEL_TYPE_NAMES.items(), key=lambda kv: kv[0])
    ]
