"""Config flow for OBD2 TCP."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from .const import (
    CONF_DEVICE_NAME,
    CONF_DISABLE_ELM_LOW_POWER,
    CONF_FUEL_TYPE,
    CONF_HOST,
    CONF_PORT,
    CONF_PROFILE,
    CONF_SCAN_INTERVAL,
    CONF_UNIT_DISTANCE,
    CONF_UNIT_PRESSURE,
    CONF_UNIT_SPEED,
    CONF_UNIT_TEMPERATURE,
    DEFAULT_PORT,
    DEFAULT_PROFILE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FUEL_TYPE_GASOLINE,
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
from .fuel_type_labels import fuel_type_config_select_options
from .obd_client import PythonOBDClient
from .profile import list_available_profiles

_LOGGER = logging.getLogger(__name__)


def _options_schema(suggested: dict[str, str | bool]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_UNIT_TEMPERATURE,
                default=suggested.get(CONF_UNIT_TEMPERATURE, UNIT_TEMP_CELSIUS),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[UNIT_TEMP_CELSIUS, UNIT_TEMP_FAHRENHEIT],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_UNIT_PRESSURE,
                default=suggested.get(CONF_UNIT_PRESSURE, UNIT_PRESSURE_KPA),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[UNIT_PRESSURE_KPA, UNIT_PRESSURE_PSI, UNIT_PRESSURE_BAR],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_UNIT_SPEED,
                default=suggested.get(CONF_UNIT_SPEED, UNIT_SPEED_KMH),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[UNIT_SPEED_KMH, UNIT_SPEED_MPH],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_UNIT_DISTANCE,
                default=suggested.get(CONF_UNIT_DISTANCE, UNIT_DISTANCE_KM),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[UNIT_DISTANCE_KM, UNIT_DISTANCE_MI],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_DISABLE_ELM_LOW_POWER,
                default=bool(suggested.get(CONF_DISABLE_ELM_LOW_POWER, False)),
            ): selector.BooleanSelector(),
        }
    )


def _user_data_schema(profiles: list[str]) -> vol.Schema:
    if not profiles:
        profiles = [DEFAULT_PROFILE]
    profile_default = (
        DEFAULT_PROFILE if DEFAULT_PROFILE in profiles else profiles[0]
    )
    return vol.Schema(
        {
            vol.Required(CONF_HOST): str,
            vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.Coerce(int),
            vol.Optional(CONF_DEVICE_NAME): str,
            vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.Coerce(
                int
            ),
            vol.Optional(CONF_PROFILE, default=profile_default): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=profiles,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_FUEL_TYPE,
                default=str(FUEL_TYPE_GASOLINE),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=fuel_type_config_select_options(),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, str]:
    client = PythonOBDClient(data[CONF_HOST], int(data[CONF_PORT]))
    ok = await hass.async_add_executor_job(client.quick_probe)
    if not ok:
        raise CannotConnect
    title = data.get(CONF_DEVICE_NAME) or f"{data[CONF_HOST]}:{data[CONF_PORT]}"
    return {"title": title}


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


# Newer HA: CONN_CLASS_LOCAL_POLL; older: CONNECTION_CLASS_LOCAL_POLL
_CONN_CLASS_LOCAL_POLL = getattr(
    config_entries,
    "CONN_CLASS_LOCAL_POLL",
    getattr(config_entries, "CONNECTION_CLASS_LOCAL_POLL", "local_poll"),
)


class OBD2TCPConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    CONNECTION_CLASS = _CONN_CLASS_LOCAL_POLL

    def __init__(self) -> None:
        super().__init__()
        self._user_data: dict[str, Any] | None = None

    @staticmethod
    @callback
    def async_get_options_flow(
        _config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return OBD2TCPOptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                self._user_data = user_input
                return await self.async_step_units()

        profiles = await self.hass.async_add_executor_job(
            list_available_profiles,
            Path(__file__).parent,
        )
        return self.async_show_form(
            step_id="user",
            data_schema=_user_data_schema(profiles),
            errors=errors,
        )

    async def async_step_units(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if self._user_data is None:
            return await self.async_step_user()

        if user_input is not None:
            await self.async_set_unique_id(
                f"{self._user_data[CONF_HOST]}_{self._user_data[CONF_PORT]}"
            )
            self._abort_if_unique_id_configured()
            ud = self._user_data
            data: dict[str, Any] = {
                CONF_HOST: ud[CONF_HOST],
                CONF_PORT: int(ud[CONF_PORT]),
                CONF_SCAN_INTERVAL: int(ud.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
                CONF_PROFILE: ud.get(CONF_PROFILE, DEFAULT_PROFILE),
                CONF_FUEL_TYPE: int(ud.get(CONF_FUEL_TYPE, str(FUEL_TYPE_GASOLINE))),
            }
            if ud.get(CONF_DEVICE_NAME):
                data[CONF_DEVICE_NAME] = ud[CONF_DEVICE_NAME]
            title = ud.get(CONF_DEVICE_NAME) or f"{ud[CONF_HOST]}:{ud[CONF_PORT]}"
            return self.async_create_entry(
                title=title,
                data=data,
                options=dict(user_input),
            )

        suggested: dict[str, str | bool] = {
            CONF_UNIT_TEMPERATURE: UNIT_TEMP_CELSIUS,
            CONF_UNIT_PRESSURE: UNIT_PRESSURE_KPA,
            CONF_UNIT_SPEED: UNIT_SPEED_KMH,
            CONF_UNIT_DISTANCE: UNIT_DISTANCE_KM,
            CONF_DISABLE_ELM_LOW_POWER: False,
        }
        return self.async_show_form(
            step_id="units",
            data_schema=_options_schema(suggested),
        )


class OBD2TCPOptionsFlowHandler(config_entries.OptionsFlowWithReload):
    """Change display units without removing the integration."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current: dict[str, str | bool] = dict(self.config_entry.options or {})
        if CONF_DISABLE_ELM_LOW_POWER not in current:
            current[CONF_DISABLE_ELM_LOW_POWER] = bool(
                self.config_entry.data.get(CONF_DISABLE_ELM_LOW_POWER, False)
            )
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(current),
        )
