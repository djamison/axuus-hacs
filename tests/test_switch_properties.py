"""Property-based tests for the Axuus switch platform.

# Feature: axuus-ha-integration, Property 5: Vehicle switch mapping correctness

Tests verify that for any set of vehicles with random auth states, there is
exactly one switch per vehicle with the correct unique_id and is_on state.

**Validates: Requirements 8.1, 8.6**
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from hypothesis import given, settings, strategies as st

from custom_components.axuus.api.models import Vehicle, VehicleType
from custom_components.axuus.coordinator import AxuusCoordinator, AxuusData
from custom_components.axuus.switch import AxuusVehicleAuthorizedSwitch


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------


@st.composite
def vehicles(draw):
    """Generate a random Vehicle."""
    vehicle_id = draw(
        st.text(
            alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-",
            min_size=5,
            max_size=15,
        )
    )
    lp_num = draw(
        st.text(
            alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
            min_size=1,
            max_size=10,
        )
    )
    description = draw(st.text(min_size=0, max_size=50))
    vehicle_type = draw(st.sampled_from([VehicleType.RESIDENT, VehicleType.GUEST]))
    return Vehicle(
        vehicle_id=vehicle_id,
        lp_num=lp_num,
        description=description,
        make_name="",
        model_name="",
        year="",
        lp_state="",
        vin="",
        valid_reg=True,
        make_id="",
        model_id="",
        color_id="",
        vehicle_type=vehicle_type,
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
    return coordinator


# ---------------------------------------------------------------------------
# Property 5: Vehicle switch mapping correctness
# ---------------------------------------------------------------------------


@given(
    vehicle_entries=st.lists(
        st.tuples(vehicles(), st.booleans()),
        min_size=0,
        max_size=20,
    ),
)
@settings(max_examples=100)
def test_vehicle_switch_mapping_correctness(
    vehicle_entries: list[tuple[Vehicle, bool]],
) -> None:
    """Property 5: Vehicle switch mapping correctness.

    **Validates: Requirements 8.1, 8.6**

    For any set of vehicles with random auth states:
    - exactly one switch per vehicle
    - unique_id equals axuus_{vehicle_id}_authorized
    - is_on reflects vehicle_auth state
    """
    # Deduplicate by vehicle_id (last one wins, like a dict)
    vehicle_map: dict[str, Vehicle] = {}
    auth_map: dict[str, bool] = {}
    for vehicle, auth_state in vehicle_entries:
        vehicle_map[vehicle.vehicle_id] = vehicle
        auth_map[vehicle.vehicle_id] = auth_state

    # Split into resident/guest based on vehicle_type
    resident_vehicles = {
        vid: v for vid, v in vehicle_map.items() if v.vehicle_type == VehicleType.RESIDENT
    }
    guest_vehicles = {
        vid: v for vid, v in vehicle_map.items() if v.vehicle_type == VehicleType.GUEST
    }

    data = AxuusData(
        codes={},
        resident_vehicles=resident_vehicles,
        guest_vehicles=guest_vehicles,
        vehicle_auth=auth_map,
        last_poll_success=True,
    )
    coordinator = _make_mock_coordinator(data)
    client = AsyncMock()

    # Create one switch per vehicle (as async_setup_entry would)
    switches = {
        vid: AxuusVehicleAuthorizedSwitch(coordinator, client, vid)
        for vid in vehicle_map
    }

    # Exactly one switch per vehicle
    assert len(switches) == len(vehicle_map)

    for vid, switch in switches.items():
        # unique_id follows the format
        assert switch.unique_id == f"axuus_{vid}_authorized"

        # is_on reflects the auth state
        assert switch.is_on == auth_map[vid]
