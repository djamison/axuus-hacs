"""Axuus integration for Home Assistant.

Manages the lifecycle of the Axuus API client, data coordinator, and
entity platforms. Registers services for code/vehicle management.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .api.client import AxuusClient
from .const import (
    AUTH_METHOD_CREDENTIALS,
    CONF_ASPXAUTH,
    CONF_AUTH_METHOD,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    EXPIRES_AFTER_VALUES,
    PLATFORMS,
)
from .coordinator import AxuusCoordinator

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Voluptuous schemas for service call validation
# ---------------------------------------------------------------------------

SERVICE_CREATE_CODE_SCHEMA = vol.Schema(
    {
        vol.Required("description"): str,
        vol.Required("expires_after"): vol.In(EXPIRES_AFTER_VALUES),
        vol.Optional("assign_lp", default=False): bool,
        vol.Optional("email_to", default=""): str,
        vol.Optional("sms_to", default=""): str,
    }
)

SERVICE_UPDATE_CODE_SCHEMA = vol.Schema(
    {
        vol.Required("code_id"): vol.Coerce(int),
        vol.Optional("description"): str,
        vol.Optional("assign_lp"): bool,
        vol.Optional("email_to"): str,
        vol.Optional("sms_to"): str,
    }
)

SERVICE_DELETE_CODE_SCHEMA = vol.Schema(
    {
        vol.Required("code_id"): vol.Coerce(int),
    }
)

SERVICE_AUTHORIZE_VEHICLE_SCHEMA = vol.Schema(
    {
        vol.Required("vehicle_id"): str,
        vol.Required("authorized"): bool,
    }
)

SERVICE_REMOVE_VEHICLE_SCHEMA = vol.Schema(
    {
        vol.Required("vehicle_id"): str,
        vol.Required("confirm"): bool,
    }
)

SERVICE_REFRESH_SCHEMA = vol.Schema({})


# ---------------------------------------------------------------------------
# Helpers to get the first coordinator/client from hass.data
# ---------------------------------------------------------------------------


def _get_first_entry_data(hass: HomeAssistant) -> dict:
    """Return the data dict for the first config entry."""
    entries = hass.data.get(DOMAIN, {})
    if not entries:
        raise HomeAssistantError("No Axuus integration entries configured")
    return next(iter(entries.values()))


def _get_client(hass: HomeAssistant) -> AxuusClient:
    """Return the AxuusClient from the first config entry."""
    return _get_first_entry_data(hass)["client"]


def _get_coordinator(hass: HomeAssistant) -> AxuusCoordinator:
    """Return the AxuusCoordinator from the first config entry."""
    return _get_first_entry_data(hass)["coordinator"]


# ---------------------------------------------------------------------------
# Service handlers
# ---------------------------------------------------------------------------


async def _async_handle_create_code(call: ServiceCall) -> None:
    """Handle axuus.create_code service call."""
    hass = call.hass
    client = _get_client(hass)
    coordinator = _get_coordinator(hass)

    description = call.data["description"]
    expires_after = call.data["expires_after"]
    assign_lp = call.data.get("assign_lp", False)
    email_to = call.data.get("email_to", "")
    sms_to = call.data.get("sms_to", "")

    # Validate expires_after against allowed values
    if expires_after not in EXPIRES_AFTER_VALUES:
        raise ServiceValidationError(
            f"Invalid expires_after value: {expires_after}. "
            f"Must be one of: {', '.join(EXPIRES_AFTER_VALUES)}"
        )

    try:
        code = await client.create_code(
            description,
            expires_after,
            assign_lp=assign_lp,
            email_to=email_to,
            sms_to=sms_to,
        )
    except Exception as err:
        raise HomeAssistantError(f"Failed to create access code: {err}") from err

    # Trigger coordinator refresh to pick up the new code
    await coordinator.async_request_refresh()

    # Store the generated code in the service response data
    call.hass.bus.async_fire(
        f"{DOMAIN}_code_created_response",
        {"code": code, "description": description},
    )


async def _async_handle_update_code(call: ServiceCall) -> None:
    """Handle axuus.update_code service call."""
    hass = call.hass
    client = _get_client(hass)
    coordinator = _get_coordinator(hass)

    code_id = call.data["code_id"]
    description = call.data.get("description", "")
    assign_lp = call.data.get("assign_lp", False)
    email_to = call.data.get("email_to", "")
    sms_to = call.data.get("sms_to", "")

    try:
        await client.update_code(
            code_id,
            description=description,
            assign_lp=assign_lp,
            email_to=email_to,
            sms_to=sms_to,
        )
    except Exception as err:
        raise HomeAssistantError(f"Failed to update access code: {err}") from err

    await coordinator.async_request_refresh()


async def _async_handle_delete_code(call: ServiceCall) -> None:
    """Handle axuus.delete_code service call."""
    hass = call.hass
    client = _get_client(hass)
    coordinator = _get_coordinator(hass)

    code_id = call.data["code_id"]

    try:
        await client.delete_code(code_id)
    except Exception as err:
        raise HomeAssistantError(f"Failed to delete access code: {err}") from err

    await coordinator.async_request_refresh()


async def _async_handle_authorize_vehicle(call: ServiceCall) -> None:
    """Handle axuus.authorize_vehicle service call.

    Reads the current auth state from coordinator data and only calls the API
    if the desired state differs (idempotent).
    """
    hass = call.hass
    client = _get_client(hass)
    coordinator = _get_coordinator(hass)

    vehicle_id = call.data["vehicle_id"]
    desired_authorized = call.data["authorized"]

    # Read current auth state from coordinator data
    if coordinator.data is None:
        raise HomeAssistantError("Coordinator data not available yet")

    current_auth = coordinator.data.vehicle_auth.get(vehicle_id)
    if current_auth is None:
        raise HomeAssistantError(
            f"Vehicle {vehicle_id} not found in coordinator data"
        )

    # Only call the API if the state actually needs to change
    if current_auth != desired_authorized:
        try:
            await client.authorize_vehicle(
                vehicle_id, currently_authorized=current_auth
            )
        except Exception as err:
            raise HomeAssistantError(
                f"Failed to authorize vehicle: {err}"
            ) from err

        await coordinator.async_request_refresh()


async def _async_handle_remove_vehicle(call: ServiceCall) -> None:
    """Handle axuus.remove_vehicle service call.

    Requires confirm=true to proceed. Rejects with ServiceValidationError if false.
    """
    hass = call.hass
    client = _get_client(hass)
    coordinator = _get_coordinator(hass)

    vehicle_id = call.data["vehicle_id"]
    confirm = call.data["confirm"]

    if not confirm:
        raise ServiceValidationError(
            "You must set confirm to true to remove a vehicle. "
            "This action cannot be undone."
        )

    try:
        await client.inactivate_vehicle(vehicle_id)
    except Exception as err:
        raise HomeAssistantError(
            f"Failed to remove vehicle: {err}"
        ) from err

    await coordinator.async_request_refresh()


async def _async_handle_refresh(call: ServiceCall) -> None:
    """Handle axuus.refresh service call."""
    coordinator = _get_coordinator(call.hass)
    await coordinator.async_request_refresh()


# ---------------------------------------------------------------------------
# Service registration / unregistration
# ---------------------------------------------------------------------------

_SERVICES = {
    "create_code": (_async_handle_create_code, SERVICE_CREATE_CODE_SCHEMA),
    "update_code": (_async_handle_update_code, SERVICE_UPDATE_CODE_SCHEMA),
    "delete_code": (_async_handle_delete_code, SERVICE_DELETE_CODE_SCHEMA),
    "authorize_vehicle": (
        _async_handle_authorize_vehicle,
        SERVICE_AUTHORIZE_VEHICLE_SCHEMA,
    ),
    "remove_vehicle": (_async_handle_remove_vehicle, SERVICE_REMOVE_VEHICLE_SCHEMA),
    "refresh": (_async_handle_refresh, SERVICE_REFRESH_SCHEMA),
}


def _register_services(hass: HomeAssistant) -> None:
    """Register all Axuus services (guarded: only once across entries)."""
    if hass.services.has_service(DOMAIN, "create_code"):
        return  # Already registered

    for service_name, (handler, schema) in _SERVICES.items():
        hass.services.async_register(DOMAIN, service_name, handler, schema=schema)


def _unregister_services(hass: HomeAssistant) -> None:
    """Unregister all Axuus services."""
    for service_name in _SERVICES:
        hass.services.async_remove(DOMAIN, service_name)


# ---------------------------------------------------------------------------
# Integration setup / teardown
# ---------------------------------------------------------------------------


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Axuus from a config entry."""
    # 1. Create aiohttp session
    session = aiohttp.ClientSession()

    # 2. Instantiate client based on auth method
    auth_method = entry.data.get(CONF_AUTH_METHOD)
    if auth_method == AUTH_METHOD_CREDENTIALS:
        client = AxuusClient(
            session,
            email=entry.data[CONF_EMAIL],
            password=entry.data[CONF_PASSWORD],
        )
    else:
        # Cookie-based auth
        client = AxuusClient(
            session,
            aspxauth_cookie=entry.data[CONF_ASPXAUTH],
        )

    # 3. If credentials auth, perform initial login
    if auth_method == AUTH_METHOD_CREDENTIALS:
        await client.login()

    # 4. Create coordinator with poll interval from options (or default)
    poll_interval = entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
    coordinator = AxuusCoordinator(
        hass,
        client,
        update_interval=timedelta(seconds=poll_interval),
        config_entry_id=entry.entry_id,
        account_name=entry.title,
    )

    # 5. First refresh — raises ConfigEntryAuthFailed (→ reauth) or
    #    UpdateFailed (→ ConfigEntryNotReady) automatically
    await coordinator.async_config_entry_first_refresh()

    # 6. Store coordinator, client, session in hass.data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "client": client,
        "session": session,
    }

    # 7. Forward entity platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # 8. Register services (guarded: only register once across multiple entries)
    _register_services(hass)

    # 9. Register options update listener for live poll interval changes
    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    return True


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update — adopt new poll interval without reload."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if data is None:
        return
    coordinator: AxuusCoordinator = data["coordinator"]
    new_interval = entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
    coordinator.update_interval = timedelta(seconds=new_interval)
    _LOGGER.debug("Updated poll interval to %s seconds", new_interval)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an Axuus config entry."""
    # 1. Unload all entity platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)

        # 2. Unregister services if this is the last entry
        if len(hass.data.get(DOMAIN, {})) == 0:
            _unregister_services(hass)

        # 3. Close the aiohttp session
        session: aiohttp.ClientSession = data["session"]
        await session.close()

        # 4. Clean up empty domain dict
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)

    return unload_ok
