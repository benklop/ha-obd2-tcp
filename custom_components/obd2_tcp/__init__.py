"""OBD2 (TCP) custom integration for Home Assistant."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from .const import (
    CONF_FUEL_TYPE,
    CONF_HOST,
    CONF_PORT,
    CONF_PROFILE,
    CONF_SCAN_INTERVAL,
    DEFAULT_PROFILE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FUEL_TYPE_GASOLINE,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

PLATFORMS: tuple[str, ...] = ("sensor",)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from .coordinator import OBD2TCPCoordinator
    from .profile import async_load_profile_from_package

    component_dir = Path(__file__).parent
    profile_name = entry.data.get(CONF_PROFILE, DEFAULT_PROFILE)
    try:
        profile_entities = await async_load_profile_from_package(
            hass, profile_name, component_dir
        )
    except FileNotFoundError:
        _LOGGER.error("Profile %s not found under profiles/", profile_name)
        return False

    coordinator = OBD2TCPCoordinator(
        hass,
        entry,
        host=entry.data[CONF_HOST],
        port=int(entry.data[CONF_PORT]),
        scan_interval=int(entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        profile_entities=profile_entities,
        fuel_type=int(entry.data.get(CONF_FUEL_TYPE, FUEL_TYPE_GASOLINE)),
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from .coordinator import OBD2TCPCoordinator

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: OBD2TCPCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unload_ok
