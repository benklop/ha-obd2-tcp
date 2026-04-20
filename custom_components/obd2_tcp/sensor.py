"""Sensor platform for OBD2 TCP."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.typing import StateType

from .const import CONF_DEVICE_NAME, DOMAIN
from .coordinator import OBD2TCPCoordinator
from .profile import ProfileEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: OBD2TCPCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        OBD2TcpSensor(coordinator, ent) for ent in coordinator.entities
    )


class OBD2TcpSensor(CoordinatorEntity[OBD2TCPCoordinator], SensorEntity):
    """One profile entity as a sensor."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: OBD2TCPCoordinator, entity: ProfileEntity) -> None:
        super().__init__(coordinator)
        self._profile = entity
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{entity.name}"
        self.entity_description = SensorEntityDescription(
            key=entity.name,
            name=entity.description,
            native_unit_of_measurement=coordinator.native_unit_for(entity)
            or (entity.unit or None),
            icon=f"mdi:{entity.icon}" if entity.icon else None,
            device_class=entity.device_class or None,
            state_class=SensorStateClass.MEASUREMENT
            if entity.measurement
            else None,
            entity_category=EntityCategory.DIAGNOSTIC if entity.diagnostic else None,
        )

    @property
    def device_info(self) -> DeviceInfo:
        name = self.coordinator.config_entry.data.get(
            CONF_DEVICE_NAME, self.coordinator.host
        )
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            name=name,
            manufacturer="OBD2 TCP",
            model="ELM327",
        )

    @property
    def native_value(self) -> StateType:
        data = self.coordinator.data
        if data is None:
            return None
        return data.get(self._profile.name)

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        if data is None:
            return False
        return (
            self.coordinator.last_update_success
            and self._profile.name in data
        )
