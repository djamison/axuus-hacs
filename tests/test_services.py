"""Unit tests for the Axuus service handlers.

Tests cover:
- create_code: calls client.create_code() with correct args and triggers refresh
- update_code: calls client.update_code() with correct args and triggers refresh
- delete_code: calls client.delete_code() and triggers refresh
- authorize_vehicle: state change calls API with correct currently_authorized
- authorize_vehicle: idempotent — no API call when already in desired state
- remove_vehicle: confirm=true calls inactivate_vehicle() and triggers refresh
- remove_vehicle: confirm=false raises ServiceValidationError
- refresh: calls coordinator.async_request_refresh()

Requirements: 11.1–11.7, 12.1–12.7, 13.1–13.2
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.axuus import (
    _async_handle_authorize_vehicle,
    _async_handle_create_code,
    _async_handle_delete_code,
    _async_handle_refresh,
    _async_handle_remove_vehicle,
    _async_handle_update_code,
)
from custom_components.axuus.const import DOMAIN
from custom_components.axuus.coordinator import AxuusData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_hass(
    vehicle_auth: dict[str, bool] | None = None,
) -> tuple[MagicMock, AsyncMock, MagicMock]:
    """Set up a mock hass with a mock client and coordinator in hass.data.

    Returns (hass, client, coordinator).
    """
    hass = MagicMock()
    client = AsyncMock()
    coordinator = MagicMock()
    coordinator.data = AxuusData(
        codes={},
        resident_vehicles={},
        guest_vehicles={},
        vehicle_auth=vehicle_auth or {},
        last_poll_success=True,
    )
    coordinator.async_request_refresh = AsyncMock()

    hass.data = {DOMAIN: {"entry1": {"client": client, "coordinator": coordinator}}}
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()

    return hass, client, coordinator


def _make_service_call(hass: MagicMock, data: dict) -> MagicMock:
    """Create a mock ServiceCall with the given hass and data."""
    call = MagicMock()
    call.hass = hass
    call.data = data
    return call


# ---------------------------------------------------------------------------
# 1. create_code
# ---------------------------------------------------------------------------


async def test_create_code() -> None:
    """create_code calls client.create_code() with correct args and triggers refresh."""
    hass, client, coordinator = _setup_hass()
    client.create_code.return_value = "987654"

    call = _make_service_call(hass, {
        "description": "Plumber visit",
        "expires_after": "oneday",
        "assign_lp": True,
        "email_to": "plumber@example.com",
        "sms_to": "+15551234567",
    })

    await _async_handle_create_code(call)

    client.create_code.assert_awaited_once_with(
        "Plumber visit",
        "oneday",
        assign_lp=True,
        email_to="plumber@example.com",
        sms_to="+15551234567",
    )
    coordinator.async_request_refresh.assert_awaited_once()


# ---------------------------------------------------------------------------
# 2. update_code
# ---------------------------------------------------------------------------


async def test_update_code() -> None:
    """update_code calls client.update_code() with correct args and triggers refresh."""
    hass, client, coordinator = _setup_hass()
    client.update_code.return_value = True

    call = _make_service_call(hass, {
        "code_id": 100001,
        "description": "Updated description",
        "assign_lp": True,
        "email_to": "new@example.com",
        "sms_to": "",
    })

    await _async_handle_update_code(call)

    client.update_code.assert_awaited_once_with(
        100001,
        description="Updated description",
        assign_lp=True,
        email_to="new@example.com",
        sms_to="",
    )
    coordinator.async_request_refresh.assert_awaited_once()


# ---------------------------------------------------------------------------
# 3. delete_code
# ---------------------------------------------------------------------------


async def test_delete_code() -> None:
    """delete_code calls client.delete_code() and triggers refresh."""
    hass, client, coordinator = _setup_hass()
    client.delete_code.return_value = True

    call = _make_service_call(hass, {"code_id": 100001})

    await _async_handle_delete_code(call)

    client.delete_code.assert_awaited_once_with(100001)
    coordinator.async_request_refresh.assert_awaited_once()


# ---------------------------------------------------------------------------
# 4. authorize_vehicle — state change
# ---------------------------------------------------------------------------


async def test_authorize_vehicle_state_change() -> None:
    """authorize_vehicle calls API with correct currently_authorized when state differs."""
    # Vehicle is currently unauthorized, user wants to authorize
    hass, client, coordinator = _setup_hass(
        vehicle_auth={"V-aaaa-1111": False},
    )
    client.authorize_vehicle.return_value = True

    call = _make_service_call(hass, {
        "vehicle_id": "V-aaaa-1111",
        "authorized": True,
    })

    await _async_handle_authorize_vehicle(call)

    # API should be called with currently_authorized=False (the current state)
    client.authorize_vehicle.assert_awaited_once_with(
        "V-aaaa-1111", currently_authorized=False
    )
    coordinator.async_request_refresh.assert_awaited_once()


async def test_authorize_vehicle_state_change_deauthorize() -> None:
    """authorize_vehicle calls API to deauthorize when currently authorized."""
    # Vehicle is currently authorized, user wants to deauthorize
    hass, client, coordinator = _setup_hass(
        vehicle_auth={"V-aaaa-1111": True},
    )
    client.authorize_vehicle.return_value = True

    call = _make_service_call(hass, {
        "vehicle_id": "V-aaaa-1111",
        "authorized": False,
    })

    await _async_handle_authorize_vehicle(call)

    # API should be called with currently_authorized=True (the current state)
    client.authorize_vehicle.assert_awaited_once_with(
        "V-aaaa-1111", currently_authorized=True
    )
    coordinator.async_request_refresh.assert_awaited_once()


# ---------------------------------------------------------------------------
# 5. authorize_vehicle — idempotent
# ---------------------------------------------------------------------------


async def test_authorize_vehicle_idempotent() -> None:
    """No API call when vehicle is already in the desired state."""
    # Vehicle is already authorized, user requests authorized=True
    hass, client, coordinator = _setup_hass(
        vehicle_auth={"V-aaaa-1111": True},
    )

    call = _make_service_call(hass, {
        "vehicle_id": "V-aaaa-1111",
        "authorized": True,
    })

    await _async_handle_authorize_vehicle(call)

    # No API call should be made
    client.authorize_vehicle.assert_not_awaited()
    # No refresh needed either
    coordinator.async_request_refresh.assert_not_awaited()


async def test_authorize_vehicle_idempotent_unauthorized() -> None:
    """No API call when vehicle is already unauthorized and desired is False."""
    hass, client, coordinator = _setup_hass(
        vehicle_auth={"V-aaaa-1111": False},
    )

    call = _make_service_call(hass, {
        "vehicle_id": "V-aaaa-1111",
        "authorized": False,
    })

    await _async_handle_authorize_vehicle(call)

    client.authorize_vehicle.assert_not_awaited()
    coordinator.async_request_refresh.assert_not_awaited()


# ---------------------------------------------------------------------------
# 6. remove_vehicle — confirmed
# ---------------------------------------------------------------------------


async def test_remove_vehicle_confirmed() -> None:
    """remove_vehicle with confirm=true calls inactivate_vehicle() and triggers refresh."""
    hass, client, coordinator = _setup_hass()
    client.inactivate_vehicle.return_value = True

    call = _make_service_call(hass, {
        "vehicle_id": "V-aaaa-1111",
        "confirm": True,
    })

    await _async_handle_remove_vehicle(call)

    client.inactivate_vehicle.assert_awaited_once_with("V-aaaa-1111")
    coordinator.async_request_refresh.assert_awaited_once()


# ---------------------------------------------------------------------------
# 7. remove_vehicle — not confirmed
# ---------------------------------------------------------------------------


async def test_remove_vehicle_not_confirmed() -> None:
    """remove_vehicle with confirm=false raises ServiceValidationError."""
    hass, client, coordinator = _setup_hass()

    call = _make_service_call(hass, {
        "vehicle_id": "V-aaaa-1111",
        "confirm": False,
    })

    with pytest.raises(ServiceValidationError):
        await _async_handle_remove_vehicle(call)

    # No API call should be made
    client.inactivate_vehicle.assert_not_awaited()


# ---------------------------------------------------------------------------
# 8. refresh
# ---------------------------------------------------------------------------


async def test_refresh() -> None:
    """refresh calls coordinator.async_request_refresh()."""
    hass, client, coordinator = _setup_hass()

    call = _make_service_call(hass, {})

    await _async_handle_refresh(call)

    coordinator.async_request_refresh.assert_awaited_once()
