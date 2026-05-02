"""Binary sensor platform for the Axuus integration.

Provides a connection status sensor that reflects whether the most recent
poll cycle succeeded.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AxuusCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Axuus binary sensor entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: AxuusCoordinator = data["coordinator"]

    async_add_entities([AxuusConnectionSensor(coordinator)])


class AxuusConnectionSensor(CoordinatorEntity[AxuusCoordinator], BinarySensorEntity):
    """Binary sensor reflecting the Axuus connection status."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: AxuusCoordinator) -> None:
        """Initialize the connection sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = "axuus_connection"
        self._attr_name = "Axuus Connection"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry_id)},
            name=coordinator.account_name,
            manufacturer="Axuus",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def is_on(self) -> bool:
        """Return True if the last poll cycle succeeded."""
        return self.coordinator.last_update_success
