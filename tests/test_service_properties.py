"""Property-based tests for the Axuus authorize vehicle service.

# Feature: axuus-ha-integration, Property 6: Authorize vehicle service idempotency

Tests verify that the authorize_vehicle service handler calls the API with
the correct currently_authorized parameter if and only if states differ,
and performs no API call when states match.

**Validates: Requirements 12.2, 12.3, 12.4**
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from custom_components.axuus import _async_handle_authorize_vehicle
from custom_components.axuus.const import DOMAIN
from custom_components.axuus.coordinator import AxuusData

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VEHICLE_ID = "V-test-0001"


def _setup_hass(current_auth: bool) -> tuple[MagicMock, AsyncMock, MagicMock]:
    """Set up a mock hass with a vehicle in the given auth state."""
    hass = MagicMock()
    client = AsyncMock()
    coordinator = MagicMock()
    coordinator.data = AxuusData(
        codes={},
        resident_vehicles={},
        guest_vehicles={},
        vehicle_auth={VEHICLE_ID: current_auth},
        last_poll_success=True,
    )
    coordinator.async_request_refresh = AsyncMock()

    hass.data = {DOMAIN: {"entry1": {"client": client, "coordinator": coordinator}}}
    hass.bus = MagicMock()

    return hass, client, coordinator


def _make_service_call(hass: MagicMock, data: dict) -> MagicMock:
    """Create a mock ServiceCall."""
    call = MagicMock()
    call.hass = hass
    call.data = data
    return call


# ---------------------------------------------------------------------------
# Property 6: Authorize vehicle service idempotency
# ---------------------------------------------------------------------------


@given(
    current_auth=st.booleans(),
    desired_auth=st.booleans(),
)
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_authorize_vehicle_idempotency(
    current_auth: bool,
    desired_auth: bool,
) -> None:
    """Property 6: Authorize vehicle service idempotency.

    **Validates: Requirements 12.2, 12.3, 12.4**

    For any (current_auth, desired_auth) pair:
    - API called with correct currently_authorized if states differ
    - No API call when states match
    """
    hass, client, coordinator = _setup_hass(current_auth)

    call = _make_service_call(hass, {
        "vehicle_id": VEHICLE_ID,
        "authorized": desired_auth,
    })

    await _async_handle_authorize_vehicle(call)

    if current_auth == desired_auth:
        # Idempotent: no API call, no refresh
        client.authorize_vehicle.assert_not_awaited()
        coordinator.async_request_refresh.assert_not_awaited()
    else:
        # State differs: API called with current state, then refresh
        client.authorize_vehicle.assert_awaited_once_with(
            VEHICLE_ID, currently_authorized=current_auth
        )
        coordinator.async_request_refresh.assert_awaited_once()
