"""Manager and helper edge cases that the HTTP flows cannot reach directly."""

from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
import time
from typing import Any
from unittest.mock import patch

from aiohttp.test_utils import TestClient
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockUser,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.beamin import manager as manager_module
from custom_components.beamin.auth_helpers import (
    BeamInError,
    TemporarySessions,
    check_approver,
    local_only_blocked,
)
from custom_components.beamin.const import DATA_MANAGER, DATA_SESSIONS, EVENT_EXPIRED
from custom_components.beamin.manager import BeamInManager, BeamRequest
from custom_components.beamin.user_agent import parse_user_agent
from custom_components.beamin.views import network_type

from .common import CLIENT_ID, DEVICE_IP, access_token, approve, create_ok, deny, poll


@pytest.fixture
def manager(hass: HomeAssistant, entry: MockConfigEntry) -> BeamInManager:
    """Return the loaded manager."""
    return hass.data[DATA_MANAGER]


def _new(manager: BeamInManager, ip: str = DEVICE_IP) -> tuple[BeamRequest, str]:
    created = manager.async_create_request(
        ip=ip, via_cloud=False, user_agent="", touch=False, client_id=CLIENT_ID
    )
    return created.request, created.secret


async def test_poll_expires_late_requests(
    hass: HomeAssistant, manager: BeamInManager
) -> None:
    """A request past its deadline is expired on access, even before its timer."""
    expired = async_capture_events(hass, EVENT_EXPIRED)
    request, secret = _new(manager)
    request.expires_at = time.time() - 1
    with pytest.raises(BeamInError) as err:
        await manager.async_poll(
            request.request_id, secret, ip=DEVICE_IP, via_cloud=False
        )
    assert err.value.code == "expired"
    assert len(expired) == 1
    manager._async_expire(request.request_id)
    assert len(expired) == 1


async def test_approval_racing_with_expiry(
    hass: HomeAssistant, manager: BeamInManager, hass_admin_user: MockUser
) -> None:
    """A request that expires while the approval is checked cannot be approved."""
    request, _ = _new(manager)

    async def expire_meanwhile(*_: Any) -> MockUser:
        manager._async_expire(request.request_id)
        return hass_admin_user

    with (
        patch.object(
            manager_module, "async_resolve_target", side_effect=expire_meanwhile
        ),
        pytest.raises(BeamInError) as err,
    ):
        await manager.async_approve(
            hass_admin_user,
            code=request.code,
            match_choice=request.match_number,
            duration="normal",
            target_user_id=None,
        )
    assert err.value.code == "invalid_code"


async def test_codes_never_collide(
    hass: HomeAssistant, manager: BeamInManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new code is drawn again if it matches a waiting one."""
    letters = iter("AAAAAA" + "AAAAAA" + "BBBBBB")
    monkeypatch.setattr(manager_module.secrets, "choice", lambda _: next(letters))
    first, _ = _new(manager)
    second, _ = _new(manager, ip="198.51.100.7")
    assert (first.code, second.code) == ("AAAAAA", "BBBBBB")


async def test_denied_request_does_not_also_expire(
    hass: HomeAssistant, client: TestClient, hass_admin_user: MockUser
) -> None:
    """A denial the device never collected does not fire an expired event."""
    expired = async_capture_events(hass, EVENT_EXPIRED)
    token, _ = await access_token(hass, hass_admin_user)
    request = await create_ok(client)
    assert (await deny(client, request["code"], token)).status == 200
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=121))
    await hass.async_block_till_done()
    assert expired == []


async def test_failed_session_creation_leaves_no_token(
    hass: HomeAssistant, client: TestClient, hass_admin_user: MockUser
) -> None:
    """If the temporary schedule cannot be saved, the new token is removed."""
    token, _ = await access_token(hass, hass_admin_user)
    request = await create_ok(client)
    await approve(client, request, token, duration="temporary")
    before = set(hass_admin_user.refresh_tokens)
    sessions: TemporarySessions = hass.data[DATA_SESSIONS]
    with patch.object(sessions, "async_add", side_effect=OSError("disk full")):
        response = await poll(client, request)
    assert response.status == HTTPStatus.INTERNAL_SERVER_ERROR
    assert set(hass_admin_user.refresh_tokens) == before


async def test_non_string_code_is_rejected(
    hass: HomeAssistant, client: TestClient, hass_admin_user: MockUser
) -> None:
    """Codes must be strings."""
    token, _ = await access_token(hass, hass_admin_user)
    response = await client.post(
        "/api/beamin/deny",
        json={"code": 123456},
        headers={"Authorization": f"Bearer {token}", "X-Forwarded-For": DEVICE_IP},
    )
    assert response.status == 400
    assert (await response.json())["code"] == "invalid_format"


async def test_requests_without_session_are_refused(
    hass: HomeAssistant, manager: BeamInManager, hass_admin_user: MockUser
) -> None:
    """Supervisor-socket requests carry a user but no refresh token."""
    for user, token_id in (
        (None, "x"),
        (hass_admin_user, None),
        (hass_admin_user, "gone"),
    ):
        with pytest.raises(BeamInError) as err:
            check_approver(hass, user, token_id, manager.sessions)
        assert err.value.status == HTTPStatus.FORBIDDEN


def test_local_only_with_unknown_address() -> None:
    """An unparsable address is never considered local."""
    user = MockUser()
    user.local_only = True
    assert local_only_blocked(user, "", via_cloud=False) is True
    assert local_only_blocked(user, "10.0.0.2", via_cloud=False) is False


def test_network_type_unknown_address() -> None:
    """Unix-socket requests have no address to classify."""
    request = BeamRequest(
        request_id="r",
        secret_hash=b"",
        code="AAAAAA",
        match_number=42,
        choices=(42, 43, 44),
        created_at=0,
        expires_at=0,
        ip="",
        via_cloud=False,
        device=parse_user_agent(""),
        client_id=CLIENT_ID,
    )
    assert network_type(request, None) == "unknown"
    assert "secret_hash" not in repr(request)
    assert "AAAAAA" not in repr(request)
