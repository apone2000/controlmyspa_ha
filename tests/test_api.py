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

    async def json(self, **kwargs):
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


def command_response(status: int = 200, success: bool = True, message: str = "ok"):
    """Build a command reply in the envelope the service uses."""
    return FakeResponse(
        status,
        {"statusCode": status, "data": {"success": success}, "message": message},
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


async def test_failed_read_raises_connection_error():
    """A server error on a read is retryable, not a crash."""
    session = FakeSession(
        post_responses=[login_response()], get_responses=[FakeResponse(500)]
    )
    client = ControlMySpaClient(session, "user@example.com", "secret")

    with pytest.raises(api.ControlMySpaConnectionError):
        await client.async_get_spa()


# --- current state and commands ----------------------------------------------


async def test_current_state_is_read_from_its_own_endpoint():
    """Components live on current-state, not in the /web/spas record."""
    session = FakeSession(
        post_responses=[login_response()],
        get_responses=[
            FakeResponse(
                200,
                {
                    "statusCode": 200,
                    "data": {"components": [{"componentType": "LIGHT"}]},
                },
            )
        ],
    )
    client = ControlMySpaClient(session, "user@example.com", "secret")

    state = await client.async_get_current_state("spa-1")

    assert state["components"] == [{"componentType": "LIGHT"}]
    assert session.get_calls[0][0].endswith("/web/spas/spa-1/current-state")


async def test_component_command_sends_the_portal_payload():
    """The body the portal sends, verified live against a real light."""
    token = make_jwt(time.time() + 86400)
    session = FakeSession(post_responses=[login_response(token), command_response()])
    client = ControlMySpaClient(session, "user@example.com", "secret")

    await client.async_set_component_state("spa-1", "light", "HIGH", 0)

    url, kwargs = session.post_calls[1]
    assert url.endswith("/web/spa-commands/component-state")
    assert kwargs["json"] == {
        "spaId": "spa-1",
        "via": "WEB",
        "componentType": "light",
        "state": "HIGH",
        "deviceNumber": 0,
    }
    assert kwargs["headers"]["Authorization"] == f"Bearer {token}"


async def test_unported_component_command_omits_device_number():
    """Only types addressed by port send deviceNumber at all."""
    session = FakeSession(post_responses=[login_response(), command_response()])
    client = ControlMySpaClient(session, "user@example.com", "secret")

    await client.async_set_component_state("spa-1", "circ-pump", "HIGH")

    assert "deviceNumber" not in session.post_calls[1][1]["json"]


async def test_heater_mode_command_sends_mode_not_state():
    """The heater endpoint names its field differently from component-state."""
    session = FakeSession(post_responses=[login_response(), command_response()])
    client = ControlMySpaClient(session, "user@example.com", "secret")

    await client.async_set_heater_mode("spa-1", "REST")

    url, kwargs = session.post_calls[1]
    assert url.endswith("/web/spa-commands/temperature/heater-mode")
    assert kwargs["json"] == {"spaId": "spa-1", "via": "WEB", "mode": "REST"}


async def test_target_temperature_command_sends_value():
    """The portal's desired-temperature dialog posts a bare value."""
    session = FakeSession(post_responses=[login_response(), command_response()])
    client = ControlMySpaClient(session, "user@example.com", "secret")

    await client.async_set_target_temperature("spa-1", 101.0)

    url, kwargs = session.post_calls[1]
    assert url.endswith("/web/spa-commands/temperature/value")
    assert kwargs["json"] == {"spaId": "spa-1", "via": "WEB", "value": 101.0}


async def test_panel_state_command_sends_state():
    """The portal's panel lock button posts the lock action as state."""
    session = FakeSession(post_responses=[login_response(), command_response()])
    client = ControlMySpaClient(session, "user@example.com", "secret")

    await client.async_set_panel_state("spa-1", "LOCK_PANEL")

    url, kwargs = session.post_calls[1]
    assert url.endswith("/web/spa-commands/panel/state")
    assert kwargs["json"] == {"spaId": "spa-1", "via": "WEB", "state": "LOCK_PANEL"}


async def test_service_refusal_raises_command_error_with_its_message():
    """Observed live: a 503 carrying a Redis out-of-memory refusal."""
    session = FakeSession(
        post_responses=[
            login_response(),
            command_response(
                503,
                success=False,
                message="OOM command not allowed when used memory > 'maxmemory'.",
            ),
        ]
    )
    client = ControlMySpaClient(session, "user@example.com", "secret")

    with pytest.raises(api.ControlMySpaCommandError, match="OOM command"):
        await client.async_set_component_state("spa-1", "light", "OFF", 0)


async def test_success_false_is_a_refusal_even_with_200():
    """The envelope's own verdict outranks the status code."""
    session = FakeSession(
        post_responses=[login_response(), command_response(success=False)]
    )
    client = ControlMySpaClient(session, "user@example.com", "secret")

    with pytest.raises(api.ControlMySpaCommandError):
        await client.async_set_heater_mode("spa-1", "READY")


async def test_command_retries_after_unexpected_401():
    """A command is not lost to a token rejected before its stated expiry."""
    session = FakeSession(
        post_responses=[
            login_response(),
            FakeResponse(401),
            login_response(),
            command_response(),
        ]
    )
    client = ControlMySpaClient(session, "user@example.com", "secret")

    await client.async_set_component_state("spa-1", "blower", "HIGH", 0)

    assert session.post_calls[-1][0].endswith("/web/spa-commands/component-state")
