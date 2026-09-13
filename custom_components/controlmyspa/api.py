"""Client for the ControlMySpa cloud API.

Deliberately free of Home Assistant imports so it can be exercised standalone
against the live service.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import time
from typing import Any

import aiohttp

from .const import (
    ENDPOINT_LOGIN,
    ENDPOINT_REFRESH,
    ENDPOINT_SPAS,
    REQUEST_TIMEOUT,
    TOKEN_EXPIRY_MARGIN,
)

_LOGGER = logging.getLogger(__name__)


class ControlMySpaError(Exception):
    """Base error for all client failures."""


class ControlMySpaConnectionError(ControlMySpaError):
    """The service could not be reached, or answered too slowly."""


class ControlMySpaAuthError(ControlMySpaError):
    """Credentials were rejected, or a token could not be obtained."""


class ControlMySpaNoSpaError(ControlMySpaError):
    """Authentication succeeded but the account exposes no spa."""


def decode_jwt_expiry(token: str) -> float | None:
    """Return the ``exp`` claim of a JWT as a UNIX timestamp.

    The payload is read purely to schedule our own renewal, so the signature is
    not checked and no trust decision rests on the result.
    """
    try:
        payload_segment = token.split(".")[1]
    except IndexError:
        return None

    # JWT uses unpadded base64url; restore the padding before decoding.
    padding = "=" * (-len(payload_segment) % 4)
    try:
        payload = json.loads(
            base64.urlsafe_b64decode(payload_segment + padding).decode("utf-8")
        )
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None

    expiry = payload.get("exp")
    if isinstance(expiry, (int, float)):
        return float(expiry)
    return None


class ControlMySpaClient:
    """Authenticates against the cloud API and retrieves spa state."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
        timeout: int = REQUEST_TIMEOUT,
    ) -> None:
        """Store credentials and the session used for every request."""
        self._session = session
        self._email = email
        self._password = password
        self._timeout = aiohttp.ClientTimeout(total=timeout)

        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: float = 0.0
        # Serialises renewals so concurrent callers cannot each trigger a login.
        self._auth_lock = asyncio.Lock()

    @property
    def access_token(self) -> str | None:
        """Return the current access token, for diagnostics only."""
        return self._access_token

    @property
    def is_authenticated(self) -> bool:
        """Return True while the cached token is still usable."""
        if not self._access_token:
            return False
        return time.time() < self._expires_at - TOKEN_EXPIRY_MARGIN

    async def async_login(self) -> None:
        """Exchange credentials for an access token.

        The portal posts plain credentials here and brokers to Azure AD B2C
        server-side, so there is no redirect or PKCE flow to reproduce.
        """
        payload = {"email": self._email, "password": self._password}

        try:
            async with self._session.post(
                ENDPOINT_LOGIN, json=payload, timeout=self._timeout
            ) as response:
                if response.status in (400, 401, 403):
                    raise ControlMySpaAuthError("Credentials were rejected")
                response.raise_for_status()
                body = await response.json()
        except asyncio.TimeoutError as err:
            raise ControlMySpaConnectionError("Timed out contacting the API") from err
        except aiohttp.ClientError as err:
            raise ControlMySpaConnectionError(
                f"Could not reach the API: {err}"
            ) from err

        data = (body or {}).get("data") or {}
        access_token = data.get("accessToken")
        if not access_token:
            raise ControlMySpaAuthError("Login response contained no access token")

        self._access_token = access_token
        self._refresh_token = data.get("refreshToken")

        expiry = decode_jwt_expiry(access_token)
        # Tokens are minted with a 24h life; fall back to that if the claim is
        # unreadable so an odd token cannot pin us to a permanently stale value.
        self._expires_at = expiry if expiry is not None else time.time() + 86400

        _LOGGER.debug(
            "Authenticated successfully; token valid for %d minutes",
            max(0, int((self._expires_at - time.time()) / 60)),
        )

    async def async_refresh_token(self) -> bool:
        """Try to renew via the refresh endpoint.

        The request and response shapes here are inferred rather than observed,
        so failure is expected to be survivable: callers fall back to a full
        login, which is cheap against a 24h token.
        """
        if not self._refresh_token:
            return False

        try:
            async with self._session.post(
                ENDPOINT_REFRESH,
                json={"refreshToken": self._refresh_token},
                timeout=self._timeout,
            ) as response:
                if response.status != 200:
                    return False
                body = await response.json()
        except (asyncio.TimeoutError, aiohttp.ClientError, ValueError):
            return False

        data = (body or {}).get("data") or {}
        access_token = data.get("accessToken")
        if not access_token:
            return False

        self._access_token = access_token
        self._refresh_token = data.get("refreshToken") or self._refresh_token
        expiry = decode_jwt_expiry(access_token)
        self._expires_at = expiry if expiry is not None else time.time() + 86400

        _LOGGER.debug("Renewed access token via refresh endpoint")
        return True

    async def async_ensure_token(self) -> None:
        """Guarantee a usable token, renewing or re-authenticating as needed."""
        if self.is_authenticated:
            return

        async with self._auth_lock:
            # Another caller may have renewed while we waited for the lock.
            if self.is_authenticated:
                return
            if await self.async_refresh_token():
                return
            await self.async_login()

    async def _async_get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """Perform an authenticated GET, retrying once after a 401."""
        await self.async_ensure_token()

        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {self._access_token}"}
            try:
                async with self._session.get(
                    url, headers=headers, params=params, timeout=self._timeout
                ) as response:
                    if response.status == 401 and attempt == 1:
                        # Token rejected earlier than its own expiry claimed.
                        _LOGGER.debug("Token rejected; re-authenticating")
                        self._access_token = None
                        await self.async_ensure_token()
                        continue
                    if response.status in (401, 403):
                        raise ControlMySpaAuthError("Access denied by the API")
                    response.raise_for_status()
                    return await response.json()
            except asyncio.TimeoutError as err:
                raise ControlMySpaConnectionError(
                    "Timed out contacting the API"
                ) from err
            except aiohttp.ClientError as err:
                raise ControlMySpaConnectionError(
                    f"Could not reach the API: {err}"
                ) from err

        raise ControlMySpaAuthError("Could not authenticate against the API")

    async def async_get_spa(self) -> dict[str, Any]:
        """Return the raw record for the account's active spa.

        This single call supplies everything the old client needed two requests
        and a discovery document to assemble.
        """
        body = await self._async_get(ENDPOINT_SPAS, params={"page": 0, "pageSize": 20})

        spas = ((body or {}).get("data") or {}).get("spas") or []
        if not spas:
            raise ControlMySpaNoSpaError("The account has no spa registered")

        for spa in spas:
            if spa.get("isDefault"):
                return spa
        return spas[0]
