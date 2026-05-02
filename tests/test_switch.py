"""Unit tests for the Axuus switch platform.

Tests cover:
- Vehicle authorization switch: is_on, async_turn_on, async_turn_off,
  unique_id, available

Requirements: 8.1–8.8
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.axuus.api.models import Vehicle, VehicleType
from custom_components.axuus.coordinator import AxuusCoordinator, AxuusData
from custom_components.axuus.switch import AxuusVehicleAuthorizedSwitch

# ---------------------------------------------------------------------------
# Sample data (same as test_coordinator.py)
# ---------------------------------------------------------------------------

SAMPLE_VEHICLE = Vehicle(
    vehicle_id="V-aaaa-1111",
    lp_num="ABC123",
    description="Daily Driver",
    make_name="Honda",
    model_name="Pilot",
    year="2021",
    lp_state="NV",
    vin="",
    valid_reg=True,
    make_id="42",
    model_id="512",
    color_id="7",
    vehicle_type=VehicleType.RESIDENT,
)

SAMPLE_VEHICLE_B = Vehicle(
    vehicle_id="V-bbbb-2222",
    lp_num="XYZ789",
    description="Weekend Car",
    make_name="Toyota",
    model_name="Camry",
    year="2023",
    lp_state="CA",
    vin="",
    valid_reg=True,
    make_id="10",
    model_id="200",
    color_id="3",
    vehicle_type=VehicleType.GUEST,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_coordinator(data: AxuusData) -> MagicMock:
    """Create a mock coordinator with the given data."""
    coordinator = MagicMock(spec=AxuusCoordinator)
    coordinator.data = data
    coordinator.last_update_success = True
    coordinator.async_request_refresh = AsyncMock()
    coordinator.config_entry_id = "test_entry"
    coordinator.account_name = "Axuus"
    return coordinator


def _make_data(
    resident_vehicles: dict[str, Vehicle] | None = None,
    guest_vehicles: dict[str, Vehicle] | None = None,
    vehicle_auth: dict[str, bool] | None = None,
) -> AxuusData:
    """Build an AxuusData snapshot with sensible defaults."""
    return AxuusData(
        codes={},
        resident_vehicles=resident_vehicles or {},
        guest_vehicles=guest_vehicles or {},
        vehicle_auth=vehicle_auth or {},
        last_poll_success=True,
    )


def _make_switch(
    coordinator: MagicMock,
    vehicle_id: str = "V-aaaa-1111",
) -> AxuusVehicleAuthorizedSwitch:
    """Create a switch entity with a mocked client and coordinator."""
    client = AsyncMock()
    switch = AxuusVehicleAuthorizedSwitch(coordinator, client, vehicle_id)
    # Provide a mock hass so async_write_ha_state doesn't fail
    switch.hass = MagicMock()
    return switch


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_switch_is_on_reflects_auth_state() -> None:
    """is_on reflects vehicle_auth state."""
    data = _make_data(
        resident_vehicles={SAMPLE_VEHICLE.vehicle_id: SAMPLE_VEHICLE},
        vehicle_auth={"V-aaaa-1111": True},
    )
    coordinator = _make_mock_coordinator(data)
    switch = _make_switch(coordinator, "V-aaaa-1111")

    assert switch.is_on is True

    # Change auth state to False
    data.vehicle_auth["V-aaaa-1111"] = False
    assert switch.is_on is False


async def test_switch_turn_on() -> None:
    """async_turn_on calls authorize_vehicle(currently_authorized=False) and applies optimistic update."""
    data = _make_data(
        resident_vehicles={SAMPLE_VEHICLE.vehicle_id: SAMPLE_VEHICLE},
        vehicle_auth={"V-aaaa-1111": False},
    )
    coordinator = _make_mock_coordinator(data)
    client = AsyncMock()
    switch = AxuusVehicleAuthorizedSwitch(coordinator, client, "V-aaaa-1111")
    switch.hass = MagicMock()
    # Patch async_write_ha_state to avoid HA entity_id check outside full HA runtime
    switch.async_write_ha_state = MagicMock()

    await switch.async_turn_on()

    # Verify API call with currently_authorized=False (to toggle ON)
    client.authorize_vehicle.assert_awaited_once_with(
        "V-aaaa-1111", currently_authorized=False
    )
    # Verify optimistic update
    assert data.vehicle_auth["V-aaaa-1111"] is True
    # Verify state write was triggered
    switch.async_write_ha_state.assert_called_once()


async def test_switch_turn_off() -> None:
    """async_turn_off calls authorize_vehicle(currently_authorized=True) and applies optimistic update."""
    data = _make_data(
        resident_vehicles={SAMPLE_VEHICLE.vehicle_id: SAMPLE_VEHICLE},
        vehicle_auth={"V-aaaa-1111": True},
    )
    coordinator = _make_mock_coordinator(data)
    client = AsyncMock()
    switch = AxuusVehicleAuthorizedSwitch(coordinator, client, "V-aaaa-1111")
    switch.hass = MagicMock()
    # Patch async_write_ha_state to avoid HA entity_id check outside full HA runtime
    switch.async_write_ha_state = MagicMock()

    await switch.async_turn_off()

    # Verify API call with currently_authorized=True (to toggle OFF)
    client.authorize_vehicle.assert_awaited_once_with(
        "V-aaaa-1111", currently_authorized=True
    )
    # Verify optimistic update
    assert data.vehicle_auth["V-aaaa-1111"] is False
    # Verify state write was triggered
    switch.async_write_ha_state.assert_called_once()


def test_switch_unique_id() -> None:
    """unique_id format is axuus_{vehicle_id}_authorized."""
    data = _make_data(
        resident_vehicles={SAMPLE_VEHICLE.vehicle_id: SAMPLE_VEHICLE},
        vehicle_auth={"V-aaaa-1111": True},
    )
    coordinator = _make_mock_coordinator(data)
    switch = _make_switch(coordinator, "V-aaaa-1111")

    assert switch.unique_id == "axuus_V-aaaa-1111_authorized"


def test_switch_available_when_present() -> None:
    """available returns True when vehicle exists in snapshot."""
    data = _make_data(
        resident_vehicles={SAMPLE_VEHICLE.vehicle_id: SAMPLE_VEHICLE},
        vehicle_auth={"V-aaaa-1111": True},
    )
    coordinator = _make_mock_coordinator(data)
    switch = _make_switch(coordinator, "V-aaaa-1111")

    assert switch.available is True


def test_switch_unavailable_when_missing() -> None:
    """available returns False when vehicle disappears from snapshot."""
    data = _make_data(
        resident_vehicles={},
        guest_vehicles={},
        vehicle_auth={},
    )
    coordinator = _make_mock_coordinator(data)
    switch = _make_switch(coordinator, "V-aaaa-1111")

    assert switch.available is False
