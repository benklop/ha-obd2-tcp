"""ELM327 AT commands and OBD-II PID requests (mode 01 style)."""

from __future__ import annotations

import logging
import re
from typing import Final

from .elm_connection import ELMConnection, ELMConnectionError

_LOGGER = logging.getLogger(__name__)

_HEX: Final = re.compile(r"[0-9A-Fa-f]+")
_NO_DATA: Final = re.compile(r"NO\s*DATA", re.I)
_UNABLE: Final = re.compile(r"UNABLE|ERROR|BUS\s*INIT", re.I)


class OBDProtocol:
    def __init__(self, connection: ELMConnection) -> None:
        self._conn = connection
        self._initialized = False
        self._last_dtcs: list[str] = []

    @property
    def last_dtcs(self) -> list[str]:
        return list(self._last_dtcs)

    async def async_quick_probe(self) -> bool:
        """Lightweight check for config flow (ATE0 + ATI)."""
        try:
            raw = await self._conn.async_send_command("ATE0")
            if _UNABLE.search(raw):
                return False
            raw2 = await self._conn.async_send_command("ATI")
            return len(raw2.strip()) > 0 and not _UNABLE.search(raw2)
        except ELMConnectionError:
            return False

    async def async_init(self) -> None:
        """Standard ELM init for polling."""
        await self._conn.async_send_command("ATE0")
        await self._conn.async_send_command("ATL0")
        await self._conn.async_send_command("ATS0")
        await self._conn.async_send_command("ATH0")
        await self._conn.async_send_command("ATSP0")
        self._initialized = True

    async def async_read_battery_voltage(self) -> float | None:
        raw = await self._conn.async_send_command("AT RV")
        text = self._conn.strip_echo(raw, "AT RV")
        m = re.search(r"([\d.]+)\s*V?", text, re.I)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
        return None

    async def async_request_mode01(
        self, pid: int
    ) -> tuple[bool, str, list[int]]:
        """Request service 01 PID (decimal pid). Returns ok, payload_hex, data_bytes."""
        cmd = f"01 {pid:02X}"
        raw = await self._conn.async_send_command(cmd)
        text = self._conn.strip_echo(raw, cmd)
        if _NO_DATA.search(text) or _UNABLE.search(text):
            return False, "", []
        hex_compact = "".join(_HEX.findall(text)).upper()
        prefix = f"41{pid:02X}"
        idx = hex_compact.find(prefix)
        if idx < 0:
            return False, hex_compact, []
        data_hex = hex_compact[idx + len(prefix) :]
        if not data_hex:
            return False, data_hex, []
        try:
            data_bytes = [int(data_hex[i : i + 2], 16) for i in range(0, len(data_hex), 2)]
        except ValueError:
            return False, data_hex, []
        return True, data_hex, data_bytes

    async def async_read_monitor_status(self) -> tuple[bool, list[int]]:
        """PID 01 — MIL and DTC count (first 4 bytes A B C D)."""
        ok, _, data = await self.async_request_mode01(1)
        if not ok or len(data) < 4:
            return False, []
        return True, data

    def dtc_count_from_monitor(self, data: list[int]) -> int:
        """Number of confirmed emissions-related DTCs (nibble encoding of byte B)."""
        if len(data) < 2:
            return 0
        b = data[1]
        return (b >> 4) & 0x0F

    async def async_fetch_dtcs(self) -> list[str]:
        """Mode 03 — stored DTCs."""
        raw = await self._conn.async_send_command("03")
        text = self._conn.strip_echo(raw, "03")
        if _NO_DATA.search(text):
            self._last_dtcs = []
            return []
        hex_compact = "".join(_HEX.findall(text)).upper()
        if not hex_compact.startswith("43"):
            self._last_dtcs = []
            return []
        payload = hex_compact[2:]
        codes: list[str] = []
        for i in range(0, len(payload), 4):
            chunk = payload[i : i + 4]
            if len(chunk) < 4:
                break
            try:
                val = int(chunk, 16)
            except ValueError:
                continue
            if val == 0:
                continue
            b1, b2 = (val >> 8) & 0xFF, val & 0xFF
            codes.append(self._two_bytes_to_dtc(b1, b2))
        self._last_dtcs = codes
        return codes

    @staticmethod
    def _two_bytes_to_dtc(b1: int, b2: int) -> str:
        type_map = {0: "P", 1: "C", 2: "B", 3: "U"}
        kind = (b1 >> 6) & 0x03
        prefix = type_map.get(kind, "P")
        digit1 = (b1 >> 4) & 0x03
        digit2 = b1 & 0x0F
        return f"{prefix}{digit1:X}{digit2:X}{b2:02X}"
