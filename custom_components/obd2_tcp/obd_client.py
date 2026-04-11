"""python-OBD wrapper for socket-based ELM327 access.

Home Assistant integrations must not block the event loop. This module provides
sync methods intended to be called via hass.async_add_executor_job(...).
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import Any

import obd
from obd import OBDCommand

_LOGGER = logging.getLogger(__name__)

_HEX = re.compile(r"[0-9A-Fa-f]+")
_NO_DATA = re.compile(r"NO\s*DATA", re.I)
_UNABLE = re.compile(r"UNABLE|ERROR|BUS\s*INIT", re.I)


class OBDClientError(Exception):
    """Wrapper error for connection/query failures."""


@dataclass(frozen=True)
class Mode01Result:
    ok: bool
    payload_hex: str
    data_bytes: list[int]


class PythonOBDClient:
    """Thin wrapper around python-OBD for TCP sockets."""

    def __init__(self, host: str, port: int, *, timeout: float = 8.0) -> None:
        self._host = host
        self._port = int(port)
        self._timeout = float(timeout)
        self._conn: obd.OBD | None = None
        self._cmd_cache: dict[int, OBDCommand] = {}

    @property
    def connected(self) -> bool:
        return bool(self._conn and self._conn.is_connected())

    @property
    def portstr(self) -> str:
        return f"socket://{self._host}:{self._port}"

    def connect(self) -> None:
        """Connect (or reconnect) to the adapter."""
        self.close()
        try:
            # Notes:
            # - python-OBD uses pyserial.serial_for_url(), which supports socket://
            # - fast=False avoids python-OBD "repeat last cmd with CR" behavior,
            #   which can be problematic with some TCP bridges.
            self._conn = obd.OBD(
                self.portstr,
                fast=False,
                timeout=self._timeout,
                check_voltage=False,
            )
        except Exception as err:  # noqa: BLE001
            self._conn = None
            raise OBDClientError(f"OBD connect failed: {err}") from err

        if not self._conn or self._conn.status() == obd.OBDStatus.NOT_CONNECTED:
            self._conn = None
            raise OBDClientError("OBD connect failed: NOT_CONNECTED")

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
        self._conn = None

    def ensure_connected(self) -> None:
        if not self._conn:
            self.connect()
            return
        if self._conn.status() == obd.OBDStatus.NOT_CONNECTED:
            self.connect()

    def quick_probe(self) -> bool:
        """Best-effort probe used by config flow."""
        try:
            self.connect()
            return self._conn is not None and self._conn.status() != obd.OBDStatus.NOT_CONNECTED
        except OBDClientError:
            return False
        finally:
            self.close()

    def read_adapter_voltage(self) -> float | None:
        """Adapter voltage via AT RV (python-OBD: ELM_VOLTAGE)."""
        self.ensure_connected()
        assert self._conn is not None

        try:
            r = self._conn.query(obd.commands.ELM_VOLTAGE, force=True)
        except Exception as err:  # noqa: BLE001
            raise OBDClientError(f"ELM_VOLTAGE failed: {err}") from err

        if r is None or r.is_null() or r.value is None:
            return None

        try:
            # Pint quantity -> magnitude (volts)
            return float(getattr(r.value, "magnitude", r.value))
        except (TypeError, ValueError):
            return None

    def fetch_dtcs(self) -> list[str]:
        """Mode 03 DTCs via python-OBD GET_DTC."""
        self.ensure_connected()
        assert self._conn is not None

        try:
            r = self._conn.query(obd.commands.GET_DTC, force=True)
        except Exception as err:  # noqa: BLE001
            raise OBDClientError(f"GET_DTC failed: {err}") from err

        if r is None or r.is_null() or r.value is None:
            return []

        codes: list[str] = []
        # python-OBD returns list like: [(code, desc), ...]
        for item in r.value:
            try:
                code = item[0]
            except Exception:  # noqa: BLE001
                continue
            if isinstance(code, str) and code:
                codes.append(code)
        return codes

    def request_mode01(self, pid: int) -> Mode01Result:
        """Request service 01 PID (decimal pid). Returns payload_hex and data_bytes.

        We keep compatibility with existing profile scaling by extracting bytes from the
        raw adapter output (response.messages[*].raw()) and then applying the same
        '41 <pid> <data...>' prefix search as the legacy implementation.
        """
        self.ensure_connected()
        assert self._conn is not None

        pid_int = int(pid)
        cmd = self._cmd_cache.get(pid_int)
        if cmd is None:
            cmd_bytes = f"01{pid_int:02X}".encode("ascii")

            def _identity_decoder(messages: list[Any]) -> list[Any]:
                return messages

            cmd = OBDCommand(
                name=f"MODE01_{pid_int:02X}",
                desc=f"Mode 01 PID {pid_int:02X}",
                command=cmd_bytes,
                _bytes=0,
                decoder=_identity_decoder,
                fast=False,
            )
            self._cmd_cache[pid_int] = cmd

        try:
            r = self._conn.query(cmd, force=True)
        except Exception as err:  # noqa: BLE001
            raise OBDClientError(f"Mode01 {pid_int:02X} failed: {err}") from err

        if r is None or not r.messages:
            return Mode01Result(False, "", [])

        raw_text = "\n".join(
            m.raw().replace(" ", "") for m in r.messages if hasattr(m, "raw")
        )
        if _NO_DATA.search(raw_text) or _UNABLE.search(raw_text):
            return Mode01Result(False, "", [])

        hex_compact = "".join(_HEX.findall(raw_text)).upper()
        prefix = f"41{pid_int:02X}"
        idx = hex_compact.find(prefix)
        if idx < 0:
            return Mode01Result(False, hex_compact, [])

        data_hex = hex_compact[idx + len(prefix) :]
        if not data_hex:
            return Mode01Result(False, data_hex, [])

        try:
            data_bytes = [int(data_hex[i : i + 2], 16) for i in range(0, len(data_hex), 2)]
        except ValueError:
            return Mode01Result(False, data_hex, [])

        return Mode01Result(True, data_hex, data_bytes)

