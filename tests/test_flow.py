"""End-to-end sign-in flows through the HTTP API."""

from __future__ import annotations

import re

from aiohttp.test_utils import TestClient
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockUser, async_capture_events

from custom_components.beamin.const import (
    CLIENT_NAME_PREFIX,
    EVENT_APPROVED,
    EVENT_REQUESTED,
)

from .common import (
    CLIENT_ID,
    DEVICE_IP,
    PHONE_IP,
    access_token,
    approve,
    create_ok,
    pending,
    poll,
)


async def test_happy_path_delivers_working_tokens_exactly_once(
    hass: HomeAssistant, client: TestClient, hass_admin_user: MockUser
) -> None:
    """Request, approve from the phone, then the device gets tokens once."""
    requested = async_capture_events(hass, EVENT_REQUESTED)
    approved = async_capture_events(hass, EVENT_APPROVED)
    token, _ = await access_token(hass, hass_admin_user)

    request = await create_ok(client)
    assert set(request) == {
        "request_id",
        "secret",
        "code",
        "match_number",
        "qr_svg",
        "expires_in",
        "expires_at",
        "poll_interval",
    }
    assert re.fullmatch(r"[2-9A-HJKMNP-Z]{3}-[2-9A-HJKMNP-Z]{3}", request["code"])
    assert 10 <= request["match_number"] <= 99
    assert len(request["secret"]) >= 43
    assert request["expires_in"] == 120
    assert request["qr_svg"].startswith("<svg")
    assert requested[0].data == {
        "device": "Tesla browser",
        "device_type": "car",
        "ip": DEVICE_IP,
    }

    response = await poll(client, request)
    assert (await response.json())["status"] == "pending"

    response = await pending(client, request["code"].replace("-", "").lower(), token)
    assert response.status == 200
    screen = await response.json()
    assert screen["device"]["label"] == "Tesla browser"
    assert screen["device"]["shared"] is True
    assert screen["ip"] == DEVICE_IP
    assert screen["network"] == "internet"
    assert sorted(screen["choices"]) == sorted(set(screen["choices"]))
    assert len(screen["choices"]) == 3
    assert request["match_number"] in screen["choices"]
    assert "match_number" not in screen

    response = await approve(client, request, token, duration="normal")
    assert response.status == 200
    assert (await response.json())["status"] == "approved"

    response = await poll(client, request)
    assert response.status == 200
    assert response.headers["Cache-Control"] == "no-store"
    tokens = await response.json()
    assert tokens["status"] == "approved"
    assert tokens["token_type"] == "Bearer"
    assert tokens["expires_in"] == 1800
    assert tokens["client_id"] == CLIENT_ID

    response = await poll(client, request)
    assert response.status == 404
    assert (await response.json())["code"] == "expired"

    refresh_token = hass.auth.async_get_refresh_token_by_token(tokens["refresh_token"])
    assert refresh_token is not None
    assert refresh_token.user.id == hass_admin_user.id
    assert refresh_token.client_id == CLIENT_ID
    assert refresh_token.client_name == f"{CLIENT_NAME_PREFIX}Tesla browser"
    assert refresh_token.last_used_ip == DEVICE_IP

    response = await client.get(
        "/api/", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert response.status == 200
    response = await client.post(
        "/auth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": tokens["client_id"],
        },
    )
    assert response.status == 200, await response.text()

    assert len(approved) == 1
    assert approved[0].data == {
        "device": "Tesla browser",
        "device_type": "car",
        "ip": DEVICE_IP,
        "user_id": hass_admin_user.id,
        "user_name": hass_admin_user.name,
        "target_user_id": hass_admin_user.id,
        "target_user_name": hass_admin_user.name,
        "duration": "normal",
    }
    assert approved[0].context.user_id == hass_admin_user.id
    assert PHONE_IP not in str(approved[0].data)
