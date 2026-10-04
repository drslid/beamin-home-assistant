"""Helpers shared by the BeamIn tests."""

from __future__ import annotations

from typing import Any

from aiohttp import ClientResponse
from aiohttp.test_utils import TestClient
from homeassistant.auth.models import (
    TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN,
    RefreshToken,
    User,
)
from homeassistant.core import HomeAssistant

TESLA_UA = (
    "Mozilla/5.0 (X11; GNU/Linux) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chromium/79.0.3945.130 Chrome/79.0.3945.130 Safari/537.36 "
    "Tesla/2021.12.25.7-c65ebd6c9a46"
)
PHONE_CLIENT_ID = "https://phone.example.com/"
CLIENT_ID = "https://ha.example.com/"
DEVICE_IP = "203.0.113.10"
PHONE_IP = "198.51.100.20"
ATTACKER_IP = "192.0.2.66"


def headers(ip: str, token: str | None = None, **extra: str) -> dict[str, str]:
    """Return request headers for a client at `ip`, optionally authenticated."""
    result = {"X-Forwarded-For": ip, **extra}
    if token is not None:
        result["Authorization"] = f"Bearer {token}"
    return result


async def access_token(
    hass: HomeAssistant, user: User, *, long_lived: bool = False
) -> tuple[str, RefreshToken]:
    """Create an access token for a user, like a browser login or a script."""
    if long_lived:
        refresh_token = await hass.auth.async_create_refresh_token(
            user, client_name="Script", token_type=TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN
        )
    else:
        refresh_token = await hass.auth.async_create_refresh_token(
            user, PHONE_CLIENT_ID
        )
    return hass.auth.async_create_access_token(refresh_token), refresh_token


async def create(
    client: TestClient,
    *,
    ip: str = DEVICE_IP,
    user_agent: str = TESLA_UA,
    body: dict[str, Any] | None = None,
    **extra: str,
) -> ClientResponse:
    """Create a sign-in request as an unauthenticated device."""
    return await client.post(
        "/api/beamin/request",
        json={"client_id": CLIENT_ID} if body is None else body,
        headers=headers(ip, **{"User-Agent": user_agent, **extra}),
    )


async def create_ok(client: TestClient, **kwargs: Any) -> dict[str, Any]:
    """Create a sign-in request and return its JSON."""
    response = await create(client, **kwargs)
    assert response.status == 200, await response.text()
    return await response.json()


async def poll(
    client: TestClient,
    request: dict[str, Any],
    *,
    ip: str = DEVICE_IP,
    secret: str | None = None,
) -> ClientResponse:
    """Poll a request as its device."""
    return await client.post(
        "/api/beamin/poll",
        json={
            "request_id": request["request_id"],
            "secret": secret or request["secret"],
        },
        headers=headers(ip),
    )


async def pending(
    client: TestClient, code: str, token: str, *, ip: str = PHONE_IP
) -> ClientResponse:
    """Open the approval screen for a code."""
    return await client.get(f"/api/beamin/pending/{code}", headers=headers(ip, token))


async def approve(
    client: TestClient,
    request: dict[str, Any],
    token: str,
    *,
    ip: str = PHONE_IP,
    **body: Any,
) -> ClientResponse:
    """Approve a request, picking the right number unless told otherwise."""
    payload = {"code": request["code"], "match_choice": request["match_number"], **body}
    return await client.post(
        "/api/beamin/approve", json=payload, headers=headers(ip, token)
    )


async def deny(
    client: TestClient, code: str, token: str, *, ip: str = PHONE_IP
) -> ClientResponse:
    """Deny a request."""
    return await client.post(
        "/api/beamin/deny", json={"code": code}, headers=headers(ip, token)
    )
