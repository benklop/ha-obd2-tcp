"""DataUpdateCoordinator: TCP ELM polling, READ/CALC scheduling, expression evaluation."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import timedelta
from typing import Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ADAPTER_VOLTAGE_OFFSET,
    CONF_DISABLE_ELM_LOW_POWER,
    CONF_IGN_ACTIVE_HIGH,
    CONF_USE_IGN_GATE,
    DEFAULT_IGN_ACTIVE_HIGH,
    DEFAULT_USE_IGN_GATE,
    AF_RATIO_DIESEL,
    AF_RATIO_ETHANOL,
    AF_RATIO_GAS,
    AF_RATIO_GASOLINE,
    AF_RATIO_METHANOL,
    AF_RATIO_PROPANE,
    DEFAULT_ADAPTER_AT_RV_VOLTAGE_OFFSET_V,
    CONF_UNIT_DISTANCE,
    CONF_UNIT_PRESSURE,
    CONF_UNIT_SPEED,
    CONF_UNIT_TEMPERATURE,
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
    KMH_TO_MPH_FACTOR,
    KPA_TO_PSI,
    STATE_TYPE_CALC,
    STATE_TYPE_READ,
    UNIT_DISTANCE_KM,
    UNIT_DISTANCE_MI,
    UNIT_PRESSURE_BAR,
    UNIT_PRESSURE_KPA,
    UNIT_PRESSURE_PSI,
    UNIT_SPEED_KMH,
    UNIT_SPEED_MPH,
    UNIT_TEMP_CELSIUS,
    UNIT_TEMP_FAHRENHEIT,
)
from .expressions import ExprParser
from .obd_client import (
    OBDClientBackoffError,
    OBDClientError,
    OBDClientIgnitionOff,
    PythonOBDClient,
)
from .profile import (
    ProfileEntity,
    cast_value,
    decode_pid_bytes,
    format_sensor_native,
)
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
        # All enabled entities are polled and kept in state for CALC dependencies.
        # `entities` exposes only `visible` ones as Home Assistant sensors.
        self._profile_entities = [e for e in profile_entities if e.enabled]
        self._fuel_type = fuel_type
        opts = dict(config_entry.options or {})
        data = dict(config_entry.data or {})
        self._unit_temperature = opts.get(CONF_UNIT_TEMPERATURE, UNIT_TEMP_CELSIUS)
        self._unit_pressure = opts.get(CONF_UNIT_PRESSURE, UNIT_PRESSURE_KPA)
        self._unit_speed = opts.get(CONF_UNIT_SPEED, UNIT_SPEED_KMH)
        self._unit_distance = opts.get(CONF_UNIT_DISTANCE, UNIT_DISTANCE_KM)
        disable_elm_lp = bool(
            opts.get(
                CONF_DISABLE_ELM_LOW_POWER,
                data.get(CONF_DISABLE_ELM_LOW_POWER, False),
            )
        )
        rv_offset = float(
            opts.get(
                CONF_ADAPTER_VOLTAGE_OFFSET,
                DEFAULT_ADAPTER_AT_RV_VOLTAGE_OFFSET_V,
            )
        )
        use_ign_gate = bool(
            opts.get(CONF_USE_IGN_GATE, data.get(CONF_USE_IGN_GATE, DEFAULT_USE_IGN_GATE))
        )
        ign_active_high = bool(
            opts.get(
                CONF_IGN_ACTIVE_HIGH,
                data.get(CONF_IGN_ACTIVE_HIGH, DEFAULT_IGN_ACTIVE_HIGH),
            )
        )
        self._client = PythonOBDClient(
            host,
            port,
            disable_elm_low_power=disable_elm_lp,
            adapter_rv_offset_v=rv_offset,
            use_ign_gate=use_ign_gate,
            ign_active_high=ign_active_high,
        )
        self._last_dtcs: list[str] = []
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
        return [e for e in self._profile_entities if e.visible]

    def native_unit_for(self, ent: ProfileEntity) -> str | None:
        """Native unit for Home Assistant (after user display preferences)."""
        dc = ent.device_class or ""
        if dc == "temperature":
            return "°F" if self._unit_temperature == UNIT_TEMP_FAHRENHEIT else "°C"
        if dc == "speed":
            return "mph" if self._unit_speed == UNIT_SPEED_MPH else "km/h"
        if dc == "pressure":
            if self._unit_pressure == UNIT_PRESSURE_PSI:
                return "psi"
            if self._unit_pressure == UNIT_PRESSURE_BAR:
                return "bar"
            return "kPa"
        if dc == "distance":
            return "mi" if self._unit_distance == UNIT_DISTANCE_MI else "km"
        u = ent.unit or ""
        return u if u else None

    def _apply_user_units(
        self, ent: ProfileEntity, native: float | int | str | bool
    ) -> float | int | str | bool:
        if isinstance(native, (str, bool)):
            return native
        dc = ent.device_class or ""
        if dc == "temperature" and self._unit_temperature == UNIT_TEMP_FAHRENHEIT:
            v = float(native)
            return round(v * 9.0 / 5.0 + 32.0, 1)
        if dc == "speed" and self._unit_speed == UNIT_SPEED_MPH:
            return int(round(float(native) * KMH_TO_MPH_FACTOR))
        if dc == "pressure":
            v = float(native)
            if self._unit_pressure == UNIT_PRESSURE_PSI:
                return round(v * KPA_TO_PSI, 2)
            if self._unit_pressure == UNIT_PRESSURE_BAR:
                return round(v / 100.0, 3)
            return native
        if dc == "distance" and self._unit_distance == UNIT_DISTANCE_MI:
            return int(round(float(native) * KMH_TO_MPH_FACTOR))
        return native

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
                    self._last_dtcs = await self.hass.async_add_executor_job(
                        self._client.fetch_dtcs
                    )
                repl = str(len(self._last_dtcs))
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

                soft_skip = False
                try:
                    await self.hass.async_add_executor_job(self._client.ensure_connected)
                except (OBDClientBackoffError, OBDClientIgnitionOff):
                    soft_skip = True

                if not soft_skip:
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
                        if e.state_type == STATE_TYPE_CALC
                        and e.expr
                        and self._is_due(e, now_ms)
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
                    data[ent.name] = self._apply_user_units(ent, native)

        except (OBDClientError, TimeoutError, OSError) as err:
            await self.hass.async_add_executor_job(self._client.close)
            raise UpdateFailed(f"OBD2 connection error: {err}") from err

        return data

    async def async_shutdown(self) -> None:
        await self.hass.async_add_executor_job(self._client.close)

    async def _update_read(self, ent: ProfileEntity) -> None:
        if ent.read_func == "batteryVoltage":
            v = await self.hass.async_add_executor_job(self._client.read_adapter_voltage)
            if v is None:
                self._store.invalidate(ent.name)
            else:
                self._store.set_value(ent.name, float(v), f"{v}")
            return

        if ent.pid_service != 1 or ent.pid_number is None:
            _LOGGER.debug("Unsupported READ %s (service %s)", ent.name, ent.pid_service)
            return

        res = await self.hass.async_add_executor_job(
            self._client.request_mode01, ent.pid_number
        )
        if not res.ok or not res.data_bytes:
            self._store.invalidate(ent.name)
            return

        raw_val = decode_pid_bytes(
            res.data_bytes,
            ent.num_expected_bytes,
            ent.scale_factor,
            ent.bias,
        )
        typed = cast_value(raw_val, ent.value_type)
        self._store.set_value(ent.name, typed, res.payload_hex)
