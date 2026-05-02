from __future__ import annotations


class AxuusError(Exception):
    """Base error for the Axuus API client."""


class AxuusAuthError(AxuusError):
    """Login failed or session expired (401, missing .ASPXAUTH, "Incorrect Login or Password")."""


class AxuusServerError(AxuusError):
    """Server returned a non-success response (5xx, malformed body, NPE stack trace)."""


class AxuusCaptchaRequired(AxuusAuthError):
    """The login page started enforcing reCAPTCHA. User must use the paste-cookie path."""
