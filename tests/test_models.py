"""Tests for model parsing — runnable without aiohttp."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from custom_components.axuus.api.models import (
    AccessCode,
    Vehicle,
    VehicleType,
    _parse_axuus_datetime,
    _str_to_bool,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _inner(fixture_name: str) -> dict:
    envelope = json.loads((FIXTURES / fixture_name).read_text())
    return json.loads(envelope["d"])


def test_str_to_bool() -> None:
    assert _str_to_bool("True") is True
    assert _str_to_bool("true") is True
    assert _str_to_bool("False") is False
    assert _str_to_bool("") is False
    assert _str_to_bool(None) is False
    assert _str_to_bool(True) is True


def test_parse_axuus_datetime() -> None:
    assert _parse_axuus_datetime("5/2/2026 5:55:07 PM") == datetime(2026, 5, 2, 17, 55, 7)
    assert _parse_axuus_datetime("12/31/2025 12:00:00 AM") == datetime(2025, 12, 31, 0, 0, 0)
    assert _parse_axuus_datetime("") is None
    assert _parse_axuus_datetime(None) is None
    assert _parse_axuus_datetime("not a date") is None


def test_access_code_from_row() -> None:
    rows = _inner("get_access_codes.json")["aaData"]
    codes = [AccessCode.from_row(r) for r in rows]
    assert len(codes) == 3

    cleaner = codes[0]
    assert cleaner.code_id == 100001
    assert cleaner.code == "123456"
    assert cleaner.description == "Cleaner Tuesday"
    assert cleaner.is_one_time is False
    assert cleaner.assign_lp is False
    assert cleaner.times_used == 0
    assert cleaner.expires_after == datetime(2026, 5, 8, 9, 0, 0)

    plumber = codes[1]
    assert plumber.is_one_time is True
    assert plumber.assign_lp is True

    walker = codes[2]
    assert walker.times_used == 3


def test_vehicle_from_row_resident() -> None:
    rows = _inner("get_resident_vehicles.json")["aaData"]
    vehicles = [Vehicle.from_row(r, VehicleType.RESIDENT) for r in rows]
    assert len(vehicles) == 2

    daily = vehicles[0]
    assert daily.vehicle_id == "V-aaaa-1111"
    assert daily.lp_num == "ABC123"
    assert daily.description == "Daily Driver"
    assert daily.make_name == "Honda"
    assert daily.model_name == "Pilot"
    assert daily.year == "2021"
    assert daily.lp_state == "NV"
    assert daily.valid_reg is True
    assert daily.vehicle_type is VehicleType.RESIDENT
    assert daily.authorized is None  # not in listing


def test_vehicle_from_row_guest() -> None:
    rows = _inner("get_guest_vehicles.json")["aaData"]
    vehicles = [Vehicle.from_row(r, VehicleType.GUEST) for r in rows]
    assert len(vehicles) == 1
    assert vehicles[0].vehicle_type is VehicleType.GUEST
    assert vehicles[0].lp_num == "GUEST01"
