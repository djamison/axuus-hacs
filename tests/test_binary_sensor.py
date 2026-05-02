"""Unit tests for the Axuus binary sensor platform.

Tests cover:
- Connection sensor: is_on reflects last_update_success, device_class

Requirements: 10.1–10.3
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass

from custom_components.axuus.coordinator import AxuusCoordinator, AxuusData
from custom_components.axuus.binary_sensor import AxuusConnectionSensor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_coordinator(last_update_success: bool = True) -> MagicMock:
    """Create a mock coordinator with the given success state."""
    coordinator = MagicMock(spec=AxuusCoordinator)
    coordinator.data = AxuusData(
        codes={},
        resident_vehicles={},
        guest_vehicles={},
        vehicle_auth={},
        last_poll_success=True,
    )
    coordinator.last_update_success = last_update_success
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_connection_sensor_on_when_success() -> None:
    """is_on returns True when last_update_success is True."""
    coordinator = _make_mock_coordinator(last_update_success=True)
    sensor = AxuusConnectionSensor(coordinator)

    assert sensor.is_on is True


def test_connection_sensor_off_when_failure() -> None:
    """is_on returns False when last_update_success is False."""
    coordinator = _make_mock_coordinator(last_update_success=False)
    sensor = AxuusConnectionSensor(coordinator)

    assert sensor.is_on is False


def test_connection_sensor_device_class() -> None:
    """device_class is BinarySensorDeviceClass.CONNECTIVITY."""
    coordinator = _make_mock_coordinator()
    sensor = AxuusConnectionSensor(coordinator)

    assert sensor.device_class == BinarySensorDeviceClass.CONNECTIVITY
