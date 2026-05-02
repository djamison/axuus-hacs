from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class VehicleType(str, Enum):
    RESIDENT = "resident"
    GUEST = "guest"


def _str_to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() == "true"


def _parse_axuus_datetime(value: str | None) -> datetime | None:
    """Parse Axuus's "M/D/YYYY h:mm:ss AM/PM" format. Returns None on empty/unparseable."""
    if not value:
        return None
    for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


@dataclass(frozen=True, slots=True)
class AccessCode:
    code_id: int
    code: str
    description: str
    is_one_time: bool
    expires_after: datetime | None
    assign_lp: bool
    date_created: datetime | None
    times_used: int

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "AccessCode":
        """Parse a single aaData row from GetAccessCodes.

        Rows look like {"0": "<id>", "1": "<code>", "2": "...", "DT_RowId": "..."}.
        """
        return cls(
            code_id=int(row["0"]),
            code=str(row["1"]),
            description=str(row["2"]),
            is_one_time=_str_to_bool(row["3"]),
            expires_after=_parse_axuus_datetime(row.get("4")),
            assign_lp=_str_to_bool(row["5"]),
            date_created=_parse_axuus_datetime(row.get("6")),
            times_used=int(row["7"]) if str(row.get("7", "")).strip() else 0,
        )


@dataclass(frozen=True, slots=True)
class Vehicle:
    vehicle_id: str
    lp_num: str
    description: str
    make_name: str
    model_name: str
    year: str
    lp_state: str
    vin: str
    valid_reg: bool
    make_id: str
    model_id: str
    color_id: str
    vehicle_type: VehicleType
    authorized: bool | None = None  # populated by GetVehicle, not by list endpoints

    @classmethod
    def from_row(cls, row: dict[str, Any], vehicle_type: VehicleType) -> "Vehicle":
        return cls(
            vehicle_id=str(row["0"]),
            lp_num=str(row.get("1", "") or ""),
            description=str(row.get("2", "") or ""),
            make_name=str(row.get("3", "") or ""),
            model_name=str(row.get("4", "") or ""),
            year=str(row.get("5", "") or ""),
            lp_state=str(row.get("6", "") or ""),
            vin=str(row.get("7", "") or ""),
            valid_reg=_str_to_bool(row.get("8")),
            make_id=str(row.get("9", "") or ""),
            model_id=str(row.get("10", "") or ""),
            color_id=str(row.get("11", "") or ""),
            vehicle_type=vehicle_type,
        )
