"""Config flow for the Axuus integration.

Supports two authentication methods:
  1. Email + password (primary)
  2. Paste .ASPXAUTH cookie (fallback when captcha is enforced)

Options flow allows configuring the poll interval (30–600 seconds).
Reauth flow handles persistent authentication failures.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    OptionsFlow,
)
from homeassistant.data_entry_flow import FlowResult
from yarl import URL

from .api.client import AxuusClient
from .api.exceptions import AxuusAuthError, AxuusCaptchaRequired
from .const import (
    AUTH_METHOD_COOKIE,
    AUTH_METHOD_CREDENTIALS,
    CONF_ASPXAUTH,
    CONF_AUTH_METHOD,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_POLL_INTERVAL,
    COOKIE_USER,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

CREDENTIALS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

COOKIE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ASPXAUTH): str,
    }
)


class AxuusConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Axuus."""

    VERSION = 1

    _reauth_entry: ConfigEntry | None = None

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> AxuusOptionsFlow:
        """Return the options flow handler."""
        return AxuusOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Present the auth method choice (credentials vs paste-cookie)."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["credentials", "cookie"],
        )

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle email + password authentication."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]

            session = aiohttp.ClientSession()
            try:
                client = AxuusClient(session, email=email, password=password)
                await client.login()
                await client.list_codes()
            except AxuusCaptchaRequired:
                errors["base"] = "captcha_required"
            except AxuusAuthError:
                errors["base"] = "invalid_auth"
            except (aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            else:
                # Validation succeeded
                await self.async_set_unique_id(email)
                self._abort_if_unique_id_configured()

                if self._reauth_entry is not None:
                    self.hass.config_entries.async_update_entry(
                        self._reauth_entry,
                        data={
                            CONF_AUTH_METHOD: AUTH_METHOD_CREDENTIALS,
                            CONF_EMAIL: email,
                            CONF_PASSWORD: password,
                        },
                    )
                    await self.hass.config_entries.async_reload(
                        self._reauth_entry.entry_id
                    )
                    return self.async_abort(reason="reauth_successful")

                return self.async_create_entry(
                    title=email,
                    data={
                        CONF_AUTH_METHOD: AUTH_METHOD_CREDENTIALS,
                        CONF_EMAIL: email,
                        CONF_PASSWORD: password,
                    },
                )
            finally:
                await session.close()

        return self.async_show_form(
            step_id="credentials",
            data_schema=CREDENTIALS_SCHEMA,
            errors=errors,
        )

    async def async_step_cookie(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle paste-.ASPXAUTH cookie authentication."""
        errors: dict[str, str] = {}

        if user_input is not None:
            aspxauth = user_input[CONF_ASPXAUTH]

            session = aiohttp.ClientSession()
            try:
                # Seed the cookie jar with the provided .ASPXAUTH value
                session.cookie_jar.update_cookies(
                    {".ASPXAUTH": aspxauth},
                    response_url=URL("https://www.axuus.com/Residents/"),
                )
                client = AxuusClient(session, aspxauth_cookie=aspxauth)
                await client.list_codes()
            except AxuusAuthError:
                errors["base"] = "invalid_cookie"
            except (aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            else:
                # Validation succeeded
                await self.async_set_unique_id(COOKIE_USER)
                self._abort_if_unique_id_configured()

                if self._reauth_entry is not None:
                    self.hass.config_entries.async_update_entry(
                        self._reauth_entry,
                        data={
                            CONF_AUTH_METHOD: AUTH_METHOD_COOKIE,
                            CONF_ASPXAUTH: aspxauth,
                        },
                    )
                    await self.hass.config_entries.async_reload(
                        self._reauth_entry.entry_id
                    )
                    return self.async_abort(reason="reauth_successful")

                return self.async_create_entry(
                    title="Axuus (cookie)",
                    data={
                        CONF_AUTH_METHOD: AUTH_METHOD_COOKIE,
                        CONF_ASPXAUTH: aspxauth,
                    },
                )
            finally:
                await session.close()

        return self.async_show_form(
            step_id="cookie",
            data_schema=COOKIE_SCHEMA,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Reauth flow
    # ------------------------------------------------------------------

    async def async_step_reauth(
        self, entry_data: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reauth trigger from the coordinator."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Present the auth form for re-authentication.

        Delegates to the appropriate auth step based on user input or
        shows the menu to let the user choose.
        """
        # If user_input is None, show the auth method menu
        return self.async_show_menu(
            step_id="reauth_confirm",
            menu_options=["credentials", "cookie"],
        )


class AxuusOptionsFlow(OptionsFlow):
    """Handle options for the Axuus integration."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the poll interval option."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self._config_entry.options.get(
            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_POLL_INTERVAL, default=current_interval
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL),
                    ),
                }
            ),
        )
