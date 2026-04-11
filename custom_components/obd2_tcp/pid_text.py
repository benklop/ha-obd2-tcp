"""Human-readable text for common OBD-II mode 01 PIDs — SAE J1979 / ISO 15031-5."""

from __future__ import annotations

# Home Assistant sensor state is capped; keep summaries within a safe length.
_MAX_STATE_LEN = 248

# PID 0x03 — one status byte per fuel system (bank), first byte = system 1, second = system 2.
_FUEL_SYS_BYTE: dict[int, str] = {
    0: "Not available",
    1: "Open loop, warming up",
    2: "Closed loop, oxygen sensor feedback",
    4: "Open loop, driving conditions",
    8: "Open loop, system fault",
    16: "Closed loop, oxygen sensor fault",
}


def format_fuel_system_status_u16(raw: int) -> str:
    """Decode PID 0x03 two-byte value as big-endian bank1, bank2."""
    raw = int(raw) & 0xFFFF
    b1 = (raw >> 8) & 0xFF
    b2 = raw & 0xFF
    return _truncate(
        f"System 1: {_fuel_sys_byte_label(b1)}; System 2: {_fuel_sys_byte_label(b2)}"
    )


def _fuel_sys_byte_label(code: int) -> str:
    if code in _FUEL_SYS_BYTE:
        return _FUEL_SYS_BYTE[code]
    # Some ECUs may report undocumented combinations.
    return f"Unknown 0x{code:02X}"


_SPARK_CONTINUOUS = (
    "Catalyst",
    "Heated catalyst",
    "Evaporative system",
    "Secondary air",
    "A/C refrigerant",
    "Oxygen sensor",
    "Oxygen sensor heater",
    "EGR / VVT",
)

_DIESEL_CONTINUOUS = (
    "NMHC catalyst",
    "NOx / SCR",
    "Reserved",
    "Boost pressure",
    "Reserved",
    "Exhaust gas sensor",
    "Particulate filter",
    "EGR / VVT",
)


def format_monitor_status_u32(raw: int) -> str:
    """Decode PID 0x01 four-byte monitor status (big-endian A B C D)."""
    raw = int(raw) & 0xFFFFFFFF
    a = (raw >> 24) & 0xFF
    b = (raw >> 16) & 0xFF
    c = (raw >> 8) & 0xFF
    d = raw & 0xFF

    mil_on = bool(a & 0x80)
    dtc_count = a & 0x7F
    compression = bool(b & 0x08)

    parts: list[str] = [
        f"{'Check Engine on' if mil_on else 'Check Engine off'}, {dtc_count} stored codes",
        "Diesel" if compression else "Gasoline",
    ]

    # Byte B: continuous test availability (B2–B0) and incomplete (B6–B4).
    trip: list[str] = []
    if b & 0x01:
        trip.append("Misfire " + ("incomplete" if b & 0x10 else "complete"))
    if b & 0x02:
        trip.append("Fuel system " + ("incomplete" if b & 0x20 else "complete"))
    if b & 0x04:
        trip.append("Components " + ("incomplete" if b & 0x40 else "complete"))
    if trip:
        parts.append("This trip: " + ", ".join(trip))

    names = _DIESEL_CONTINUOUS if compression else _SPARK_CONTINUOUS
    not_done: list[str] = []
    for i in range(8):
        if c & (1 << i) and d & (1 << i):
            label = names[i]
            if not label.startswith("Reserved"):
                not_done.append(label)

    if not_done:
        parts.append("Not complete this cycle: " + ", ".join(not_done))
    else:
        parts.append("Continuous monitors OK")

    return _truncate("; ".join(parts))


def _truncate(s: str) -> str:
    if len(s) <= _MAX_STATE_LEN:
        return s
    return s[: _MAX_STATE_LEN - 3] + "..."
