"""Config flow for OBD2 TCP."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_DEVICE_NAME,
    CONF_FUEL_TYPE,
    CONF_HOST,
    CONF_PORT,
    CONF_PROFILE,
    CONF_SCAN_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_PROFILE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FUEL_TYPE_GASOLINE,
)
from .elm_connection import ELMConnection, ELMConnectionError
from .protocol import OBDProtocol

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.Coerce(int),
        vol.Optional(CONF_DEVICE_NAME): str,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.Coerce(int),
        vol.Optional(CONF_PROFILE, default=DEFAULT_PROFILE): str,
        vol.Optional(CONF_FUEL_TYPE, default=FUEL_TYPE_GASOLINE): vol.Coerce(int),
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, str]:
    conn = ELMConnection(data[CONF_HOST], int(data[CONF_PORT]))
    proto = OBDProtocol(conn)
    try:
        ok = await proto.async_quick_probe()
    finally:
        await conn.async_disconnect()
    if not ok:
        raise CannotConnect
    title = data.get(CONF_DEVICE_NAME) or f"{data[CONF_HOST]}:{data[CONF_PORT]}"
    return {"title": title}


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class OBD2TCPConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    CONNECTION_CLASS = config_entries.CONNECTION_CLASS_LOCAL_POLL

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except ELMConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(
                    f"{user_input[CONF_HOST]}_{user_input[CONF_PORT]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
