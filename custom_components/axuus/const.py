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

# ---------------------------------------------------------------------------
# Integration-layer constants
# ---------------------------------------------------------------------------

# Entity platforms to forward during setup
PLATFORMS: list[str] = ["sensor", "switch", "button", "binary_sensor"]

# Config flow constants
CONF_AUTH_METHOD = "auth_method"
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_ASPXAUTH = "aspxauth"
CONF_POLL_INTERVAL = "poll_interval"

AUTH_METHOD_CREDENTIALS = "credentials"
AUTH_METHOD_COOKIE = "cookie"

# Poll interval bounds (seconds)
DEFAULT_POLL_INTERVAL = 60
MIN_POLL_INTERVAL = 30
MAX_POLL_INTERVAL = 600

# Event type constants (fired on the HA bus)
EVENT_CODE_CREATED = "axuus_code_created"
EVENT_CODE_USED = "axuus_code_used"
EVENT_CODE_EXPIRED = "axuus_code_expired"
EVENT_VEHICLE_ADDED = "axuus_vehicle_added"
EVENT_VEHICLE_REMOVED = "axuus_vehicle_removed"

# Unique ID placeholder for paste-cookie auth (no email available)
COOKIE_USER = "cookie_user"
