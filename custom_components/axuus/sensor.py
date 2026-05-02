"""Sensor platform for the Axuus integration.

Exposes per-code sensors (one per active access code) and aggregate count
sensors (active codes, resident vehicles, guest vehicles).
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AxuusCoordinator

_LOGGER = logging.getLogger(__name__)

# Count sensor definitions: (count_type, friendly_name, data_attribute, icon)
_COUNT_SENSORS: list[tuple[str, str, str, str]] = [
    ("active_codes", "Active Codes", "codes", "mdi:dialpad"),
    ("resident_vehicles", "Resident Vehicles", "resident_vehicles", "mdi:car"),
    ("guest_vehicles", "Guest Vehicles", "guest_vehicles", "mdi:car-outline"),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Axuus sensor entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: AxuusCoordinator = data["coordinator"]

    # Register aggregate count sensors immediately
    aggregate_sensors: list[SensorEntity] = [
        AxuusCountSensor(coordinator, count_type, name, data_attr, icon)
        for count_type, name, data_attr, icon in _COUNT_SENSORS
    ]
    async_add_entities(aggregate_sensors)

    # Track known code IDs to detect additions
    known_code_ids: set[int] = set()

    # Register per-code sensors for codes already present
    if coordinator.data is not None:
        initial_codes = [
            AxuusCodeSensor(coordinator, code_id)
            for code_id in coordinator.data.codes
        ]
        if initial_codes:
            async_add_entities(initial_codes)
            known_code_ids.update(coordinator.data.codes.keys())

    @callback
    def _async_on_coordinator_update() -> None:
        """Register new per-code sensor entities when new code_ids appear."""
        nonlocal known_code_ids
        if coordinator.data is None:
            return

        current_code_ids = set(coordinator.data.codes.keys())
        new_code_ids = current_code_ids - known_code_ids
        if new_code_ids:
            new_entities = [
                AxuusCodeSensor(coordinator, code_id)
                for code_id in new_code_ids
            ]
            async_add_entities(new_entities)
            known_code_ids = known_code_ids | new_code_ids

    # Listen for coordinator updates to detect new codes
    entry.async_on_unload(
        coordinator.async_add_listener(_async_on_coordinator_update)
    )


class AxuusCodeSensor(CoordinatorEntity[AxuusCoordinator], SensorEntity):
    """Sensor entity for a single Axuus access code."""

    def __init__(
        self,
        coordinator: AxuusCoordinator,
        code_id: int,
    ) -> None:
        """Initialize the code sensor."""
        super().__init__(coordinator)
        self._code_id = code_id
        self._attr_unique_id = f"axuus_{code_id}_code"
        self._attr_icon = "mdi:lock-smart"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry_id)},
            name=coordinator.account_name,
            manufacturer="Axuus",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def name(self) -> str:
        """Return a friendly name using the code description."""
        if self.coordinator.data is not None:
            code = self.coordinator.data.codes.get(self._code_id)
            if code is not None and code.description:
                return code.description
        return f"Code {self._code_id}"

    @property
    def native_value(self) -> str | None:
        """Return the 6-digit code string."""
        if self.coordinator.data is None:
            return None
        code = self.coordinator.data.codes.get(self._code_id)
        if code is None:
            return None
        return code.code

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return code metadata as entity attributes."""
        if self.coordinator.data is None:
            return None
        code = self.coordinator.data.codes.get(self._code_id)
        if code is None:
            return None

        # Determine expires_after display value
        if code.is_one_time and code.expires_after is None:
            expires_after_str = "one_time"
        elif code.expires_after is not None:
            expires_after_str = code.expires_after.isoformat()
        else:
            expires_after_str = None

        return {
            "code_id": code.code_id,
            "description": code.description,
            "expires_after": expires_after_str,
            "assign_lp": code.assign_lp,
            "date_created": (
                code.date_created.isoformat() if code.date_created else None
            ),
            "times_used": code.times_used,
            "is_one_time": code.is_one_time,
        }

    @property
    def available(self) -> bool:
        """Return True only if code_id exists in current snapshot and coordinator is healthy."""
        if not self.coordinator.last_update_success:
            return False
        if self.coordinator.data is None:
            return False
        return self._code_id in self.coordinator.data.codes


class AxuusCountSensor(CoordinatorEntity[AxuusCoordinator], SensorEntity):
    """Aggregate count sensor (active codes, resident vehicles, guest vehicles)."""

    def __init__(
        self,
        coordinator: AxuusCoordinator,
        count_type: str,
        name: str,
        data_attr: str,
        icon: str = "mdi:counter",
    ) -> None:
        """Initialize the count sensor."""
        super().__init__(coordinator)
        self._count_type = count_type
        self._data_attr = data_attr
        self._attr_unique_id = f"axuus_{count_type}_count"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry_id)},
            name=coordinator.account_name,
            manufacturer="Axuus",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> int | None:
        """Return the count of items in the corresponding collection."""
        if self.coordinator.data is None:
            return None
        collection = getattr(self.coordinator.data, self._data_attr, None)
        if collection is None:
            return None
        return len(collection)
