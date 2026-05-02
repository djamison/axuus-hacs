"""Switch platform for the Axuus integration.

Exposes per-vehicle authorization toggle switches. Turning a switch ON
authorizes the vehicle for gate access; turning it OFF unauthorizes it.
Uses optimistic state updates after successful API calls.
"""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api.client import AxuusClient
from .const import DOMAIN
from .coordinator import AxuusCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Axuus switch entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: AxuusCoordinator = data["coordinator"]
    client: AxuusClient = data["client"]

    # Track known vehicle IDs to detect additions
    known_vehicle_ids: set[str] = set()

    # Register switches for vehicles already present
    if coordinator.data is not None:
        all_vehicles = coordinator.data.all_vehicles
        initial_switches = [
            AxuusVehicleAuthorizedSwitch(coordinator, client, vehicle_id)
            for vehicle_id in all_vehicles
        ]
        if initial_switches:
            async_add_entities(initial_switches)
            known_vehicle_ids.update(all_vehicles.keys())

    @callback
    def _async_on_coordinator_update() -> None:
        """Register new switch entities when new vehicle_ids appear."""
        nonlocal known_vehicle_ids
        if coordinator.data is None:
            return

        current_vehicle_ids = set(coordinator.data.all_vehicles.keys())
        new_vehicle_ids = current_vehicle_ids - known_vehicle_ids
        if new_vehicle_ids:
            new_entities = [
                AxuusVehicleAuthorizedSwitch(coordinator, client, vehicle_id)
                for vehicle_id in new_vehicle_ids
            ]
            async_add_entities(new_entities)
            known_vehicle_ids = known_vehicle_ids | new_vehicle_ids

    # Listen for coordinator updates to detect new vehicles
    entry.async_on_unload(
        coordinator.async_add_listener(_async_on_coordinator_update)
    )


class AxuusVehicleAuthorizedSwitch(CoordinatorEntity[AxuusCoordinator], SwitchEntity):
    """Switch entity for a vehicle's gate authorization state."""

    def __init__(
        self,
        coordinator: AxuusCoordinator,
        client: AxuusClient,
        vehicle_id: str,
    ) -> None:
        """Initialize the vehicle authorization switch."""
        super().__init__(coordinator)
        self._client = client
        self._vehicle_id = vehicle_id
        self._attr_unique_id = f"axuus_{vehicle_id}_authorized"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry_id)},
            name=coordinator.account_name,
            manufacturer="Axuus",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def name(self) -> str:
        """Return a friendly name using description, LP, and vehicle type."""
        if self.coordinator.data is not None:
            vehicle = self.coordinator.data.all_vehicles.get(self._vehicle_id)
            if vehicle is not None:
                vtype = "Guest" if vehicle.vehicle_type.value == "guest" else "Resident"
                label = vehicle.description or vehicle.lp_num or self._vehicle_id
                return f"{label} ({vtype})"
        return f"Vehicle {self._vehicle_id}"

    @property
    def icon(self) -> str:
        """Return an icon distinguishing resident from guest vehicles."""
        if self.coordinator.data is not None:
            vehicle = self.coordinator.data.all_vehicles.get(self._vehicle_id)
            if vehicle is not None and vehicle.vehicle_type.value == "guest":
                return "mdi:car-outline"
        return "mdi:car"

    @property
    def is_on(self) -> bool | None:
        """Return True if the vehicle is authorized."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.vehicle_auth.get(self._vehicle_id, False)

    async def async_turn_on(self, **kwargs) -> None:
        """Authorize the vehicle (send currently_authorized=False to toggle ON)."""
        await self._client.authorize_vehicle(
            self._vehicle_id, currently_authorized=False
        )
        # Optimistic update
        self.coordinator.data.vehicle_auth[self._vehicle_id] = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Unauthorize the vehicle (send currently_authorized=True to toggle OFF)."""
        await self._client.authorize_vehicle(
            self._vehicle_id, currently_authorized=True
        )
        # Optimistic update
        self.coordinator.data.vehicle_auth[self._vehicle_id] = False
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True only if vehicle_id exists in current snapshot and coordinator is healthy."""
        if not self.coordinator.last_update_success:
            return False
        if self.coordinator.data is None:
            return False
        return self._vehicle_id in self.coordinator.data.all_vehicles
