"""Unit tests for the Axuus data coordinator.

Tests cover:
- Successful poll cycle (all three list calls, snapshot stored)
- First poll populates vehicle_auth via get_vehicle()
- Auth recovery: AxuusAuthError → re-login → retry succeeds
- Persistent auth failure: re-login also fails → ConfigEntryAuthFailed
- Transient error: AxuusServerError → UpdateFailed
- Diff engine: code created, expired, used events
- Diff engine: vehicle added, removed events
- New vehicle triggers get_vehicle() on next poll

Requirements: 4.1–4.6, 5.1–5.5
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.axuus.api.exceptions import AxuusAuthError, AxuusServerError
from custom_components.axuus.api.models import AccessCode, Vehicle, VehicleType
from custom_components.axuus.const import (
    EVENT_CODE_CREATED,
    EVENT_CODE_EXPIRED,
    EVENT_CODE_USED,
    EVENT_VEHICLE_ADDED,
    EVENT_VEHICLE_REMOVED,
)
from custom_components.axuus.coordinator import AxuusCoordinator, AxuusData


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_CODE = AccessCode(
    code_id=100001,
    code="123456",
    description="Cleaner Tuesday",
    is_one_time=False,
    expires_after=datetime(2026, 5, 8, 9, 0, 0),
    assign_lp=False,
    date_created=datetime(2026, 5, 1, 9, 0, 0),
    times_used=0,
)

SAMPLE_CODE_USED = AccessCode(
    code_id=100001,
    code="123456",
    description="Cleaner Tuesday",
    is_one_time=False,
    expires_after=datetime(2026, 5, 8, 9, 0, 0),
    assign_lp=False,
    date_created=datetime(2026, 5, 1, 9, 0, 0),
    times_used=3,
)

SAMPLE_CODE_B = AccessCode(
    code_id=100002,
    code="654321",
    description="Dog Walker",
    is_one_time=True,
    expires_after=None,
    assign_lp=False,
    date_created=datetime(2026, 5, 2, 10, 0, 0),
    times_used=1,
)

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


def _make_coordinator(
    mock_client: AsyncMock | None = None,
) -> tuple[AxuusCoordinator, AsyncMock, MagicMock]:
    """Create an AxuusCoordinator with mocked hass and client.

    Patches HA's frame.report_usage to avoid the "Frame helper not set up"
    error that occurs when DataUpdateCoordinator.__init__ is called outside
    a real HA runtime.

    Returns (coordinator, mock_client, mock_hass).
    """
    hass = MagicMock()
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()

    if mock_client is None:
        mock_client = AsyncMock()
        mock_client.list_codes = AsyncMock(return_value=[])
        mock_client.list_resident_vehicles = AsyncMock(return_value=[])
        mock_client.list_guest_vehicles = AsyncMock(return_value=[])
        mock_client.get_vehicle = AsyncMock(return_value={"Ver_Auth": True})
        mock_client.login = AsyncMock()

    with patch("homeassistant.helpers.frame.report_usage"):
        coordinator = AxuusCoordinator(
            hass, mock_client, update_interval=timedelta(seconds=60)
        )
    return coordinator, mock_client, hass


# ---------------------------------------------------------------------------
# 1. Successful poll cycle
# ---------------------------------------------------------------------------


async def test_successful_poll_cycle() -> None:
    """All three list calls are made and the snapshot is stored correctly."""
    coordinator, client, _hass = _make_coordinator()

    client.list_codes.return_value = [SAMPLE_CODE]
    client.list_resident_vehicles.return_value = [SAMPLE_VEHICLE]
    client.list_guest_vehicles.return_value = []
    client.get_vehicle.return_value = {"Ver_Auth": True}

    data = await coordinator._do_poll()

    # All three list calls made
    client.list_codes.assert_awaited_once()
    client.list_resident_vehicles.assert_awaited_once()
    client.list_guest_vehicles.assert_awaited_once()

    # Snapshot stored correctly
    assert data.last_poll_success is True
    assert 100001 in data.codes
    assert data.codes[100001] == SAMPLE_CODE
    assert "V-aaaa-1111" in data.resident_vehicles
    assert data.resident_vehicles["V-aaaa-1111"] == SAMPLE_VEHICLE
    assert data.guest_vehicles == {}


# ---------------------------------------------------------------------------
# 2. First poll calls get_vehicle for each vehicle
# ---------------------------------------------------------------------------


async def test_first_poll_calls_get_vehicle() -> None:
    """First poll calls get_vehicle() for each vehicle to populate vehicle_auth."""
    coordinator, client, _hass = _make_coordinator()

    client.list_codes.return_value = []
    client.list_resident_vehicles.return_value = [SAMPLE_VEHICLE]
    client.list_guest_vehicles.return_value = [SAMPLE_VEHICLE_B]
    client.get_vehicle.return_value = {"Ver_Auth": True}

    assert coordinator._previous_data is None  # First poll

    data = await coordinator._do_poll()

    # get_vehicle called for both vehicles
    assert client.get_vehicle.await_count == 2
    client.get_vehicle.assert_any_await("V-aaaa-1111")
    client.get_vehicle.assert_any_await("V-bbbb-2222")

    # vehicle_auth populated
    assert data.vehicle_auth["V-aaaa-1111"] is True
    assert data.vehicle_auth["V-bbbb-2222"] is True


# ---------------------------------------------------------------------------
# 3. Auth recovery success
# ---------------------------------------------------------------------------


async def test_auth_recovery_success() -> None:
    """AxuusAuthError → re-login → retry succeeds."""
    coordinator, client, _hass = _make_coordinator()

    # First call to list_codes raises AxuusAuthError.
    # After re-login, second call succeeds.
    call_count = 0

    async def _list_codes_side_effect():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise AxuusAuthError("session expired")
        return [SAMPLE_CODE]

    client.list_codes = AsyncMock(side_effect=_list_codes_side_effect)
    client.list_resident_vehicles.return_value = []
    client.list_guest_vehicles.return_value = []

    # _async_update_data handles the auth recovery
    data = await coordinator._async_update_data()

    # login() was called for re-auth
    client.login.assert_awaited_once()

    # Data returned successfully after retry
    assert data.last_poll_success is True
    assert 100001 in data.codes


# ---------------------------------------------------------------------------
# 4. Persistent auth failure
# ---------------------------------------------------------------------------


async def test_persistent_auth_failure() -> None:
    """Re-login also fails → ConfigEntryAuthFailed raised."""
    coordinator, client, _hass = _make_coordinator()

    # list_codes always raises AxuusAuthError
    client.list_codes.side_effect = AxuusAuthError("session expired")
    # Re-login also fails
    client.login.side_effect = AxuusAuthError("bad credentials")

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()

    client.login.assert_awaited_once()


# ---------------------------------------------------------------------------
# 5. Transient error
# ---------------------------------------------------------------------------


async def test_transient_error() -> None:
    """AxuusServerError → UpdateFailed raised."""
    coordinator, client, _hass = _make_coordinator()

    client.list_codes.side_effect = AxuusServerError("500 Internal Server Error")

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


# ---------------------------------------------------------------------------
# 6. Diff fires code_created
# ---------------------------------------------------------------------------


async def test_diff_fires_code_created() -> None:
    """New code_id in snapshot → axuus_code_created event fired."""
    coordinator, client, hass = _make_coordinator()

    # Set up previous data with no codes
    coordinator._previous_data = AxuusData(
        codes={},
        resident_vehicles={},
        guest_vehicles={},
        vehicle_auth={},
        last_poll_success=True,
    )

    # New poll returns one code
    client.list_codes.return_value = [SAMPLE_CODE]
    client.list_resident_vehicles.return_value = []
    client.list_guest_vehicles.return_value = []

    await coordinator._do_poll()

    # Check that axuus_code_created was fired
    hass.bus.async_fire.assert_any_call(
        EVENT_CODE_CREATED,
        {
            "code_id": 100001,
            "code": "123456",
            "description": "Cleaner Tuesday",
            "expires_after": "2026-05-08T09:00:00",
            "is_one_time": False,
        },
    )


# ---------------------------------------------------------------------------
# 7. Diff fires code_expired
# ---------------------------------------------------------------------------


async def test_diff_fires_code_expired() -> None:
    """Code_id removed from snapshot → axuus_code_expired event fired."""
    coordinator, client, hass = _make_coordinator()

    # Previous data has one code
    coordinator._previous_data = AxuusData(
        codes={100001: SAMPLE_CODE},
        resident_vehicles={},
        guest_vehicles={},
        vehicle_auth={},
        last_poll_success=True,
    )

    # New poll returns no codes
    client.list_codes.return_value = []
    client.list_resident_vehicles.return_value = []
    client.list_guest_vehicles.return_value = []

    await coordinator._do_poll()

    hass.bus.async_fire.assert_any_call(
        EVENT_CODE_EXPIRED,
        {
            "code_id": 100001,
            "code": "123456",
            "description": "Cleaner Tuesday",
            "was_one_time": False,
        },
    )


# ---------------------------------------------------------------------------
# 8. Diff fires code_used
# ---------------------------------------------------------------------------


async def test_diff_fires_code_used() -> None:
    """times_used increased → axuus_code_used event fired."""
    coordinator, client, hass = _make_coordinator()

    # Previous data has code with times_used=0
    coordinator._previous_data = AxuusData(
        codes={100001: SAMPLE_CODE},
        resident_vehicles={},
        guest_vehicles={},
        vehicle_auth={},
        last_poll_success=True,
    )

    # New poll returns same code with times_used=3
    client.list_codes.return_value = [SAMPLE_CODE_USED]
    client.list_resident_vehicles.return_value = []
    client.list_guest_vehicles.return_value = []

    await coordinator._do_poll()

    hass.bus.async_fire.assert_any_call(
        EVENT_CODE_USED,
        {
            "code_id": 100001,
            "code": "123456",
            "description": "Cleaner Tuesday",
            "times_used": 3,
            "previous_times_used": 0,
        },
    )


# ---------------------------------------------------------------------------
# 9. Diff fires vehicle_added
# ---------------------------------------------------------------------------


async def test_diff_fires_vehicle_added() -> None:
    """New vehicle_id → axuus_vehicle_added event fired."""
    coordinator, client, hass = _make_coordinator()

    # Previous data has no vehicles
    coordinator._previous_data = AxuusData(
        codes={},
        resident_vehicles={},
        guest_vehicles={},
        vehicle_auth={},
        last_poll_success=True,
    )

    # New poll returns one resident vehicle
    client.list_codes.return_value = []
    client.list_resident_vehicles.return_value = [SAMPLE_VEHICLE]
    client.list_guest_vehicles.return_value = []
    client.get_vehicle.return_value = {"Ver_Auth": True}

    await coordinator._do_poll()

    hass.bus.async_fire.assert_any_call(
        EVENT_VEHICLE_ADDED,
        {
            "vehicle_id": "V-aaaa-1111",
            "lp_num": "ABC123",
            "lp_state": "NV",
            "description": "Daily Driver",
            "vehicle_type": "resident",
        },
    )


# ---------------------------------------------------------------------------
# 10. Diff fires vehicle_removed
# ---------------------------------------------------------------------------


async def test_diff_fires_vehicle_removed() -> None:
    """Vehicle_id removed → axuus_vehicle_removed event fired."""
    coordinator, client, hass = _make_coordinator()

    # Previous data has one vehicle
    coordinator._previous_data = AxuusData(
        codes={},
        resident_vehicles={"V-aaaa-1111": SAMPLE_VEHICLE},
        guest_vehicles={},
        vehicle_auth={"V-aaaa-1111": True},
        last_poll_success=True,
    )

    # New poll returns no vehicles
    client.list_codes.return_value = []
    client.list_resident_vehicles.return_value = []
    client.list_guest_vehicles.return_value = []

    await coordinator._do_poll()

    hass.bus.async_fire.assert_any_call(
        EVENT_VEHICLE_REMOVED,
        {
            "vehicle_id": "V-aaaa-1111",
            "lp_num": "ABC123",
            "description": "Daily Driver",
            "vehicle_type": "resident",
            "removed_via": "external",
        },
    )


# ---------------------------------------------------------------------------
# 11. New vehicle triggers get_vehicle
# ---------------------------------------------------------------------------


async def test_new_vehicle_triggers_get_vehicle() -> None:
    """New vehicle appearing triggers get_vehicle() call on next poll."""
    coordinator, client, hass = _make_coordinator()

    # Previous data has one vehicle (already fetched)
    coordinator._previous_data = AxuusData(
        codes={},
        resident_vehicles={"V-aaaa-1111": SAMPLE_VEHICLE},
        guest_vehicles={},
        vehicle_auth={"V-aaaa-1111": True},
        last_poll_success=True,
    )

    # New poll returns the existing vehicle plus a new one
    client.list_codes.return_value = []
    client.list_resident_vehicles.return_value = [SAMPLE_VEHICLE]
    client.list_guest_vehicles.return_value = [SAMPLE_VEHICLE_B]
    client.get_vehicle.return_value = {"Ver_Auth": False}

    data = await coordinator._do_poll()

    # get_vehicle called only for the NEW vehicle, not the existing one
    client.get_vehicle.assert_awaited_once_with("V-bbbb-2222")

    # Auth state: existing vehicle carried forward, new vehicle fetched
    assert data.vehicle_auth["V-aaaa-1111"] is True  # carried forward
    assert data.vehicle_auth["V-bbbb-2222"] is False  # freshly fetched
