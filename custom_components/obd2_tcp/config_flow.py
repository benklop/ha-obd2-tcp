"""Config flow for OBD2 TCP."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

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
from .profile import list_available_profiles
from .protocol import OBDProtocol

_LOGGER = logging.getLogger(__name__)


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

        profiles = await self.hass.async_add_executor_job(
            list_available_profiles,
            Path(__file__).parent,
        )
        return self.async_show_form(
            step_id="user",
            data_schema=_user_data_schema(profiles),
            errors=errors,
        )
