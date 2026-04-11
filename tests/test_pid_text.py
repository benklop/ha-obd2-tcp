"""Tests for OBD PID human-readable formatters."""

from custom_components.obd2_tcp.pid_text import (
    format_fuel_system_status_u16,
    format_monitor_status_u32,
)


def test_fuel_system_closed_loop_and_na() -> None:
    # Bank1=2 closed loop, bank2=0 N/A
    raw = (2 << 8) | 0
    s = format_fuel_system_status_u16(raw)
    assert "Closed loop, oxygen sensor feedback" in s
    assert "Not available" in s


def test_monitor_mil_off_gasoline() -> None:
    a, b, c, d = 0x00, 0x07, 0x04, 0x04
    # Evaporative available (C2) and incomplete (D2)
    raw = (a << 24) | (b << 16) | (c << 8) | d
    s = format_monitor_status_u32(raw)
    assert "Check Engine off" in s
    assert "0 stored codes" in s
    assert "Gasoline" in s
    assert "Evaporative system" in s
    assert "Not complete this cycle" in s


def test_monitor_mil_on_counts_dtc() -> None:
    a = 0x80 | 3 # MIL + 3 codes
    raw = (a << 24) | (0x07 << 16) | (0 << 8) | 0
    s = format_monitor_status_u32(raw)
    assert "Check Engine on" in s
    assert "3 stored codes" in s
