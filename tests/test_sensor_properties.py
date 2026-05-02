"""Property-based tests for the Axuus sensor platform.

# Feature: axuus-ha-integration, Property 3: Code sensor mapping correctness
# Feature: axuus-ha-integration, Property 4: Count sensors reflect collection sizes

Tests verify that sensor entities correctly map AccessCode data and that
count sensors accurately reflect collection sizes for any AxuusData snapshot.

**Validates: Requirements 6.1, 6.2, 6.5, 7.1, 7.2, 7.3**
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from hypothesis import given, settings, strategies as st

from custom_components.axuus.api.models import AccessCode, Vehicle, VehicleType
from custom_components.axuus.coordinator import AxuusCoordinator, AxuusData
from custom_components.axuus.sensor import AxuusCodeSensor, AxuusCountSensor


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


def _make_mock_coordinator(data: AxuusData) -> MagicMock:
    """Create a mock coordinator with the given data."""
    coordinator = MagicMock(spec=AxuusCoordinator)
    coordinator.data = data
    coordinator.last_update_success = True
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


# ---------------------------------------------------------------------------
# Property 3: Code sensor mapping correctness
# ---------------------------------------------------------------------------


@given(code=access_codes())
@settings(max_examples=100)
def test_code_sensor_mapping_correctness(code: AccessCode) -> None:
    """Property 3: Code sensor mapping correctness.

    **Validates: Requirements 6.1, 6.2, 6.5**

    For any AccessCode, the corresponding sensor entity has:
    - native_value equal to the 6-digit code string
    - all required attributes present and matching
    - unique_id equal to axuus_{code_id}_code
    """
    data = AxuusData(
        codes={code.code_id: code},
        resident_vehicles={},
        guest_vehicles={},
        vehicle_auth={},
        last_poll_success=True,
    )
    coordinator = _make_mock_coordinator(data)
    sensor = AxuusCodeSensor(coordinator, code.code_id)

    # native_value equals the code string
    assert sensor.native_value == code.code

    # unique_id follows the format
    assert sensor.unique_id == f"axuus_{code.code_id}_code"

    # extra_state_attributes contains all required fields
    attrs = sensor.extra_state_attributes
    assert attrs is not None
    assert attrs["code_id"] == code.code_id
    assert attrs["description"] == code.description
    assert attrs["assign_lp"] == code.assign_lp
    assert attrs["times_used"] == code.times_used
    assert attrs["is_one_time"] == code.is_one_time

    # Verify expires_after attribute
    if code.is_one_time and code.expires_after is None:
        assert attrs["expires_after"] == "one_time"
    elif code.expires_after is not None:
        assert attrs["expires_after"] == code.expires_after.isoformat()
    else:
        assert attrs["expires_after"] is None

    # Verify date_created attribute
    if code.date_created is not None:
        assert attrs["date_created"] == code.date_created.isoformat()
    else:
        assert attrs["date_created"] is None


# ---------------------------------------------------------------------------
# Property 4: Count sensors reflect collection sizes
# ---------------------------------------------------------------------------


@given(
    codes=st.dictionaries(st.integers(1, 100), access_codes()),
    resident_vehicles=st.dictionaries(
        st.text(
            alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-",
            min_size=5,
            max_size=15,
        ),
        vehicles(),
    ),
    guest_vehicles=st.dictionaries(
        st.text(
            alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-",
            min_size=5,
            max_size=15,
        ),
        vehicles(),
    ),
)
@settings(max_examples=100)
def test_count_sensors_reflect_collection_sizes(
    codes: dict[int, AccessCode],
    resident_vehicles: dict[str, Vehicle],
    guest_vehicles: dict[str, Vehicle],
) -> None:
    """Property 4: Count sensors reflect collection sizes.

    **Validates: Requirements 7.1, 7.2, 7.3**

    For any AxuusData snapshot:
    - active codes count equals len(data.codes)
    - resident vehicles count equals len(data.resident_vehicles)
    - guest vehicles count equals len(data.guest_vehicles)
    """
    data = AxuusData(
        codes=codes,
        resident_vehicles=resident_vehicles,
        guest_vehicles=guest_vehicles,
        vehicle_auth={},
        last_poll_success=True,
    )
    coordinator = _make_mock_coordinator(data)

    # Active codes count sensor
    codes_sensor = AxuusCountSensor(
        coordinator, "active_codes", "Axuus Active Codes Count", "codes"
    )
    assert codes_sensor.native_value == len(codes)

    # Resident vehicles count sensor
    resident_sensor = AxuusCountSensor(
        coordinator,
        "resident_vehicles",
        "Axuus Resident Vehicles Count",
        "resident_vehicles",
    )
    assert resident_sensor.native_value == len(resident_vehicles)

    # Guest vehicles count sensor
    guest_sensor = AxuusCountSensor(
        coordinator,
        "guest_vehicles",
        "Axuus Guest Vehicles Count",
        "guest_vehicles",
    )
    assert guest_sensor.native_value == len(guest_vehicles)
