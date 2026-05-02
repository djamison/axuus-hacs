"""Button platform for the Axuus integration.

Provides a refresh button that triggers an immediate coordinator poll cycle.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    """Set up Axuus button entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: AxuusCoordinator = data["coordinator"]

    async_add_entities([AxuusRefreshButton(coordinator)])


class AxuusRefreshButton(CoordinatorEntity[AxuusCoordinator], ButtonEntity):
    """Button entity that triggers an immediate data refresh."""

    def __init__(self, coordinator: AxuusCoordinator) -> None:
        """Initialize the refresh button."""
        super().__init__(coordinator)
        self._attr_unique_id = "axuus_refresh"
        self._attr_name = "Refresh"
        self._attr_icon = "mdi:refresh"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry_id)},
            name=coordinator.account_name,
            manufacturer="Axuus",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_press(self) -> None:
        """Handle the button press — trigger an immediate coordinator refresh."""
        await self.coordinator.async_request_refresh()
