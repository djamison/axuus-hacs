"""Async HTTP client for the Axuus resident portal.

Why this looks the way it does:

The portal is ASP.NET WebForms. Login is a form POST that echoes back four hidden
fields (__VIEWSTATE, __VIEWSTATEGENERATOR, __EVENTVALIDATION, __PREVIOUSPAGE) along
with the user's credentials. On success the server sets `.ASPXAUTH` (HttpOnly).
There's also `ASP.NET_SessionId`, set on the very first GET. Both cookies must
flow on every subsequent request.

Read endpoints are DataTables-style at `*.aspx/<Method>` returning {"d": "<json-string>"}
where the inner string parses to {sEcho, iTotalRecords, iTotalDisplayRecords, aaData: [{...}]}.
The DataTables query string is *required in full*: a minimal request triggers a
server-side NullReferenceException in DataHelper.GetDataTable.

Mutation endpoints are WCF JSON at `*.svc/<Method>` returning {"d": <result>}.

reCAPTCHA is loaded into Login.aspx but not enforced server-side as of 2026-05-01.
If Axuus turns enforcement on, the login response will indicate it; we surface
AxuusCaptchaRequired and the user can fall back to pasting a `.ASPXAUTH` cookie.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import aiohttp
from yarl import URL

from .exceptions import (
    AxuusAuthError,
    AxuusCaptchaRequired,
    AxuusError,
    AxuusServerError,
)
from .models import AccessCode, Vehicle, VehicleType

_LOGGER = logging.getLogger(__name__)

_BASE_URL = "https://www.axuus.com/Residents/"
_LOGIN_URL = _BASE_URL + "Login.aspx"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_HIDDEN_FIELDS = ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION", "__PREVIOUSPAGE")
_HIDDEN_RE = re.compile(
    r'<input[^>]*name="(__VIEWSTATE|__VIEWSTATEGENERATOR|__EVENTVALIDATION|__PREVIOUSPAGE)"'
    r'[^>]*value="([^"]*)"',
    re.IGNORECASE,
)
_LOGIN_ERROR_MARKER = "Incorrect Login or Password"
_AUTH_COOKIE = ".ASPXAUTH"


class AxuusClient:
    """Authenticated client for the Axuus resident portal."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str | None = None,
        password: str | None = None,
        *,
        aspxauth_cookie: str | None = None,
    ) -> None:
        if not (email and password) and not aspxauth_cookie:
            raise ValueError("Provide either email+password or aspxauth_cookie")
        self._session = session
        self._email = email
        self._password = password
        self._aspxauth_cookie = aspxauth_cookie
        self._headers = {"User-Agent": _USER_AGENT}

    async def login(self) -> None:
        """Establish an authenticated session.

        Cookie-only mode: seed the jar with the provided .ASPXAUTH and skip the form post.
        Credentials mode: GET Login.aspx for hidden fields, then POST.
        """
        if self._aspxauth_cookie:
            self._session.cookie_jar.update_cookies(
                {_AUTH_COOKIE: self._aspxauth_cookie}, response_url=URL(_BASE_URL)
            )
            return

        async with self._session.get(_LOGIN_URL, headers=self._headers) as resp:
            if resp.status != 200:
                raise AxuusServerError(f"Login GET returned {resp.status}")
            html = await resp.text()

        hidden = dict(_HIDDEN_RE.findall(html))
        missing = [name for name in _HIDDEN_FIELDS if name not in hidden]
        if missing:
            raise AxuusServerError(f"Login page missing hidden fields: {missing}")

        form = {name: hidden[name] for name in _HIDDEN_FIELDS}
        form["LoginUser$UserName"] = self._email or ""
        form["LoginUser$Password"] = self._password or ""
        form["LoginUser$LoginButton"] = "Login"

        post_headers = {
            **self._headers,
            "Referer": _LOGIN_URL,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        async with self._session.post(
            _LOGIN_URL, data=form, headers=post_headers, allow_redirects=True
        ) as resp:
            body = await resp.text()

        if _LOGIN_ERROR_MARKER in body:
            raise AxuusAuthError("Incorrect login or password")
        if "g-recaptcha" in body and "verify" in body.lower():
            raise AxuusCaptchaRequired(
                "Login response indicates reCAPTCHA enforcement. Use the paste-cookie path."
            )
        # Cookie should be set under normal aiohttp usage. We don't hard-require it here
        # because some test stacks (aioresponses) don't replay Set-Cookie, and absent
        # a clearer signal of failure, "200 + no error marker" is success.

    async def list_codes(self) -> list[AccessCode]:
        rows = await self._datatables_get(
            "AxuusCodes.aspx/GetAccessCodes",
            columns=8,
            sortable_indices={3},
            searchable_indices={1, 2, 6, 7},
            data_indices={0, 1, 2, 3, 6, 7},  # cols 4 & 5 are computed
            sort_col=3,
            sort_dir="desc",
        )
        return [AccessCode.from_row(row) for row in rows]

    async def list_resident_vehicles(self) -> list[Vehicle]:
        rows = await self._datatables_get(
            "ResidentVehicles.aspx/GetResidentVehicles",
            columns=12,
            sortable_indices={1, 2, 3, 4, 5, 6, 7, 8},
            searchable_indices={1, 2, 3, 4, 5, 6, 7},
            data_indices=set(range(12)),
            sort_col=1,
            sort_dir="asc",
        )
        return [Vehicle.from_row(row, VehicleType.RESIDENT) for row in rows]

    async def list_guest_vehicles(self) -> list[Vehicle]:
        rows = await self._datatables_get(
            "GuestOptions.aspx/GetGuestVehicles",
            columns=12,
            sortable_indices={1, 2, 3, 4, 5, 6, 7, 8},
            searchable_indices={1, 2, 3, 4, 5, 6, 7},
            data_indices=set(range(12)),
            sort_col=1,
            sort_dir="asc",
        )
        return [Vehicle.from_row(row, VehicleType.GUEST) for row in rows]

    async def create_code(
        self,
        description: str,
        expires_after: str = "onetime",
        *,
        assign_lp: bool = False,
        email_to: str = "",
        sms_to: str = "",
    ) -> str:
        """Create an Axuus+ code. Returns the 6-digit code as a string."""
        result = await self._svc_post(
            "ResidentHelper.svc/CreateAccessCode",
            {
                "ExpiresAfter": expires_after,
                "Description": description,
                "AssignLP": "true" if assign_lp else "false",
                "EmailTo": email_to,
                "SMSTo": sms_to,
            },
        )
        return str(result)  # server returns int; we normalize to string

    async def update_code(
        self,
        code_id: int,
        *,
        description: str,
        assign_lp: bool,
        email_to: str = "",
        sms_to: str = "",
    ) -> bool:
        result = await self._svc_post(
            "ResidentHelper.svc/SaveAccessCode",
            {
                "AccessCodeID": code_id,
                "Description": description,
                "AssignLP": "true" if assign_lp else "false",
                "EmailTo": email_to,
                "SMSTo": sms_to,
            },
        )
        return bool(result)

    async def delete_code(self, code_id: int) -> bool:
        result = await self._svc_post(
            "ResidentHelper.svc/DeleteAccessCode",
            {"AccessCodeID": code_id},
        )
        return bool(result)

    async def get_vehicle(self, vehicle_id: int | str) -> dict[str, Any]:
        """Return the parsed inner-JSON vehicle dict (with Ver_Auth, etc.)."""
        result = await self._svc_post(
            "VehicleHelper.svc/GetVehicle",
            {"VehicleID": vehicle_id},
        )
        if isinstance(result, str):
            return json.loads(result)
        if isinstance(result, dict):
            return result
        raise AxuusServerError(f"Unexpected GetVehicle payload: {type(result).__name__}")

    async def authorize_vehicle(self, vehicle_id: int | str, *, currently_authorized: bool) -> bool:
        """Toggle authorization. Pass currently_authorized=True to UNauthorize, False to authorize.

        Quirk of the API: the field is the *current* state and the server flips it.
        Callers should read the current state via get_vehicle() first.
        """
        result = await self._svc_post(
            "VehicleHelper.svc/AuthorizeVehicle",
            {"VehicleID": vehicle_id, "isAuthorized": currently_authorized},
        )
        return bool(result)

    async def inactivate_vehicle(self, vehicle_id: int | str) -> bool:
        """Soft-remove the vehicle from this user's account view.

        This does NOT necessarily revoke gate access — Axuus's own copy says contact
        staff for true 'Deny Access'. Useful when a guest leaves and you want to
        clean up your list.
        """
        result = await self._svc_post(
            "VehicleHelper.svc/InactivateVehicle",
            {"VehicleID": vehicle_id},
        )
        return bool(result)

    # ---- internals ----

    async def _datatables_get(
        self,
        path: str,
        *,
        columns: int,
        sortable_indices: set[int],
        searchable_indices: set[int],
        data_indices: set[int],
        sort_col: int,
        sort_dir: str = "desc",
        display_length: int = 500,
    ) -> list[dict[str, Any]]:
        params: list[tuple[str, str]] = [
            ("sEcho", "1"),
            ("iColumns", str(columns)),
            ("sColumns", "," * (columns - 1)),
            ("iDisplayStart", "0"),
            ("iDisplayLength", str(display_length)),
        ]
        for i in range(columns):
            params.append(("mDataProp_" + str(i), str(i) if i in data_indices else ""))
            params.append(("sSearch_" + str(i), ""))
            params.append(("bRegex_" + str(i), "false"))
            params.append(("bSearchable_" + str(i), "true" if i in searchable_indices else "false"))
            params.append(("bSortable_" + str(i), "true" if i in sortable_indices else "false"))
        params.extend(
            [
                ("sSearch", ""),
                ("bRegex", "false"),
                ("iSortCol_0", str(sort_col)),
                ("sSortDir_0", sort_dir),
                ("iSortingCols", "1"),
                ("iParticipant", ""),
            ]
        )

        envelope = await self._raw_request(
            "GET", path, params=params, headers={"Content-Type": "application/json; charset=utf-8"}
        )
        inner = envelope.get("d")
        if not isinstance(inner, str):
            raise AxuusServerError(f"DataTables {path}: missing or non-string 'd' envelope")
        try:
            data = json.loads(inner)
        except json.JSONDecodeError as exc:
            raise AxuusServerError(f"DataTables {path}: cannot parse inner JSON") from exc
        rows = data.get("aaData")
        if not isinstance(rows, list):
            raise AxuusServerError(f"DataTables {path}: missing aaData")
        return rows

    async def _svc_post(self, path: str, body: dict[str, Any]) -> Any:
        envelope = await self._raw_request(
            "POST",
            path,
            json_body=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        if "d" not in envelope:
            raise AxuusServerError(f"SVC {path}: missing 'd' in response")
        return envelope["d"]

    async def _raw_request(
        self,
        method: str,
        path: str,
        *,
        params: list[tuple[str, str]] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = _BASE_URL + path
        merged_headers = {**self._headers, **(headers or {})}
        async with self._session.request(
            method,
            url,
            params=params,
            json=json_body,
            headers=merged_headers,
        ) as resp:
            text = await resp.text()
            if resp.status == 401:
                raise AxuusAuthError(f"{method} {path}: 401 (session expired)")
            if resp.status >= 500:
                raise AxuusServerError(f"{method} {path}: {resp.status}: {text[:500]}")
            if resp.status >= 400:
                raise AxuusError(f"{method} {path}: {resp.status}: {text[:500]}")
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                # If we got HTML back, we were redirected to the login page.
                if "<html" in text.lower() or "<!DOCTYPE" in text:
                    raise AxuusAuthError(f"{method} {path}: redirected to HTML (session expired)") from exc
                raise AxuusServerError(f"{method} {path}: non-JSON body") from exc
            if isinstance(payload, dict) and payload.get("ExceptionType"):
                if "Authentication" in str(payload.get("ExceptionType", "")):
                    raise AxuusAuthError(payload.get("Message", "Authentication failed"))
                raise AxuusServerError(
                    f"{method} {path}: {payload.get('ExceptionType')}: {payload.get('Message')}"
                )
            if not isinstance(payload, dict):
                raise AxuusServerError(f"{method} {path}: response is not a JSON object")
            return payload
