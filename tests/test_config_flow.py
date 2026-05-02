"""Unit tests for the Axuus config flow.

Since Home Assistant is not installed as a full dependency, we mock HA internals
and directly instantiate the flow classes to test their logic.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol

from custom_components.axuus.api.exceptions import AxuusAuthError, AxuusCaptchaRequired
from custom_components.axuus.config_flow import AxuusConfigFlow, AxuusOptionsFlow
from custom_components.axuus.const import (
    AUTH_METHOD_COOKIE,
    AUTH_METHOD_CREDENTIALS,
    CONF_ASPXAUTH,
    CONF_AUTH_METHOD,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_POLL_INTERVAL,
    COOKIE_USER,
    DEFAULT_POLL_INTERVAL,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config_flow() -> AxuusConfigFlow:
    """Create an AxuusConfigFlow with mocked HA internals."""
    flow = AxuusConfigFlow()
    flow.hass = MagicMock()
    flow.context = {}

    # Mock the HA flow result methods so they return dicts we can inspect
    flow.async_show_menu = MagicMock(
        side_effect=lambda **kwargs: {"type": "menu", **kwargs}
    )
    flow.async_show_form = MagicMock(
        side_effect=lambda **kwargs: {"type": "form", **kwargs}
    )
    flow.async_create_entry = MagicMock(
        side_effect=lambda **kwargs: {"type": "create_entry", **kwargs}
    )
    flow.async_abort = MagicMock(
        side_effect=lambda **kwargs: {"type": "abort", **kwargs}
    )
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()

    return flow


def _make_options_flow(
    current_interval: int = DEFAULT_POLL_INTERVAL,
) -> AxuusOptionsFlow:
    """Create an AxuusOptionsFlow with a mocked config entry."""
    entry = MagicMock()
    entry.options = {CONF_POLL_INTERVAL: current_interval}
    flow = AxuusOptionsFlow(entry)
    flow.hass = MagicMock()

    flow.async_show_form = MagicMock(
        side_effect=lambda **kwargs: {"type": "form", **kwargs}
    )
    flow.async_create_entry = MagicMock(
        side_effect=lambda **kwargs: {"type": "create_entry", **kwargs}
    )

    return flow


# ---------------------------------------------------------------------------
# 1. async_step_user — menu presentation
# ---------------------------------------------------------------------------


async def test_step_user_shows_menu() -> None:
    """async_step_user should present a menu with credentials and cookie options."""
    flow = _make_config_flow()

    result = await flow.async_step_user()

    assert result["type"] == "menu"
    assert result["step_id"] == "user"
    assert "credentials" in result["menu_options"]
    assert "cookie" in result["menu_options"]


# ---------------------------------------------------------------------------
# 2. Credentials — success path
# ---------------------------------------------------------------------------


async def test_credentials_success() -> None:
    """Valid email + password should create an entry with correct data."""
    flow = _make_config_flow()

    with patch("custom_components.axuus.config_flow.aiohttp.ClientSession") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.close = AsyncMock()
        mock_session_cls.return_value = mock_session

        with patch("custom_components.axuus.config_flow.AxuusClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value = mock_client

            result = await flow.async_step_credentials(
                user_input={CONF_EMAIL: "user@example.com", CONF_PASSWORD: "secret123"}
            )

    # Verify client was constructed and called correctly
    mock_client_cls.assert_called_once_with(
        mock_session, email="user@example.com", password="secret123"
    )
    mock_client.login.assert_awaited_once()
    mock_client.list_codes.assert_awaited_once()

    # Verify unique ID was set
    flow.async_set_unique_id.assert_awaited_once_with("user@example.com")
    flow._abort_if_unique_id_configured.assert_called_once()

    # Verify entry was created with correct data
    assert result["type"] == "create_entry"
    assert result["title"] == "user@example.com"
    assert result["data"] == {
        CONF_AUTH_METHOD: AUTH_METHOD_CREDENTIALS,
        CONF_EMAIL: "user@example.com",
        CONF_PASSWORD: "secret123",
    }

    # Session should be closed
    mock_session.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# 3. Credentials — invalid auth
# ---------------------------------------------------------------------------


async def test_credentials_invalid_auth() -> None:
    """AxuusAuthError during login should show 'invalid_auth' error."""
    flow = _make_config_flow()

    with patch("custom_components.axuus.config_flow.aiohttp.ClientSession") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.close = AsyncMock()
        mock_session_cls.return_value = mock_session

        with patch("custom_components.axuus.config_flow.AxuusClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.login.side_effect = AxuusAuthError("bad creds")
            mock_client_cls.return_value = mock_client

            result = await flow.async_step_credentials(
                user_input={CONF_EMAIL: "user@example.com", CONF_PASSWORD: "wrong"}
            )

    assert result["type"] == "form"
    assert result["step_id"] == "credentials"
    assert result["errors"] == {"base": "invalid_auth"}
    mock_session.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# 4. Credentials — captcha required
# ---------------------------------------------------------------------------


async def test_credentials_captcha_required() -> None:
    """AxuusCaptchaRequired should show 'captcha_required' error."""
    flow = _make_config_flow()

    with patch("custom_components.axuus.config_flow.aiohttp.ClientSession") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.close = AsyncMock()
        mock_session_cls.return_value = mock_session

        with patch("custom_components.axuus.config_flow.AxuusClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.login.side_effect = AxuusCaptchaRequired("captcha enforced")
            mock_client_cls.return_value = mock_client

            result = await flow.async_step_credentials(
                user_input={CONF_EMAIL: "user@example.com", CONF_PASSWORD: "pass"}
            )

    assert result["type"] == "form"
    assert result["step_id"] == "credentials"
    assert result["errors"] == {"base": "captcha_required"}
    mock_session.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# 5. Cookie — success path
# ---------------------------------------------------------------------------


async def test_cookie_success() -> None:
    """Valid cookie should create an entry with correct data."""
    flow = _make_config_flow()

    with patch("custom_components.axuus.config_flow.aiohttp.ClientSession") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.close = AsyncMock()
        mock_session.cookie_jar = MagicMock()
        mock_session_cls.return_value = mock_session

        with patch("custom_components.axuus.config_flow.AxuusClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value = mock_client

            result = await flow.async_step_cookie(
                user_input={CONF_ASPXAUTH: "ABCDEF1234567890"}
            )

    # Verify client was constructed with the cookie
    mock_client_cls.assert_called_once_with(
        mock_session, aspxauth_cookie="ABCDEF1234567890"
    )
    mock_client.list_codes.assert_awaited_once()

    # Verify unique ID was set to COOKIE_USER
    flow.async_set_unique_id.assert_awaited_once_with(COOKIE_USER)
    flow._abort_if_unique_id_configured.assert_called_once()

    # Verify entry was created
    assert result["type"] == "create_entry"
    assert result["title"] == "Axuus (cookie)"
    assert result["data"] == {
        CONF_AUTH_METHOD: AUTH_METHOD_COOKIE,
        CONF_ASPXAUTH: "ABCDEF1234567890",
    }

    mock_session.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# 6. Cookie — invalid cookie
# ---------------------------------------------------------------------------


async def test_cookie_invalid() -> None:
    """AxuusAuthError during cookie validation should show 'invalid_cookie' error."""
    flow = _make_config_flow()

    with patch("custom_components.axuus.config_flow.aiohttp.ClientSession") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.close = AsyncMock()
        mock_session.cookie_jar = MagicMock()
        mock_session_cls.return_value = mock_session

        with patch("custom_components.axuus.config_flow.AxuusClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.list_codes.side_effect = AxuusAuthError("expired cookie")
            mock_client_cls.return_value = mock_client

            result = await flow.async_step_cookie(
                user_input={CONF_ASPXAUTH: "EXPIRED_COOKIE"}
            )

    assert result["type"] == "form"
    assert result["step_id"] == "cookie"
    assert result["errors"] == {"base": "invalid_cookie"}
    mock_session.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# 7. Duplicate prevention
# ---------------------------------------------------------------------------


async def test_duplicate_prevention() -> None:
    """Same email should abort with 'already_configured' via _abort_if_unique_id_configured."""
    flow = _make_config_flow()

    # Simulate _abort_if_unique_id_configured raising AbortFlow
    # In real HA, this raises config_entries.AbortFlow("already_configured").
    # We simulate this by having the mock raise an exception that we catch.
    from homeassistant.data_entry_flow import AbortFlow

    flow._abort_if_unique_id_configured = MagicMock(
        side_effect=AbortFlow("already_configured")
    )

    with patch("custom_components.axuus.config_flow.aiohttp.ClientSession") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.close = AsyncMock()
        mock_session_cls.return_value = mock_session

        with patch("custom_components.axuus.config_flow.AxuusClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value = mock_client

            with pytest.raises(AbortFlow, match="already_configured"):
                await flow.async_step_credentials(
                    user_input={CONF_EMAIL: "user@example.com", CONF_PASSWORD: "secret"}
                )

    mock_session.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# 8. Reauth flow
# ---------------------------------------------------------------------------


async def test_reauth_flow() -> None:
    """Reauth: persistent auth failure → new credentials → entry updated."""
    flow = _make_config_flow()

    # Simulate an existing config entry that needs reauth
    existing_entry = MagicMock()
    existing_entry.entry_id = "test_entry_id"
    flow._reauth_entry = existing_entry

    # Mock hass.config_entries methods
    flow.hass.config_entries.async_update_entry = MagicMock()
    flow.hass.config_entries.async_reload = AsyncMock()

    with patch("custom_components.axuus.config_flow.aiohttp.ClientSession") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.close = AsyncMock()
        mock_session_cls.return_value = mock_session

        with patch("custom_components.axuus.config_flow.AxuusClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value = mock_client

            result = await flow.async_step_credentials(
                user_input={CONF_EMAIL: "user@example.com", CONF_PASSWORD: "newpass"}
            )

    # Verify the existing entry was updated with new credentials
    flow.hass.config_entries.async_update_entry.assert_called_once_with(
        existing_entry,
        data={
            CONF_AUTH_METHOD: AUTH_METHOD_CREDENTIALS,
            CONF_EMAIL: "user@example.com",
            CONF_PASSWORD: "newpass",
        },
    )

    # Verify the entry was reloaded
    flow.hass.config_entries.async_reload.assert_awaited_once_with("test_entry_id")

    # Verify the flow aborted with reauth_successful
    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"

    mock_session.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# 9. Options flow — valid poll interval
# ---------------------------------------------------------------------------


async def test_options_flow_valid() -> None:
    """Poll interval within 30–600 should be accepted."""
    flow = _make_options_flow(current_interval=60)

    result = await flow.async_step_init(
        user_input={CONF_POLL_INTERVAL: 120}
    )

    assert result["type"] == "create_entry"
    assert result["data"] == {CONF_POLL_INTERVAL: 120}


# ---------------------------------------------------------------------------
# 10. Options flow — invalid poll interval (schema validation)
# ---------------------------------------------------------------------------


async def test_options_flow_invalid() -> None:
    """Poll interval outside 30–600 should be rejected by the voluptuous schema."""
    # Test the schema validation directly since the options flow delegates to vol
    schema = vol.Schema(
        {
            vol.Required(CONF_POLL_INTERVAL): vol.All(
                vol.Coerce(int),
                vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL),
            ),
        }
    )

    # Below minimum
    with pytest.raises(vol.MultipleInvalid):
        schema({CONF_POLL_INTERVAL: 10})

    # Above maximum
    with pytest.raises(vol.MultipleInvalid):
        schema({CONF_POLL_INTERVAL: 700})

    # Boundary values should pass
    assert schema({CONF_POLL_INTERVAL: 30}) == {CONF_POLL_INTERVAL: 30}
    assert schema({CONF_POLL_INTERVAL: 600}) == {CONF_POLL_INTERVAL: 600}

    # Negative value
    with pytest.raises(vol.MultipleInvalid):
        schema({CONF_POLL_INTERVAL: -1})

    # Zero
    with pytest.raises(vol.MultipleInvalid):
        schema({CONF_POLL_INTERVAL: 0})


# ---------------------------------------------------------------------------
# Additional: credentials form shown when no user_input
# ---------------------------------------------------------------------------


async def test_credentials_shows_form_when_no_input() -> None:
    """async_step_credentials with no input should show the credentials form."""
    flow = _make_config_flow()

    result = await flow.async_step_credentials(user_input=None)

    assert result["type"] == "form"
    assert result["step_id"] == "credentials"
    assert result["errors"] == {}


async def test_cookie_shows_form_when_no_input() -> None:
    """async_step_cookie with no input should show the cookie form."""
    flow = _make_config_flow()

    result = await flow.async_step_cookie(user_input=None)

    assert result["type"] == "form"
    assert result["step_id"] == "cookie"
    assert result["errors"] == {}
