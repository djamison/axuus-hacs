"""Unit tests for the Axuus button platform.

Tests cover:
- Refresh button: async_press triggers coordinator refresh, unique_id

Requirements: 9.1, 9.2
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.axuus.coordinator import AxuusCoordinator, AxuusData
from custom_components.axuus.button import AxuusRefreshButton


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_coordinator() -> MagicMock:
    """Create a mock coordinator."""
    coordinator = MagicMock(spec=AxuusCoordinator)
    coordinator.data = AxuusData(
        codes={},
        resident_vehicles={},
        guest_vehicles={},
        vehicle_auth={},
        last_poll_success=True,
    )
    coordinator.last_update_success = True
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_button_press_triggers_refresh() -> None:
    """async_press calls coordinator.async_request_refresh()."""
    coordinator = _make_mock_coordinator()
    button = AxuusRefreshButton(coordinator)

    await button.async_press()

    coordinator.async_request_refresh.assert_awaited_once()


def test_button_unique_id() -> None:
    """unique_id is axuus_refresh."""
    coordinator = _make_mock_coordinator()
    button = AxuusRefreshButton(coordinator)

    assert button.unique_id == "axuus_refresh"
