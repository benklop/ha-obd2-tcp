"""python-OBD wrapper for socket-based ELM327 access.

Home Assistant integrations must not block the event loop. This module provides
sync methods intended to be called via hass.async_add_executor_job(...).
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
import time
from typing import Any

import serial
import pint as _pint_obd_compat

# python-OBD defines ``percent``, ``%``, and ``ppm`` in UnitsAndScaling.py even though
# current Pint defaults already include them, which logs pint.util redefinition warnings
# in Home Assistant. Silence that only while constructing python-OBD's registry.
_orig_pint_unit_registry = _pint_obd_compat.UnitRegistry


def _pint_unit_registry_for_obd_import(*args: Any, **kwargs: Any) -> Any:
    merged = dict(kwargs)
    merged["on_redefinition"] = "ignore"
    try:
        return _orig_pint_unit_registry(*args, **merged)
    except TypeError:
        return _orig_pint_unit_registry(*args, **kwargs)


_pint_obd_compat.UnitRegistry = _pint_unit_registry_for_obd_import  # type: ignore[method-assign]
try:
    import obd
    from obd import OBDCommand
finally:
    _pint_obd_compat.UnitRegistry = _orig_pint_unit_registry  # type: ignore[method-assign]

from .const import (
    DEFAULT_ADAPTER_AT_RV_VOLTAGE_OFFSET_V,
    DEFAULT_ELM_PP0E_HEX,
    ELM_READ_CHUNK,
)

_LOGGER = logging.getLogger(__name__)

_HEX = re.compile(r"[0-9A-Fa-f]+")
_NO_DATA = re.compile(r"NO\s*DATA", re.I)
_UNABLE = re.compile(r"UNABLE|ERROR|BUS\s*INIT", re.I)
_IGN_BAD = re.compile(r"\?|UNABLE|ERROR|NO\s*DATA", re.I)
_IGN_HIGH = re.compile(r"\bHIGH\b|\bON\b", re.I)
_IGN_LOW = re.compile(r"\bLOW\b|\bOFF\b", re.I)

# Short pause before retrying AT IGN preflight (cheap; pick up ignition quickly).
_IGNITION_BACKOFF_S = 2.0


class OBDClientError(Exception):
    """Wrapper error for connection/query failures."""


class OBDClientBackoffError(OBDClientError):
    """Raised when skipping a connect attempt due to backoff."""


class OBDClientIgnitionOff(OBDClientError):
    """IgnMon / AT IGN indicates ignition off (or ignition backoff active)."""


@dataclass(frozen=True)
class Mode01Result:
    ok: bool
    payload_hex: str
    data_bytes: list[int]


class PythonOBDClient:
    """Thin wrapper around python-OBD for TCP sockets."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        timeout: float = 8.0,
        disable_elm_low_power: bool = False,
        elm_pp0e_hex: str = DEFAULT_ELM_PP0E_HEX,
        adapter_rv_offset_v: float = DEFAULT_ADAPTER_AT_RV_VOLTAGE_OFFSET_V,
        use_ign_gate: bool = False,
        ign_active_high: bool = True,
    ) -> None:
        self._host = host
        self._port = int(port)
        self._timeout = float(timeout)
        self._disable_elm_low_power = bool(disable_elm_low_power)
        self._elm_pp0e_hex = elm_pp0e_hex.strip().upper()
        self._adapter_rv_offset_v = float(adapter_rv_offset_v)
        self._use_ign_gate = bool(use_ign_gate)
        self._ign_active_high = bool(ign_active_high)
        self._conn: obd.OBD | None = None
        self._cmd_cache: dict[int, OBDCommand] = {}
        self._elm_low_power_pp_applied: bool = False
        self._connect_failures: int = 0
        self._connect_backoff_until: float = 0.0
        self._ignition_backoff_until: float = 0.0

    @property
    def connected(self) -> bool:
        return bool(self._conn and self._conn.is_connected())

    @property
    def portstr(self) -> str:
        return f"socket://{self._host}:{self._port}"

    def connect(
        self,
        *,
        apply_elm_low_power_pp: bool = True,
        skip_ign_preflight: bool = False,
    ) -> None:
        """Connect (or reconnect) to the adapter."""
        self.close()
        if self._use_ign_gate and not skip_ign_preflight:
            allowed = self._preflight_ign_mon()
            if allowed is False:
                self._note_ignition_off()
                raise OBDClientIgnitionOff(
                    "IgnMon indicates ignition off (AT IGN); skipping OBD connect"
                )
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
            self._note_connect_failure()
            raise OBDClientError(f"OBD connect failed: {err}") from err

        if not self._conn or self._conn.status() == obd.OBDStatus.NOT_CONNECTED:
            self._conn = None
            self._note_connect_failure()
            raise OBDClientError("OBD connect failed: NOT_CONNECTED")

        self._connect_failures = 0
        self._connect_backoff_until = 0.0
        self._ignition_backoff_until = 0.0
        if apply_elm_low_power_pp:
            self._maybe_apply_elm_disable_low_power()

    def _note_ignition_off(self) -> None:
        self._ignition_backoff_until = time.monotonic() + _IGNITION_BACKOFF_S

    def _note_connect_failure(self) -> None:
        self._connect_failures += 1
        delay_s = min(300.0, max(5.0, 2.0 ** min(self._connect_failures, 8)))
        self._connect_backoff_until = time.monotonic() + delay_s

    def _serial_read_until_prompt(self, ser: Any, *, deadline_s: float) -> bytes:
        buf = b""
        deadline = time.monotonic() + deadline_s
        while time.monotonic() < deadline:
            chunk = ser.read(ELM_READ_CHUNK)
            if chunk:
                buf += chunk
            if b">" in buf:
                return buf
        raise TimeoutError("timeout waiting for ELM prompt")

    def _serial_send_until_prompt(
        self, ser: Any, cmd: bytes, *, deadline_s: float
    ) -> bytes:
        try:
            ser.reset_input_buffer()
        except Exception:  # noqa: BLE001
            pass
        ser.write(cmd)
        return self._serial_read_until_prompt(ser, deadline_s=deadline_s)

    def _classify_ign_text(self, text: str) -> bool | None:
        """Return True if IgnMon appears HIGH, False if LOW, None if inconclusive."""
        if _IGN_BAD.search(text):
            return None
        lines = [
            ln.strip()
            for ln in text.replace("\r", "\n").split("\n")
            if ln.strip() and not ln.strip().startswith(">")
        ]
        high = low = False
        for ln in lines:
            u = ln.upper()
            if u in ("1", "ON", "HIGH"):
                high = True
            elif u in ("0", "OFF", "LOW"):
                low = True
            else:
                if _IGN_HIGH.search(u):
                    high = True
                if _IGN_LOW.search(u):
                    low = True
        if high and low:
            return None
        if high:
            return True
        if low:
            return False
        return None

    def _ignition_allows_obd(self, pin_high: bool | None) -> bool | None:
        if pin_high is None:
            return None
        if self._ign_active_high:
            return pin_high
        return not pin_high

    def _preflight_ign_mon(self) -> bool | None:
        """Run AT IGN on a short-lived serial session. True=proceed, False=skip, None=fail-open."""
        ser: Any = None
        try:
            tmo = min(3.0, max(1.0, self._timeout))
            ser = serial.serial_for_url(
                self.portstr,
                timeout=tmo,
                write_timeout=tmo,
            )
            dl = max(8.0, self._timeout)
            buf = self._serial_read_until_prompt(ser, deadline_s=dl)
            self._serial_send_until_prompt(ser, b"AT E0\r", deadline_s=dl)
            self._serial_send_until_prompt(ser, b"AT L0\r", deadline_s=dl)
            ign_buf = self._serial_send_until_prompt(ser, b"AT IGN\r", deadline_s=dl)
            text = ign_buf.decode("ascii", errors="replace")
            if ">" in text:
                text = text[: text.rindex(">")]
            pin_high = self._classify_ign_text(text)
            allowed = self._ignition_allows_obd(pin_high)
            if allowed is None:
                _LOGGER.debug("AT IGN inconclusive; raw response %r", text.strip())
            return allowed
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("AT IGN preflight failed: %s", err)
            return None
        finally:
            if ser is not None:
                try:
                    ser.close()
                except Exception:  # noqa: BLE001
                    pass

    def _maybe_apply_elm_disable_low_power(self) -> None:
        """Set ELM327 PP0E to disable low-power (e.g. VGate iCar Wi‑Fi staying up)."""
        if (
            not self._disable_elm_low_power
            or self._elm_low_power_pp_applied
            or self._conn is None
        ):
            return

        iface = getattr(self._conn, "interface", None)
        if iface is None or not hasattr(iface, "send_and_parse"):
            _LOGGER.warning("ELM low-power disable skipped: no ELM327 interface")
            return

        if len(self._elm_pp0e_hex) != 2 or not _HEX.fullmatch(self._elm_pp0e_hex):
            _LOGGER.warning(
                "ELM low-power disable skipped: invalid PP0E hex %r (need two hex digits)",
                self._elm_pp0e_hex,
            )
            return

        _LOGGER.warning(
            "Writing ELM327 PP0E (low-power off) — only verified on VGate iCar; "
            "other adapters may use different registers and be damaged"
        )
        try:
            sv_cmd = f"ATPP0ESV{self._elm_pp0e_hex}".encode("ascii")
            iface.send_and_parse(sv_cmd)
            iface.send_and_parse(b"ATPP0EON")
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("ELM PP0E low-power disable failed: %s", err)
            return

        self._elm_low_power_pp_applied = True
        _LOGGER.info(
            "ELM PP0E updated for low-power off (SV%s, ON). "
            "Power-cycle the adapter once if Wi‑Fi still sleeps; clones may ignore PP commands.",
            self._elm_pp0e_hex,
        )

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
        self._conn = None

    def ensure_connected(self) -> None:
        if time.monotonic() < self._ignition_backoff_until:
            raise OBDClientIgnitionOff("Connect attempt skipped (ignition backoff)")
        if time.monotonic() < self._connect_backoff_until:
            raise OBDClientBackoffError("Connect attempt skipped (backoff)")
        if not self._conn:
            self.connect(apply_elm_low_power_pp=True)
            return
        if self._conn.status() == obd.OBDStatus.NOT_CONNECTED:
            self.connect(apply_elm_low_power_pp=True)

    def quick_probe(self) -> bool:
        """Best-effort probe used by config flow."""
        try:
            self.connect(apply_elm_low_power_pp=False, skip_ign_preflight=True)
            return self._conn is not None and self._conn.status() != obd.OBDStatus.NOT_CONNECTED
        except OBDClientError:
            return False
        finally:
            self.close()

    def read_adapter_voltage(self) -> float | None:
        """Adapter-reported vehicle voltage via AT RV (python-OBD: ELM_VOLTAGE).

        Adds ``adapter_rv_offset_v`` (from integration options) to approximate true battery
        voltage when the dongle senses pin 16 through a protection diode.
        """
        self.ensure_connected()
        assert self._conn is not None

        try:
            r = self._conn.query(obd.commands.ELM_VOLTAGE, force=True)
        except Exception as err:  # noqa: BLE001
            raise OBDClientError(f"ELM_VOLTAGE failed: {err}") from err

        if r is None or r.is_null() or r.value is None:
            return None

        try:
            # Pint quantity -> magnitude (volts), then correct typical adapter diode drop.
            raw = float(getattr(r.value, "magnitude", r.value))
            return raw + self._adapter_rv_offset_v
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
