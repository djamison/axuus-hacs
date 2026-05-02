"""Data coordinator for the Axuus integration.

Polls access codes, resident vehicles, and guest vehicles each cycle.
Diffs consecutive snapshots to fire HA bus events for automations.
Handles auth recovery (single re-login) and transient error propagation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.client import AxuusClient
from .api.exceptions import AxuusAuthError, AxuusServerError
from .api.models import AccessCode, Vehicle
from .const import (
    DOMAIN,
    EVENT_CODE_CREATED,
    EVENT_CODE_EXPIRED,
    EVENT_CODE_USED,
    EVENT_VEHICLE_ADDED,
    EVENT_VEHICLE_REMOVED,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class AxuusData:
    """Snapshot of all Axuus data from a single poll cycle."""

    codes: dict[int, AccessCode]
    resident_vehicles: dict[str, Vehicle]
    guest_vehicles: dict[str, Vehicle]
    vehicle_auth: dict[str, bool]
    last_poll_success: bool

    @property
    def all_vehicles(self) -> dict[str, Vehicle]:
        """Return combined resident + guest vehicles."""
        return {**self.resident_vehicles, **self.guest_vehicles}


class AxuusCoordinator(DataUpdateCoordinator[AxuusData]):
    """Coordinator that polls the Axuus portal and diffs snapshots."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: AxuusClient,
        update_interval: timedelta,
        *,
        config_entry_id: str = "",
        account_name: str = "Axuus",
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )
        self.client = client
        self._previous_data: AxuusData | None = None
        self.config_entry_id = config_entry_id
        self.account_name = account_name

    async def _async_update_data(self) -> AxuusData:
        """Poll the Axuus API and return a fresh snapshot."""
        try:
            return await self._do_poll()
        except AxuusAuthError:
            # Single re-login attempt
            _LOGGER.debug("Auth error during poll, attempting re-login")
            try:
                await self.client.login()
            except AxuusAuthError as err:
                raise ConfigEntryAuthFailed(
                    "Re-login failed, triggering reauth flow"
                ) from err

            # Retry the full poll after successful re-login
            try:
                return await self._do_poll()
            except AxuusAuthError as err:
                raise ConfigEntryAuthFailed(
                    "Poll failed after re-login, triggering reauth flow"
                ) from err
        except (TimeoutError, AxuusServerError, aiohttp.ClientError) as err:
            raise UpdateFailed(f"Error communicating with Axuus: {err}") from err

    async def _do_poll(self) -> AxuusData:
        """Execute the actual API calls and build the data snapshot.

        Raises AxuusAuthError, AxuusServerError, aiohttp.ClientError,
        or asyncio.TimeoutError — callers handle these.
        """
        codes_list = await self.client.list_codes()
        resident_list = await self.client.list_resident_vehicles()
        guest_list = await self.client.list_guest_vehicles()

        codes = {c.code_id: c for c in codes_list}
        resident_vehicles = {v.vehicle_id: v for v in resident_list}
        guest_vehicles = {v.vehicle_id: v for v in guest_list}

        all_vehicle_ids = set(resident_vehicles) | set(guest_vehicles)

        # Determine which vehicles need a get_vehicle call for auth state
        if self._previous_data is None:
            # First poll: fetch auth for every vehicle
            new_vehicle_ids = all_vehicle_ids
        else:
            previous_vehicle_ids = set(self._previous_data.all_vehicles)
            new_vehicle_ids = all_vehicle_ids - previous_vehicle_ids

        # Start with previous auth state, then update for new vehicles
        vehicle_auth: dict[str, bool] = {}
        if self._previous_data is not None:
            # Carry forward auth state for vehicles that still exist
            for vid in all_vehicle_ids:
                if vid in self._previous_data.vehicle_auth:
                    vehicle_auth[vid] = self._previous_data.vehicle_auth[vid]

        # Fetch auth state for new vehicles
        for vid in new_vehicle_ids:
            try:
                vehicle_detail = await self.client.get_vehicle(vid)
                vehicle_auth[vid] = _parse_ver_auth(vehicle_detail)
            except (AxuusAuthError, AxuusServerError) as err:
                _LOGGER.warning(
                    "Failed to get auth state for vehicle %s: %s", vid, err
                )
                vehicle_auth[vid] = False

        snapshot = AxuusData(
            codes=codes,
            resident_vehicles=resident_vehicles,
            guest_vehicles=guest_vehicles,
            vehicle_auth=vehicle_auth,
            last_poll_success=True,
        )

        # Diff and fire events (skip on first poll — no previous data to compare)
        if self._previous_data is not None:
            self._diff_and_fire_events(self._previous_data, snapshot)

        self._previous_data = snapshot
        return snapshot

    def _diff_and_fire_events(
        self, old: AxuusData, new: AxuusData
    ) -> None:
        """Compare two snapshots and fire HA bus events for changes."""
        self._diff_codes(old, new)
        self._diff_vehicles(old, new)

    def _diff_codes(self, old: AxuusData, new: AxuusData) -> None:
        """Diff access codes and fire created/expired/used events."""
        old_ids = set(old.codes)
        new_ids = set(new.codes)

        # New codes
        for code_id in new_ids - old_ids:
            code = new.codes[code_id]
            self.hass.bus.async_fire(
                EVENT_CODE_CREATED,
                {
                    "code_id": code.code_id,
                    "code": code.code,
                    "description": code.description,
                    "expires_after": (
                        code.expires_after.isoformat()
                        if code.expires_after
                        else None
                    ),
                    "is_one_time": code.is_one_time,
                },
            )

        # Expired codes
        for code_id in old_ids - new_ids:
            code = old.codes[code_id]
            self.hass.bus.async_fire(
                EVENT_CODE_EXPIRED,
                {
                    "code_id": code.code_id,
                    "code": code.code,
                    "description": code.description,
                    "was_one_time": code.is_one_time,
                },
            )

        # Code usage increases
        for code_id in old_ids & new_ids:
            old_code = old.codes[code_id]
            new_code = new.codes[code_id]
            if new_code.times_used > old_code.times_used:
                self.hass.bus.async_fire(
                    EVENT_CODE_USED,
                    {
                        "code_id": new_code.code_id,
                        "code": new_code.code,
                        "description": new_code.description,
                        "times_used": new_code.times_used,
                        "previous_times_used": old_code.times_used,
                    },
                )

    def _diff_vehicles(self, old: AxuusData, new: AxuusData) -> None:
        """Diff vehicles (resident + guest combined) and fire added/removed events."""
        old_vehicles = old.all_vehicles
        new_vehicles = new.all_vehicles
        old_ids = set(old_vehicles)
        new_ids = set(new_vehicles)

        # New vehicles
        for vid in new_ids - old_ids:
            vehicle = new_vehicles[vid]
            self.hass.bus.async_fire(
                EVENT_VEHICLE_ADDED,
                {
                    "vehicle_id": vehicle.vehicle_id,
                    "lp_num": vehicle.lp_num,
                    "lp_state": vehicle.lp_state,
                    "description": vehicle.description,
                    "vehicle_type": vehicle.vehicle_type.value,
                },
            )

        # Removed vehicles
        for vid in old_ids - new_ids:
            vehicle = old_vehicles[vid]
            self.hass.bus.async_fire(
                EVENT_VEHICLE_REMOVED,
                {
                    "vehicle_id": vehicle.vehicle_id,
                    "lp_num": vehicle.lp_num,
                    "description": vehicle.description,
                    "vehicle_type": vehicle.vehicle_type.value,
                    "removed_via": "external",
                },
            )


def _parse_ver_auth(vehicle_detail: dict[str, Any]) -> bool:
    """Extract the Ver_Auth boolean from a GetVehicle response dict."""
    raw = vehicle_detail.get("Ver_Auth")
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return False
    return str(raw).strip().lower() == "true"
