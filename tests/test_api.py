"""Tests for the ControlMySpa API client.

Every request is served by a fake session; no test contacts the live service.
"""

from __future__ import annotations

import base64
import json
import time

import aiohttp
import pytest
from conftest import api

ControlMySpaClient = api.ControlMySpaClient


def make_jwt(exp: float) -> str:
    """Build a token carrying the given expiry claim."""

    def segment(payload: dict) -> str:
        raw = json.dumps(payload).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{segment({'alg': 'RS256'})}.{segment({'exp': int(exp)})}.signature"


class FakeResponse:
    """Stands in for an aiohttp response used as an async context manager."""

    def __init__(self, status: int, payload: dict | None = None) -> None:
        self.status = status
        self._payload = payload or {}

    async def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status >= 400:
            raise aiohttp.ClientResponseError(
                None, (), status=self.status, message="error"
            )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class FakeSession:
    """Serves queued responses and records the requests that were made."""

    def __init__(self, post_responses=None, get_responses=None) -> None:
        self.post_responses = list(post_responses or [])
        self.get_responses = list(get_responses or [])
        self.post_calls: list[tuple] = []
        self.get_calls: list[tuple] = []

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return self.post_responses.pop(0)

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return self.get_responses.pop(0)


def login_response(token: str | None = None, refresh: str = "refresh-token"):
    """Build a successful login body in the documented envelope."""
    token = token or make_jwt(time.time() + 86400)
    return FakeResponse(
        200,
        {
            "statusCode": 200,
            "data": {"accessToken": token, "refreshToken": refresh},
            "message": "Log in successful.",
        },
    )


def spas_response(spas: list[dict]):
    """Build a spa listing body."""
    return FakeResponse(
        200,
        {
            "statusCode": 200,
            "data": {"spas": spas, "page": {"totalElements": len(spas)}},
            "message": "ok",
        },
    )


def test_decodes_expiry_from_a_token():
    """The expiry claim drives renewal scheduling."""
    expiry = time.time() + 3600
    assert api.decode_jwt_expiry(make_jwt(expiry)) == pytest.approx(int(expiry))


def test_malformed_tokens_decode_to_none():
    """A token we cannot read must not raise during login."""
    assert api.decode_jwt_expiry("not-a-jwt") is None
    assert api.decode_jwt_expiry("a.!!!!.c") is None
    assert api.decode_jwt_expiry("") is None


def test_token_without_expiry_claim_decodes_to_none():
    """Absence of exp is handled rather than assumed."""
    payload = base64.urlsafe_b64encode(json.dumps({"sub": "x"}).encode())
    token = f"h.{payload.decode().rstrip('=')}.s"

    assert api.decode_jwt_expiry(token) is None


async def test_login_stores_tokens_and_expiry():
    """A successful login yields a usable, correctly dated session."""
    expiry = time.time() + 86400
    session = FakeSession(post_responses=[login_response(make_jwt(expiry))])
    client = ControlMySpaClient(session, "user@example.com", "secret")

    await client.async_login()

    assert client.is_authenticated is True
    url, kwargs = session.post_calls[0]
    assert url.endswith("/web/auth/login")
    # The new API expects JSON with an "email" key, not form-encoded "username".
    assert kwargs["json"] == {"email": "user@example.com", "password": "secret"}


async def test_rejected_credentials_raise_auth_error():
    """A 401 is a credentials problem, not a transport problem."""
    session = FakeSession(post_responses=[FakeResponse(401)])
    client = ControlMySpaClient(session, "user@example.com", "wrong")

    with pytest.raises(api.ControlMySpaAuthError):
        await client.async_login()


async def test_login_without_a_token_raises_auth_error():
    """A 200 carrying no token is still a failed login."""
    session = FakeSession(
        post_responses=[FakeResponse(200, {"statusCode": 200, "data": {}})]
    )
    client = ControlMySpaClient(session, "user@example.com", "secret")

    with pytest.raises(api.ControlMySpaAuthError):
        await client.async_login()


async def test_expired_token_is_not_considered_authenticated():
    """Renewal is triggered before the token actually lapses."""
    session = FakeSession(post_responses=[login_response(make_jwt(time.time() + 60))])
    client = ControlMySpaClient(session, "user@example.com", "secret")

    await client.async_login()

    # Inside the five-minute safety margin, so treated as already expired.
    assert client.is_authenticated is False


async def test_get_spa_returns_the_default_spa():
    """Accounts with several spas resolve to the one marked default."""
    session = FakeSession(
        post_responses=[login_response()],
        get_responses=[
            spas_response(
                [
                    {"_id": "first", "isDefault": False},
                    {"_id": "second", "isDefault": True},
                ]
            )
        ],
    )
    client = ControlMySpaClient(session, "user@example.com", "secret")

    spa = await client.async_get_spa()

    assert spa["_id"] == "second"


async def test_get_spa_falls_back_to_the_only_spa():
    """A single spa with no default flag is still returned."""
    session = FakeSession(
        post_responses=[login_response()],
        get_responses=[spas_response([{"_id": "only"}])],
    )
    client = ControlMySpaClient(session, "user@example.com", "secret")

    assert (await client.async_get_spa())["_id"] == "only"


async def test_account_without_a_spa_raises():
    """An empty listing is reported distinctly so setup can explain itself."""
    session = FakeSession(
        post_responses=[login_response()],
        get_responses=[spas_response([])],
    )
    client = ControlMySpaClient(session, "user@example.com", "secret")

    with pytest.raises(api.ControlMySpaNoSpaError):
        await client.async_get_spa()


async def test_request_sends_bearer_token():
    """State requests authenticate with the token from login."""
    token = make_jwt(time.time() + 86400)
    session = FakeSession(
        post_responses=[login_response(token)],
        get_responses=[spas_response([{"_id": "x"}])],
    )
    client = ControlMySpaClient(session, "user@example.com", "secret")

    await client.async_get_spa()

    _, kwargs = session.get_calls[0]
    assert kwargs["headers"]["Authorization"] == f"Bearer {token}"


async def test_unexpected_401_triggers_reauthentication_and_retry():
    """A token rejected before its stated expiry is replaced, not fatal."""
    session = FakeSession(
        post_responses=[login_response(), login_response()],
        get_responses=[FakeResponse(401), spas_response([{"_id": "recovered"}])],
    )
    client = ControlMySpaClient(session, "user@example.com", "secret")

    spa = await client.async_get_spa()

    assert spa["_id"] == "recovered"
    assert len(session.post_calls) == 2


async def test_refresh_failure_falls_back_to_full_login():
    """The refresh endpoint's shape is unverified, so failure must be survivable."""
    session = FakeSession(
        post_responses=[
            login_response(make_jwt(time.time() + 60)),
            FakeResponse(404),
            login_response(),
        ],
        get_responses=[spas_response([{"_id": "x"}])],
    )
    client = ControlMySpaClient(session, "user@example.com", "secret")
    await client.async_login()

    await client.async_get_spa()

    # Refresh attempted, then a full login when it did not work.
    assert len(session.post_calls) == 3


async def test_connection_errors_are_wrapped():
    """Transport failures surface as a distinct, retryable error type."""

    class ExplodingSession(FakeSession):
        def post(self, url, **kwargs):
            raise aiohttp.ClientError("boom")

    client = ControlMySpaClient(ExplodingSession(), "user@example.com", "secret")

    with pytest.raises(api.ControlMySpaConnectionError):
        await client.async_login()
