"""Client tests against mocked HTTP. Validates request shapes match the live API."""

from __future__ import annotations

import json
import re
from pathlib import Path

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.axuus.api import (
    AxuusAuthError,
    AxuusClient,
    AxuusError,
)
from custom_components.axuus.api.exceptions import AxuusServerError

FIXTURES = Path(__file__).parent / "fixtures"
LOGIN_URL = "https://www.axuus.com/Residents/Login.aspx"
BASE = "https://www.axuus.com/Residents/"


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as s:
        yield s


@pytest.fixture
def login_html() -> str:
    return (FIXTURES / "login_page_excerpt.html").read_text()


# ---- login flow ----


async def test_login_credentials_success(session, login_html) -> None:
    """Successful login: 200 response with no error marker. (aioresponses can't
    replay Set-Cookie into the jar, so we verify the no-exception path; the
    cookie path is covered by test_login_cookie_only.)"""
    with aioresponses() as m:
        m.get(LOGIN_URL, status=200, body=login_html)
        m.post(LOGIN_URL, status=200, body="<html>Welcome to Axuus</html>")
        client = AxuusClient(session, email="user@example.com", password="hunter2")
        await client.login()  # raises on failure


async def test_login_credentials_wrong_password(session, login_html) -> None:
    with aioresponses() as m:
        m.get(LOGIN_URL, status=200, body=login_html)
        m.post(
            LOGIN_URL,
            status=200,
            body="<html><h4>Incorrect Login or Password</h4></html>",
        )
        client = AxuusClient(session, email="user@example.com", password="bad")
        with pytest.raises(AxuusAuthError, match="Incorrect"):
            await client.login()


async def test_login_credentials_missing_hidden_fields(session) -> None:
    with aioresponses() as m:
        m.get(LOGIN_URL, status=200, body="<html>broken</html>")
        client = AxuusClient(session, email="user@example.com", password="x")
        with pytest.raises(AxuusServerError, match="missing hidden fields"):
            await client.login()


async def test_login_cookie_only(session) -> None:
    client = AxuusClient(session, aspxauth_cookie="PASTED_COOKIE_VALUE")
    await client.login()
    cookie_keys = [c.key for c in session.cookie_jar]
    assert ".ASPXAUTH" in cookie_keys


def test_construct_without_creds_or_cookie() -> None:
    with pytest.raises(ValueError):
        AxuusClient(session=None)  # type: ignore[arg-type]


# ---- list endpoints ----


async def test_list_codes(session) -> None:
    payload = (FIXTURES / "get_access_codes.json").read_text()
    with aioresponses() as m:
        m.get(
            re.compile(r"^https://www\.axuus\.com/Residents/AxuusCodes\.aspx/GetAccessCodes\?.*$"),
            status=200,
            body=payload,
            content_type="application/json",
        )
        client = AxuusClient(session, aspxauth_cookie="x")
        await client.login()
        codes = await client.list_codes()

    assert [c.description for c in codes] == [
        "Cleaner Tuesday",
        "Plumber One Time",
        "Dog Walker",
    ]


async def test_list_resident_vehicles(session) -> None:
    payload = (FIXTURES / "get_resident_vehicles.json").read_text()
    with aioresponses() as m:
        m.get(
            re.compile(r"^https://www\.axuus\.com/Residents/ResidentVehicles\.aspx/GetResidentVehicles\?.*$"),
            status=200,
            body=payload,
            content_type="application/json",
        )
        client = AxuusClient(session, aspxauth_cookie="x")
        await client.login()
        vehicles = await client.list_resident_vehicles()

    assert [v.lp_num for v in vehicles] == ["ABC123", "XYZ789"]


# ---- mutation endpoints ----


async def test_create_code_returns_string_from_int(session) -> None:
    """Server returns {'d': <int>}; client must normalize to string."""
    with aioresponses() as m:
        m.post(
            BASE + "ResidentHelper.svc/CreateAccessCode",
            status=200,
            body=json.dumps({"d": 566626}),
            content_type="application/json",
        )
        client = AxuusClient(session, aspxauth_cookie="x")
        await client.login()
        code = await client.create_code("HA test", expires_after="oneday")

    assert code == "566626"
    assert isinstance(code, str)


async def test_delete_code_returns_bool(session) -> None:
    with aioresponses() as m:
        m.post(
            BASE + "ResidentHelper.svc/DeleteAccessCode",
            status=200,
            body=json.dumps({"d": True}),
            content_type="application/json",
        )
        client = AxuusClient(session, aspxauth_cookie="x")
        await client.login()
        result = await client.delete_code(815150)

    assert result is True


async def test_inactivate_vehicle(session) -> None:
    with aioresponses() as m:
        m.post(
            BASE + "VehicleHelper.svc/InactivateVehicle",
            status=200,
            body=json.dumps({"d": True}),
            content_type="application/json",
        )
        client = AxuusClient(session, aspxauth_cookie="x")
        await client.login()
        result = await client.inactivate_vehicle("V-aaaa-1111")

    assert result is True


async def test_authorize_vehicle_passes_current_state(session) -> None:
    """The API takes the *current* isAuthorized value and flips it. Verify we send the right thing."""
    captured: dict[str, object] = {}

    def callback(url, **kwargs):
        captured["body"] = kwargs.get("json")
        from aioresponses.core import CallbackResult

        return CallbackResult(status=200, body=json.dumps({"d": True}))

    with aioresponses() as m:
        m.post(BASE + "VehicleHelper.svc/AuthorizeVehicle", callback=callback)
        client = AxuusClient(session, aspxauth_cookie="x")
        await client.login()
        # Currently authorized → toggle off
        await client.authorize_vehicle("V-aaaa-1111", currently_authorized=True)

    assert captured["body"] == {"VehicleID": "V-aaaa-1111", "isAuthorized": True}


# ---- error handling ----


async def test_401_raises_auth_error(session) -> None:
    with aioresponses() as m:
        m.post(
            BASE + "ResidentHelper.svc/DeleteAccessCode",
            status=401,
            body=json.dumps(
                {
                    "Message": "Authentication failed.",
                    "ExceptionType": "System.InvalidOperationException",
                }
            ),
        )
        client = AxuusClient(session, aspxauth_cookie="x")
        await client.login()
        with pytest.raises(AxuusAuthError):
            await client.delete_code(123)


async def test_html_redirect_raises_auth_error(session) -> None:
    """When session expires, .svc routes redirect to Login.aspx (HTML body)."""
    with aioresponses() as m:
        m.get(
            re.compile(r"^https://www\.axuus\.com/Residents/AxuusCodes\.aspx/GetAccessCodes\?.*$"),
            status=200,
            body="<!DOCTYPE html><html>Login page</html>",
            content_type="text/html",
        )
        client = AxuusClient(session, aspxauth_cookie="x")
        await client.login()
        with pytest.raises(AxuusAuthError, match="redirected to HTML"):
            await client.list_codes()


async def test_server_npe_raises_server_error(session) -> None:
    """Sending a malformed DataTables query gets a real C# stack trace back."""
    with aioresponses() as m:
        m.get(
            re.compile(r"^https://www\.axuus\.com/Residents/AxuusCodes\.aspx/GetAccessCodes\?.*$"),
            status=500,
            body=json.dumps(
                {
                    "Message": "Object reference not set to an instance of an object.",
                    "ExceptionType": "System.NullReferenceException",
                }
            ),
        )
        client = AxuusClient(session, aspxauth_cookie="x")
        await client.login()
        with pytest.raises(AxuusServerError):
            await client.list_codes()
