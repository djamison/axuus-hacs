"""Unit tests for the Axuus integration lifecycle (__init__.py).

Tests cover:
- async_setup_entry: creates session, client, coordinator, forwards platforms, registers services
- async_setup_entry: cookie auth path works correctly
- async_unload_entry: unloads platforms, closes session, cleans up hass.data
- _async_update_options: options update changes coordinator.update_interval

Requirements: 14.1–14.4
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.axuus import async_setup_entry, async_unload_entry, _async_update_options
from custom_components.axuus.const import (
    AUTH_METHOD_COOKIE,
    AUTH_METHOD_CREDENTIALS,
    CONF_ASPXAUTH,
    CONF_AUTH_METHOD,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    PLATFORMS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    auth_method: str = AUTH_METHOD_CREDENTIALS,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
) -> MagicMock:
    """Create a mock config entry."""
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.async_on_unload = MagicMock()

    if auth_method == AUTH_METHOD_CREDENTIALS:
        entry.data = {
            CONF_AUTH_METHOD: AUTH_METHOD_CREDENTIALS,
            CONF_EMAIL: "user@example.com",
            CONF_PASSWORD: "secret123",
        }
    else:
        entry.data = {
            CONF_AUTH_METHOD: AUTH_METHOD_COOKIE,
            CONF_ASPXAUTH: "ABCDEF1234567890",
        }

    entry.options = {CONF_POLL_INTERVAL: poll_interval}
    entry.add_update_listener = MagicMock(return_value=MagicMock())
    return entry


def _make_hass(has_service: bool = False) -> MagicMock:
    """Create a mock hass object."""
    hass = MagicMock()
    hass.data = {}
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.services.has_service = MagicMock(return_value=has_service)
    hass.services.async_register = MagicMock()
    hass.services.async_remove = MagicMock()
    return hass


# ---------------------------------------------------------------------------
# 1. async_setup_entry — credentials auth
# ---------------------------------------------------------------------------


async def test_setup_entry_credentials() -> None:
    """Setup with credentials creates session, client, coordinator, forwards platforms, registers services."""
    hass = _make_hass()
    entry = _make_entry(auth_method=AUTH_METHOD_CREDENTIALS)

    mock_session = MagicMock()
    mock_session.close = AsyncMock()

    mock_client = AsyncMock()
    mock_coordinator = MagicMock()
    mock_coordinator.async_config_entry_first_refresh = AsyncMock()
    mock_coordinator.update_interval = timedelta(seconds=DEFAULT_POLL_INTERVAL)

    with (
        patch("custom_components.axuus.aiohttp.ClientSession", return_value=mock_session),
        patch("custom_components.axuus.AxuusClient", return_value=mock_client) as mock_client_cls,
        patch("custom_components.axuus.AxuusCoordinator", return_value=mock_coordinator) as mock_coord_cls,
    ):
        result = await async_setup_entry(hass, entry)

    assert result is True

    # Client created with session, email, password
    mock_client_cls.assert_called_once_with(
        mock_session,
        email="user@example.com",
        password="secret123",
    )

    # Login called for credentials auth
    mock_client.login.assert_awaited_once()

    # Coordinator created with correct interval
    mock_coord_cls.assert_called_once_with(
        hass,
        mock_client,
        update_interval=timedelta(seconds=DEFAULT_POLL_INTERVAL),
    )

    # First refresh called
    mock_coordinator.async_config_entry_first_refresh.assert_awaited_once()

    # Data stored in hass.data
    assert DOMAIN in hass.data
    assert entry.entry_id in hass.data[DOMAIN]
    stored = hass.data[DOMAIN][entry.entry_id]
    assert stored["client"] is mock_client
    assert stored["coordinator"] is mock_coordinator
    assert stored["session"] is mock_session

    # Platforms forwarded
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry, PLATFORMS
    )

    # Services registered (since has_service returns False)
    assert hass.services.async_register.call_count == 6  # 6 services


# ---------------------------------------------------------------------------
# 2. async_setup_entry — cookie auth
# ---------------------------------------------------------------------------


async def test_setup_entry_cookie() -> None:
    """Setup with cookie auth creates client with aspxauth_cookie, does NOT call login()."""
    hass = _make_hass()
    entry = _make_entry(auth_method=AUTH_METHOD_COOKIE)

    mock_session = MagicMock()
    mock_session.close = AsyncMock()

    mock_client = AsyncMock()
    mock_coordinator = MagicMock()
    mock_coordinator.async_config_entry_first_refresh = AsyncMock()
    mock_coordinator.update_interval = timedelta(seconds=DEFAULT_POLL_INTERVAL)

    with (
        patch("custom_components.axuus.aiohttp.ClientSession", return_value=mock_session),
        patch("custom_components.axuus.AxuusClient", return_value=mock_client) as mock_client_cls,
        patch("custom_components.axuus.AxuusCoordinator", return_value=mock_coordinator),
    ):
        result = await async_setup_entry(hass, entry)

    assert result is True

    # Client created with session and aspxauth_cookie
    mock_client_cls.assert_called_once_with(
        mock_session,
        aspxauth_cookie="ABCDEF1234567890",
    )

    # Login NOT called for cookie auth
    mock_client.login.assert_not_awaited()


# ---------------------------------------------------------------------------
# 3. async_unload_entry
# ---------------------------------------------------------------------------


async def test_unload_entry() -> None:
    """Unload unloads platforms, closes session, cleans up hass.data."""
    hass = _make_hass()
    entry = _make_entry()

    mock_session = MagicMock()
    mock_session.close = AsyncMock()

    # Pre-populate hass.data as if setup had run
    hass.data = {
        DOMAIN: {
            entry.entry_id: {
                "client": AsyncMock(),
                "coordinator": MagicMock(),
                "session": mock_session,
            }
        }
    }

    result = await async_unload_entry(hass, entry)

    assert result is True

    # Platforms unloaded
    hass.config_entries.async_unload_platforms.assert_awaited_once_with(
        entry, PLATFORMS
    )

    # Session closed
    mock_session.close.assert_awaited_once()

    # hass.data cleaned up — entry removed and DOMAIN key removed (last entry)
    assert DOMAIN not in hass.data


async def test_unload_entry_keeps_domain_when_other_entries_exist() -> None:
    """Unload removes only this entry; DOMAIN key remains if other entries exist."""
    hass = _make_hass()
    entry = _make_entry()

    mock_session = MagicMock()
    mock_session.close = AsyncMock()

    # Two entries in hass.data
    hass.data = {
        DOMAIN: {
            entry.entry_id: {
                "client": AsyncMock(),
                "coordinator": MagicMock(),
                "session": mock_session,
            },
            "other_entry_id": {
                "client": AsyncMock(),
                "coordinator": MagicMock(),
                "session": MagicMock(),
            },
        }
    }

    result = await async_unload_entry(hass, entry)

    assert result is True

    # This entry removed, but DOMAIN key and other entry remain
    assert DOMAIN in hass.data
    assert entry.entry_id not in hass.data[DOMAIN]
    assert "other_entry_id" in hass.data[DOMAIN]

    # Services NOT unregistered (other entry still active)
    hass.services.async_remove.assert_not_called()


# ---------------------------------------------------------------------------
# 4. _async_update_options
# ---------------------------------------------------------------------------


async def test_update_options() -> None:
    """Options update changes coordinator.update_interval."""
    hass = MagicMock()
    entry = _make_entry(poll_interval=120)

    mock_coordinator = MagicMock()
    mock_coordinator.update_interval = timedelta(seconds=DEFAULT_POLL_INTERVAL)

    hass.data = {
        DOMAIN: {
            entry.entry_id: {
                "coordinator": mock_coordinator,
                "client": AsyncMock(),
                "session": MagicMock(),
            }
        }
    }

    await _async_update_options(hass, entry)

    assert mock_coordinator.update_interval == timedelta(seconds=120)
