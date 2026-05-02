from __future__ import annotations

DOMAIN = "axuus"

BASE_URL = "https://www.axuus.com/Residents/"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

EXPIRES_AFTER_VALUES = ("onetime", "oneday", "threedays", "oneweek", "onemonth")

VEHICLE_TYPE_RESIDENT = 1
VEHICLE_TYPE_GUEST = 2

MAKE_ID_UNKNOWN = 1157
MODEL_ID_UNKNOWN = 7097

CODE_COLUMNS = (
    "AccessCodeID",
    "AccessCode",
    "Description",
    "isOneTime",
    "ExpiresAfter",
    "AssignLP",
    "DateCreated",
    "TimesUsed",
)

VEHICLE_COLUMNS = (
    "VehicleID",
    "LPNum",
    "Description",
    "MakeName",
    "ModelName",
    "Year",
    "LPState",
    "VIN",
    "ValidReg",
    "MakeID",
    "ModelID",
    "ColorID",
)
