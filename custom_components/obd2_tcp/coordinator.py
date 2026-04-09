"""DataUpdateCoordinator: TCP ELM polling, READ/CALC scheduling, expression evaluation."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import timedelta
from typing import Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    AF_RATIO_DIESEL,
    AF_RATIO_ETHANOL,
    AF_RATIO_GAS,
    AF_RATIO_GASOLINE,
    AF_RATIO_METHANOL,
    AF_RATIO_PROPANE,
    DENSITY_DIESEL,
    DENSITY_ETHANOL,
    DENSITY_GAS,
    DENSITY_GASOLINE,
    DENSITY_METHANOL,
    DENSITY_PROPANE,
    FUEL_TYPE_CNG,
    FUEL_TYPE_DIESEL,
    FUEL_TYPE_ELECTRIC,
    FUEL_TYPE_ETHANOL,
    FUEL_TYPE_LPG,
    FUEL_TYPE_METHANOL,
    FUEL_TYPE_PROPANE,
    STATE_TYPE_CALC,
    STATE_TYPE_READ,
)
from .elm_connection import ELMConnection, ELMConnectionError
from .expressions import ExprParser
from .profile import (
    ProfileEntity,
    cast_value,
    decode_pid_bytes,
    format_sensor_native,
)
from .protocol import OBDProtocol
from .state_store import StateStore

_LOGGER = logging.getLogger(__name__)

_NUMDTC_RE = re.compile(r"numDTCs\s*\(\s*([^)]+)\s*\)", re.I)


class OBD2TCPCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass,
        config_entry,
        *,
        host: str,
        port: int,
        scan_interval: int,
        profile_entities: list[ProfileEntity],
        fuel_type: int,
    ) -> None:
        self.config_entry = config_entry
        self.host = host
        self.port = port
        self._profile_entities = [e for e in profile_entities if e.enabled and e.visible]
        self._fuel_type = fuel_type
        self._conn = ELMConnection(host, port)
        self._protocol = OBDProtocol(self._conn)
        self._store = StateStore()
        self._lock = asyncio.Lock()
        super().__init__(
            hass,
            _LOGGER,
            name=f"OBD2 {host}",
            update_interval=timedelta(seconds=scan_interval),
        )

    @property
    def entities(self) -> list[ProfileEntity]:
        return self._profile_entities

    def _af_ratio(self, fuel: float) -> float:
        k = int(fuel)
        if k == FUEL_TYPE_METHANOL:
            return AF_RATIO_METHANOL
        if k == FUEL_TYPE_ETHANOL:
            return AF_RATIO_ETHANOL
        if k == FUEL_TYPE_DIESEL:
            return AF_RATIO_DIESEL
        if k in (FUEL_TYPE_LPG, FUEL_TYPE_CNG):
            return AF_RATIO_GAS
        if k == FUEL_TYPE_PROPANE:
            return AF_RATIO_PROPANE
        if k == FUEL_TYPE_ELECTRIC:
            return 0.0
        return AF_RATIO_GASOLINE

    def _density(self, fuel: float) -> float:
        k = int(fuel)
        if k == FUEL_TYPE_METHANOL:
            return DENSITY_METHANOL
        if k == FUEL_TYPE_ETHANOL:
            return DENSITY_ETHANOL
        if k == FUEL_TYPE_DIESEL:
            return DENSITY_DIESEL
        if k in (FUEL_TYPE_LPG, FUEL_TYPE_CNG):
            return DENSITY_GAS
        if k == FUEL_TYPE_PROPANE:
            return DENSITY_PROPANE
        if k == FUEL_TYPE_ELECTRIC:
            return 0.0
        return DENSITY_GASOLINE

    def _sync_resolve_var(self, raw: str) -> float:
        name = raw.lstrip("$")
        if name == "millis":
            return self._store.millis()

        if "." in name:
            base, op = name.split(".", 1)
            ent = self._store.get_entry(base)
            if ent is None:
                return 0.0
            if op == "pu":
                return ent.previous_update
            if op == "lu":
                return ent.last_update
            if op == "ov":
                v = ent.old_value
                if isinstance(v, bool):
                    return 1.0 if v else 0.0
                return float(v)
            if op.startswith("b") and len(op) > 1:
                rest = op[1:]
                if ":" in rest:
                    a, b = rest.split(":", 1)
                    try:
                        i = int(a)
                        j = int(b)
                    except ValueError:
                        return 0.0
                    return self._store.extract_payload_bytes(base, i, j)
                try:
                    i = int(rest)
                except ValueError:
                    return 0.0
                return self._store.extract_payload_bytes(base, i, None)

        if name == "fuelType":
            if self._store.get_entry("fuelType") is not None:
                return self._store.get_numeric("fuelType")
            return float(self._fuel_type)

        return self._store.get_numeric(name)

    async def _expand_numdtcs(self, expr: str) -> str:
        out = expr

        while True:
            m = _NUMDTC_RE.search(out)
            if not m:
                break
            inner = m.group(1).strip()
            p = ExprParser()
            p.set_variable_resolve_function(self._sync_resolve_var)
            p.add_custom_function("afRatio", self._af_ratio)
            p.add_custom_function("density", self._density)
            trig = int(p.eval_exp(inner))
            if trig <= 0:
                repl = "0"
            else:
                async with self._lock:
                    await self._protocol.async_fetch_dtcs()
                repl = str(len(self._protocol.last_dtcs))
            out = out[: m.start()] + repl + out[m.end() :]
        return out

    def _eval_sync_expr(self, expr: str) -> float:
        p = ExprParser()
        p.set_variable_resolve_function(self._sync_resolve_var)
        p.add_custom_function("afRatio", self._af_ratio)
        p.add_custom_function("density", self._density)

        def _num_stub(_: float) -> float:
            return 0.0

        p.add_custom_function("numDTCs", _num_stub)
        return p.eval_exp(expr)

    async def _eval_calc(self, expr: str) -> float:
        expanded = await self._expand_numdtcs(expr)
        return self._eval_sync_expr(expanded)

    def _is_due(self, ent: ProfileEntity, now_ms: float) -> bool:
        st = self._store.get_entry(ent.name)
        if ent.interval < 0:
            return st is None or st.last_update == 0
        if st is None or st.last_update == 0:
            return True
        return st.last_update + ent.interval <= now_ms

    async def _async_update_data(self) -> dict[str, Any]:
        now_ms = self._store.millis()
        data: dict[str, Any] = {}

        try:
            async with self._lock:
                for ent in self._profile_entities:
                    self._store.ensure(ent.name)

                if not self._conn.connected:
                    await self._conn.async_connect()
                    await self._protocol.async_init()

                read_list = [
                    e
                    for e in self._profile_entities
                    if e.state_type == STATE_TYPE_READ and self._is_due(e, now_ms)
                ]
                read_list.sort(key=lambda x: x.name)

                for ent in read_list:
                    await self._update_read(ent)

                calc_list = [
                    e
                    for e in self._profile_entities
                    if e.state_type == STATE_TYPE_CALC and e.expr and self._is_due(e, now_ms)
                ]

                for ent in calc_list:
                    val = await self._eval_calc(ent.expr)
                    typed = cast_value(val, ent.value_type)
                    self._store.set_value(ent.name, typed, None)

                for ent in self._profile_entities:
                    st = self._store.get_entry(ent.name)
                    if st is None or st.last_update == 0:
                        data[ent.name] = None
                        continue
                    payload = st.payload if ent.state_type == STATE_TYPE_READ else None
                    native = format_sensor_native(
                        st.value,
                        ent.value_type,
                        ent.value_format,
                        ent.value_func,
                        ent.value_expr,
                        payload,
                    )
                    data[ent.name] = native

        except (ELMConnectionError, TimeoutError, OSError) as err:
            await self._conn.async_disconnect()
            raise UpdateFailed(f"OBD2 connection error: {err}") from err

        return data

    async def async_shutdown(self) -> None:
        await self._conn.async_disconnect()

    async def _update_read(self, ent: ProfileEntity) -> None:
        if ent.read_func == "batteryVoltage":
            v = await self._protocol.async_read_battery_voltage()
            if v is None:
                self._store.set_value(ent.name, 0.0, "")
            else:
                self._store.set_value(ent.name, float(v), f"{v}")
            return

        if ent.pid_service != 1 or ent.pid_number is None:
            _LOGGER.debug("Unsupported READ %s (service %s)", ent.name, ent.pid_service)
            return

        ok, payload_hex, data = await self._protocol.async_request_mode01(ent.pid_number)
        if not ok or not data:
            self._store.set_value(ent.name, 0.0, payload_hex)
            return

        raw_val = decode_pid_bytes(
            data,
            ent.num_expected_bytes,
            ent.scale_factor,
            ent.bias,
        )
        typed = cast_value(raw_val, ent.value_type)
        self._store.set_value(ent.name, typed, payload_hex)
