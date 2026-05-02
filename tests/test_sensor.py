"""Unit tests for the Axuus sensor platform.

Tests cover:
- Per-code sensor: native_value, extra_state_attributes, unique_id, available
- Aggregate count sensors: active codes, resident vehicles, guest vehicles

Requirements: 6.1–6.5, 7.1–7.3
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.axuus.api.models import AccessCode, Vehicle, VehicleType
from custom_components.axuus.coordinator import AxuusCoordinator, AxuusData
from custom_components.axuus.sensor import AxuusCodeSensor, AxuusCountSensor


# ---------------------------------------------------------------------------
# Sample data (same as test_coordinator.py)
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


def _make_mock_coordinator(data: AxuusData) -> MagicMock:
    """Create a mock coordinator with the given data."""
    coordinator = MagicMock(spec=AxuusCoordinator)
    coordinator.data = data
    coordinator.last_update_success = True
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


def _make_data(
    codes: dict[int, AccessCode] | None = None,
    resident_vehicles: dict[str, Vehicle] | None = None,
    guest_vehicles: dict[str, Vehicle] | None = None,
    vehicle_auth: dict[str, bool] | None = None,
) -> AxuusData:
    """Build an AxuusData snapshot with sensible defaults."""
    return AxuusData(
        codes=codes or {},
        resident_vehicles=resident_vehicles or {},
        guest_vehicles=guest_vehicles or {},
        vehicle_auth=vehicle_auth or {},
        last_poll_success=True,
    )


# ---------------------------------------------------------------------------
# Per-code sensor tests
# ---------------------------------------------------------------------------


def test_code_sensor_native_value() -> None:
    """native_value is the 6-digit code string."""
    data = _make_data(codes={SAMPLE_CODE.code_id: SAMPLE_CODE})
    coordinator = _make_mock_coordinator(data)
    sensor = AxuusCodeSensor(coordinator, SAMPLE_CODE.code_id)

    assert sensor.native_value == "123456"


def test_code_sensor_attributes() -> None:
    """extra_state_attributes contains all required fields matching AccessCode."""
    data = _make_data(codes={SAMPLE_CODE.code_id: SAMPLE_CODE})
    coordinator = _make_mock_coordinator(data)
    sensor = AxuusCodeSensor(coordinator, SAMPLE_CODE.code_id)

    attrs = sensor.extra_state_attributes
    assert attrs is not None
    assert attrs["code_id"] == 100001
    assert attrs["description"] == "Cleaner Tuesday"
    assert attrs["expires_after"] == "2026-05-08T09:00:00"
    assert attrs["assign_lp"] is False
    assert attrs["date_created"] == "2026-05-01T09:00:00"
    assert attrs["times_used"] == 0
    assert attrs["is_one_time"] is False


def test_code_sensor_attributes_one_time() -> None:
    """extra_state_attributes for a one-time code with no expires_after shows 'one_time'."""
    data = _make_data(codes={SAMPLE_CODE_B.code_id: SAMPLE_CODE_B})
    coordinator = _make_mock_coordinator(data)
    sensor = AxuusCodeSensor(coordinator, SAMPLE_CODE_B.code_id)

    attrs = sensor.extra_state_attributes
    assert attrs is not None
    assert attrs["expires_after"] == "one_time"
    assert attrs["is_one_time"] is True


def test_code_sensor_unique_id() -> None:
    """unique_id format is axuus_{code_id}_code."""
    data = _make_data(codes={SAMPLE_CODE.code_id: SAMPLE_CODE})
    coordinator = _make_mock_coordinator(data)
    sensor = AxuusCodeSensor(coordinator, SAMPLE_CODE.code_id)

    assert sensor.unique_id == "axuus_100001_code"


def test_code_sensor_available_when_present() -> None:
    """available returns True when code_id exists in snapshot."""
    data = _make_data(codes={SAMPLE_CODE.code_id: SAMPLE_CODE})
    coordinator = _make_mock_coordinator(data)
    sensor = AxuusCodeSensor(coordinator, SAMPLE_CODE.code_id)

    assert sensor.available is True


def test_code_sensor_unavailable_when_missing() -> None:
    """available returns False when code disappears from snapshot."""
    data = _make_data(codes={})  # Code not present
    coordinator = _make_mock_coordinator(data)
    sensor = AxuusCodeSensor(coordinator, SAMPLE_CODE.code_id)

    assert sensor.available is False


# ---------------------------------------------------------------------------
# Aggregate count sensor tests
# ---------------------------------------------------------------------------


def test_count_sensor_active_codes() -> None:
    """Returns correct count of codes."""
    data = _make_data(codes={
        SAMPLE_CODE.code_id: SAMPLE_CODE,
        SAMPLE_CODE_B.code_id: SAMPLE_CODE_B,
    })
    coordinator = _make_mock_coordinator(data)
    sensor = AxuusCountSensor(coordinator, "active_codes", "Axuus Active Codes Count", "codes")

    assert sensor.native_value == 2


def test_count_sensor_resident_vehicles() -> None:
    """Returns correct count of resident vehicles."""
    data = _make_data(resident_vehicles={SAMPLE_VEHICLE.vehicle_id: SAMPLE_VEHICLE})
    coordinator = _make_mock_coordinator(data)
    sensor = AxuusCountSensor(
        coordinator, "resident_vehicles", "Axuus Resident Vehicles Count", "resident_vehicles"
    )

    assert sensor.native_value == 1


def test_count_sensor_guest_vehicles() -> None:
    """Returns correct count of guest vehicles."""
    data = _make_data(guest_vehicles={SAMPLE_VEHICLE_B.vehicle_id: SAMPLE_VEHICLE_B})
    coordinator = _make_mock_coordinator(data)
    sensor = AxuusCountSensor(
        coordinator, "guest_vehicles", "Axuus Guest Vehicles Count", "guest_vehicles"
    )

    assert sensor.native_value == 1
