"""Property-based tests for the Axuus diff engine.

# Feature: axuus-ha-integration, Property 1: Code diff engine produces correct events
# Feature: axuus-ha-integration, Property 2: Vehicle diff engine produces correct events

Tests verify that the coordinator's _diff_and_fire_events method fires
exactly the right set of events for any pair of snapshots.

**Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5**
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from hypothesis import given, settings, strategies as st

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
# Hypothesis strategies
# ---------------------------------------------------------------------------


@st.composite
def access_codes(draw):
    """Generate a random AccessCode."""
    code_id = draw(st.integers(min_value=1, max_value=999999))
    code = draw(st.text(alphabet="0123456789", min_size=6, max_size=6))
    description = draw(st.text(min_size=1, max_size=50))
    is_one_time = draw(st.booleans())
    expires_after = draw(
        st.one_of(
            st.none(),
            st.datetimes(
                min_value=datetime(2020, 1, 1), max_value=datetime(2030, 12, 31)
            ),
        )
    )
    assign_lp = draw(st.booleans())
    date_created = draw(
        st.one_of(
            st.none(),
            st.datetimes(
                min_value=datetime(2020, 1, 1), max_value=datetime(2030, 12, 31)
            ),
        )
    )
    times_used = draw(st.integers(min_value=0, max_value=1000))
    return AccessCode(
        code_id=code_id,
        code=code,
        description=description,
        is_one_time=is_one_time,
        expires_after=expires_after,
        assign_lp=assign_lp,
        date_created=date_created,
        times_used=times_used,
    )


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


def _make_coordinator() -> tuple[AxuusCoordinator, MagicMock]:
    """Create an AxuusCoordinator with mocked hass and client."""
    hass = MagicMock()
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()

    client = AsyncMock()

    with patch("homeassistant.helpers.frame.report_usage"):
        coordinator = AxuusCoordinator(
            hass, client, update_interval=timedelta(seconds=60)
        )
    return coordinator, hass


def _make_data(
    codes: dict[int, AccessCode] | None = None,
    resident_vehicles: dict[str, Vehicle] | None = None,
    guest_vehicles: dict[str, Vehicle] | None = None,
) -> AxuusData:
    """Build an AxuusData snapshot."""
    return AxuusData(
        codes=codes or {},
        resident_vehicles=resident_vehicles or {},
        guest_vehicles=guest_vehicles or {},
        vehicle_auth={},
        last_poll_success=True,
    )


# ---------------------------------------------------------------------------
# Property 1: Code diff engine produces correct events
# ---------------------------------------------------------------------------


@given(
    old_code_list=st.lists(access_codes(), max_size=15),
    new_code_list=st.lists(access_codes(), max_size=15),
)
@settings(max_examples=100)
def test_code_diff_produces_correct_events(
    old_code_list: list[AccessCode],
    new_code_list: list[AccessCode],
) -> None:
    """Property 1: Code diff engine produces correct events.

    **Validates: Requirements 5.1, 5.2, 5.3**

    For any two code snapshots, the diff engine fires:
    - exactly one axuus_code_created per new code_id
    - exactly one axuus_code_expired per removed code_id
    - exactly one axuus_code_used per code_id with increased times_used
    - no other code events
    """
    # Key by code_id so dict key matches the object's identity
    old_codes = {c.code_id: c for c in old_code_list}
    new_codes = {c.code_id: c for c in new_code_list}

    coordinator, hass = _make_coordinator()

    old_data = _make_data(codes=old_codes)
    new_data = _make_data(codes=new_codes)

    coordinator._diff_and_fire_events(old_data, new_data)

    # Collect all fired events
    calls = hass.bus.async_fire.call_args_list
    created_events = [c for c in calls if c[0][0] == EVENT_CODE_CREATED]
    expired_events = [c for c in calls if c[0][0] == EVENT_CODE_EXPIRED]
    used_events = [c for c in calls if c[0][0] == EVENT_CODE_USED]

    # Compute expected sets
    old_ids = set(old_codes)
    new_ids = set(new_codes)

    expected_created = new_ids - old_ids
    expected_expired = old_ids - new_ids
    expected_used = {
        cid
        for cid in old_ids & new_ids
        if new_codes[cid].times_used > old_codes[cid].times_used
    }

    # Verify counts
    assert len(created_events) == len(expected_created), (
        f"Expected {len(expected_created)} created events, got {len(created_events)}"
    )
    assert len(expired_events) == len(expected_expired), (
        f"Expected {len(expected_expired)} expired events, got {len(expired_events)}"
    )
    assert len(used_events) == len(expected_used), (
        f"Expected {len(expected_used)} used events, got {len(used_events)}"
    )

    # Verify created event code_ids
    created_code_ids = {c[0][1]["code_id"] for c in created_events}
    assert created_code_ids == expected_created

    # Verify expired event code_ids
    expired_code_ids = {c[0][1]["code_id"] for c in expired_events}
    assert expired_code_ids == expected_expired

    # Verify used event code_ids
    used_code_ids = {c[0][1]["code_id"] for c in used_events}
    assert used_code_ids == expected_used

    # Verify no other code events (only vehicle events allowed beyond these)
    code_event_types = {EVENT_CODE_CREATED, EVENT_CODE_EXPIRED, EVENT_CODE_USED}
    vehicle_event_types = {EVENT_VEHICLE_ADDED, EVENT_VEHICLE_REMOVED}
    all_event_types = {c[0][0] for c in calls}
    unexpected = all_event_types - code_event_types - vehicle_event_types
    assert not unexpected, f"Unexpected event types fired: {unexpected}"


# ---------------------------------------------------------------------------
# Property 2: Vehicle diff engine produces correct events
# ---------------------------------------------------------------------------


@given(
    old_vehicle_list=st.lists(vehicles(), max_size=15),
    new_vehicle_list=st.lists(vehicles(), max_size=15),
)
@settings(max_examples=100)
def test_vehicle_diff_produces_correct_events(
    old_vehicle_list: list[Vehicle],
    new_vehicle_list: list[Vehicle],
) -> None:
    """Property 2: Vehicle diff engine produces correct events.

    **Validates: Requirements 5.4, 5.5**

    For any two vehicle snapshots, the diff engine fires:
    - exactly one axuus_vehicle_added per new vehicle_id
    - exactly one axuus_vehicle_removed per removed vehicle_id
    - no other vehicle events
    """
    # Key by vehicle_id so dict key matches the object's identity
    old_vehicles = {v.vehicle_id: v for v in old_vehicle_list}
    new_vehicles = {v.vehicle_id: v for v in new_vehicle_list}

    coordinator, hass = _make_coordinator()

    # Split vehicles into resident/guest based on their type for realistic data,
    # but the diff engine combines them via all_vehicles anyway.
    # For simplicity, put all in resident_vehicles.
    old_data = _make_data(resident_vehicles=old_vehicles)
    new_data = _make_data(resident_vehicles=new_vehicles)

    coordinator._diff_and_fire_events(old_data, new_data)

    # Collect all fired events
    calls = hass.bus.async_fire.call_args_list
    added_events = [c for c in calls if c[0][0] == EVENT_VEHICLE_ADDED]
    removed_events = [c for c in calls if c[0][0] == EVENT_VEHICLE_REMOVED]

    # Compute expected sets
    old_ids = set(old_vehicles)
    new_ids = set(new_vehicles)

    expected_added = new_ids - old_ids
    expected_removed = old_ids - new_ids

    # Verify counts
    assert len(added_events) == len(expected_added), (
        f"Expected {len(expected_added)} added events, got {len(added_events)}"
    )
    assert len(removed_events) == len(expected_removed), (
        f"Expected {len(expected_removed)} removed events, got {len(removed_events)}"
    )

    # Verify added event vehicle_ids
    added_vehicle_ids = {c[0][1]["vehicle_id"] for c in added_events}
    assert added_vehicle_ids == expected_added

    # Verify removed event vehicle_ids
    removed_vehicle_ids = {c[0][1]["vehicle_id"] for c in removed_events}
    assert removed_vehicle_ids == expected_removed

    # Verify no other vehicle events
    vehicle_event_types = {EVENT_VEHICLE_ADDED, EVENT_VEHICLE_REMOVED}
    code_event_types = {EVENT_CODE_CREATED, EVENT_CODE_EXPIRED, EVENT_CODE_USED}
    all_event_types = {c[0][0] for c in calls}
    unexpected = all_event_types - vehicle_event_types - code_event_types
    assert not unexpected, f"Unexpected event types fired: {unexpected}"
