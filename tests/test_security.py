"""Security properties of the sign-in flow."""

from __future__ import annotations

from datetime import timedelta
import json
import logging
from unittest.mock import patch

from aiohttp.test_utils import TestClient
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockUser,
    async_capture_events,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.beamin import manager as manager_module
from custom_components.beamin.const import EVENT_DENIED, EVENT_EXPIRED

from .common import (
    ATTACKER_IP,
    CLIENT_ID,
    DEVICE_IP,
    PHONE_IP,
    access_token,
    approve,
    create,
    create_ok,
    deny,
    headers,
    pending,
    poll,
)


@pytest.fixture
async def admin_token(hass: HomeAssistant, hass_admin_user: MockUser) -> str:
    """Return an interactive admin session."""
    token, _ = await access_token(hass, hass_admin_user)
    return token


async def _sign_in(
    hass: HomeAssistant, client: TestClient, token: str, **body: object
) -> dict[str, object]:
    request = await create_ok(client)
    response = await approve(client, request, token, **body)
    assert response.status == 200, await response.text()
    response = await poll(client, request)
    result: dict[str, object] = await response.json()
    return result


async def test_code_alone_grants_nothing(
    hass: HomeAssistant, client: TestClient, admin_token: str
) -> None:
    """Approving does not hand tokens to the approver nor to a wrong secret."""
    request = await create_ok(client)
    response = await approve(client, request, admin_token)
    body = await response.json()
    assert "access_token" not in body
    assert "refresh_token" not in body

    response = await poll(client, request, ip=ATTACKER_IP, secret="x" * 43)
    assert response.status == 403
    assert (await response.json())["code"] == "invalid_secret"
    # The request is destroyed: the legitimate device gets nothing either.
    response = await poll(client, request)
    assert response.status == 404


async def test_wrong_secret_feeds_ip_ban(
    hass: HomeAssistant, client: TestClient
) -> None:
    """Wrong secrets count as failed logins and end in Home Assistant's IP ban."""
    denied = async_capture_events(hass, EVENT_DENIED)
    requests = [await create_ok(client) for _ in range(3)]
    for request in requests:
        response = await poll(client, request, ip=ATTACKER_IP, secret="guess")
        assert response.status == 403
    assert [event.data["reason"] for event in denied] == ["invalid_secret"] * 3

    response = await create(client, ip=ATTACKER_IP)
    assert response.status == 403  # banned by Home Assistant's middleware
    response = await client.get("/beam", headers=headers(ATTACKER_IP))
    assert response.status == 403
    response = await create(client)
    assert response.status == 200


async def test_unknown_request_is_expired_not_a_failed_login(
    hass: HomeAssistant, client: TestClient
) -> None:
    """Polling after cleanup is normal for the page: it never leads to a ban."""
    for _ in range(4):
        response = await poll(
            client, {"request_id": "nope", "secret": "x"}, ip=ATTACKER_IP
        )
        assert response.status == 404
    response = await create(client, ip=ATTACKER_IP)
    assert response.status == 200


async def test_wrong_number_cancels_request(
    hass: HomeAssistant, client: TestClient, admin_token: str
) -> None:
    """A wrong pick among the three numbers invalidates the request at once."""
    request = await create_ok(client)
    screen = await (await pending(client, request["code"], admin_token)).json()
    decoy = next(n for n in screen["choices"] if n != request["match_number"])

    response = await approve(client, request, admin_token, match_choice=decoy)
    assert response.status == 400
    assert (await response.json())["code"] == "wrong_number"

    response = await approve(client, request, admin_token)
    assert response.status == 404
    response = await poll(client, request)
    assert await response.json() == {"status": "denied", "reason": "wrong_number"}
    response = await poll(client, request)
    assert response.status == 404


async def test_expired_request(
    hass: HomeAssistant,
    client: TestClient,
    admin_token: str,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Requests die after the TTL, approved or not."""
    expired = async_capture_events(hass, EVENT_EXPIRED)
    waiting = await create_ok(client)
    approved = await create_ok(client)
    assert (await approve(client, approved, admin_token)).status == 200

    freezer.tick(timedelta(seconds=121))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert (await poll(client, waiting)).status == 404
    assert (await poll(client, approved)).status == 404
    response = await pending(client, waiting["code"], admin_token)
    assert response.status == 404
    assert sorted(event.data["approved"] for event in expired) == [False, True]


async def test_expired_before_timer_runs(
    hass: HomeAssistant,
    client: TestClient,
    admin_token: str,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A late timer does not extend a request's life."""
    request = await create_ok(client)
    freezer.tick(timedelta(seconds=121))
    assert (await pending(client, request["code"], admin_token)).status == 404
    assert (await poll(client, request)).status == 404


async def test_denied_request(
    hass: HomeAssistant, client: TestClient, admin_token: str
) -> None:
    """The device learns about the denial once, then the request is gone."""
    denied = async_capture_events(hass, EVENT_DENIED)
    request = await create_ok(client)
    response = await deny(client, request["code"], admin_token)
    assert response.status == 200
    assert await (await poll(client, request)).json() == {
        "status": "denied",
        "reason": "denied",
    }
    assert (await poll(client, request)).status == 404
    assert (await deny(client, request["code"], admin_token)).status == 404
    assert denied[0].data["reason"] == "denied"


async def test_code_cannot_be_reused(
    hass: HomeAssistant, client: TestClient, admin_token: str
) -> None:
    """Once approved, the code is released: no second approval, no second token."""
    request = await create_ok(client)
    assert (await approve(client, request, admin_token)).status == 200
    assert (await approve(client, request, admin_token)).status == 404
    assert (await deny(client, request["code"], admin_token)).status == 404
    assert (await poll(client, request)).status == 200
    assert (await approve(client, request, admin_token)).status == 404


@pytest.mark.parametrize("path", ["/api/beamin/approve", "/api/beamin/deny"])
async def test_no_state_change_on_get(
    hass: HomeAssistant, client: TestClient, admin_token: str, path: str
) -> None:
    """GET never approves nor denies, even with the code in the query string."""
    request = await create_ok(client)
    response = await client.get(
        f"{path}?code={request['code']}&match_choice={request['match_number']}",
        headers=headers(PHONE_IP, admin_token),
    )
    assert response.status == 405
    assert await (await poll(client, request)).json() == {
        "status": "pending",
        "expires_in": 120,
    }


async def test_approval_requires_authentication(
    hass: HomeAssistant, client: TestClient
) -> None:
    """Without a session, approval endpoints answer 401."""
    request = await create_ok(client)
    for response in (
        await client.post(
            "/api/beamin/approve",
            json={"code": request["code"], "match_choice": request["match_number"]},
            headers=headers(PHONE_IP),
        ),
        await client.get(
            f"/api/beamin/pending/{request['code']}", headers=headers(PHONE_IP)
        ),
        await client.post(
            "/api/beamin/deny",
            json={"code": request["code"]},
            headers=headers(PHONE_IP),
        ),
    ):
        assert response.status == 401


async def test_long_lived_token_cannot_approve(
    hass: HomeAssistant, client: TestClient, hass_admin_user: MockUser
) -> None:
    """Scripts holding a long-lived token cannot approve sign-ins."""
    token, _ = await access_token(hass, hass_admin_user, long_lived=True)
    request = await create_ok(client)
    for response in (
        await pending(client, request["code"], token),
        await approve(client, request, token),
        await deny(client, request["code"], token),
    ):
        assert response.status == 403
        assert (await response.json())["code"] == "not_interactive"


async def test_system_user_cannot_approve(
    hass: HomeAssistant, client: TestClient, hass_supervisor_access_token: str
) -> None:
    """System-generated users (Supervisor, …) cannot approve sign-ins."""
    request = await create_ok(client)
    response = await approve(client, request, hass_supervisor_access_token)
    assert response.status == 403


async def test_temporary_session_cannot_approve(
    hass: HomeAssistant, client: TestClient, admin_token: str
) -> None:
    """A temporary BeamIn session cannot mint sessions that outlive it."""
    tokens = await _sign_in(hass, client, admin_token, duration="temporary")
    request = await create_ok(client)
    response = await approve(client, request, str(tokens["access_token"]))
    assert response.status == 403
    assert (await response.json())["code"] == "temporary_session"


async def test_non_admin_cannot_impersonate(
    hass: HomeAssistant,
    client: TestClient,
    hass_read_only_user: MockUser,
    hass_admin_user: MockUser,
) -> None:
    """Non-admins only sign devices in as themselves; the server enforces it."""
    token, _ = await access_token(hass, hass_read_only_user)
    request = await create_ok(client)
    screen = await (await pending(client, request["code"], token)).json()
    assert screen["targets"] == []
    assert screen["approver"]["is_admin"] is False

    response = await approve(client, request, token, target_user_id=hass_admin_user.id)
    assert response.status == 403
    assert (await response.json())["code"] == "not_allowed"

    response = await approve(
        client, request, token, target_user_id=hass_read_only_user.id
    )
    assert response.status == 200
    tokens = await (await poll(client, request)).json()
    refresh_token = hass.auth.async_get_refresh_token_by_token(tokens["refresh_token"])
    assert refresh_token is not None
    assert refresh_token.user.id == hass_read_only_user.id


async def test_admin_impersonation_rules(
    hass: HomeAssistant,
    client: TestClient,
    admin_token: str,
    hass_admin_user: MockUser,
    hass_read_only_user: MockUser,
    hass_owner_user: MockUser,
    hass_supervisor_user: MockUser,
) -> None:
    """Admins may pick other users, within the impersonation rules."""
    tablet = MockUser(name="Tablet").add_to_hass(hass)
    retired = MockUser(name="Retired", is_active=False).add_to_hass(hass)

    request = await create_ok(client)
    screen = await (await pending(client, request["code"], admin_token)).json()
    target_ids = [target["id"] for target in screen["targets"]]
    assert target_ids[0] == hass_admin_user.id
    assert {tablet.id, hass_read_only_user.id} <= set(target_ids)
    assert not {hass_owner_user.id, hass_supervisor_user.id, retired.id} & set(
        target_ids
    )

    for forbidden in (
        hass_owner_user.id,
        hass_supervisor_user.id,
        retired.id,
        "missing",
    ):
        response = await approve(client, request, admin_token, target_user_id=forbidden)
        assert response.status == 403

    response = await approve(client, request, admin_token, target_user_id=tablet.id)
    assert response.status == 200
    assert (await response.json())["user"] == "Tablet"
    tokens = await (await poll(client, request)).json()
    refresh_token = hass.auth.async_get_refresh_token_by_token(tokens["refresh_token"])
    assert refresh_token is not None
    assert refresh_token.user.id == tablet.id


async def test_owner_may_target_owner_list(
    hass: HomeAssistant,
    client: TestClient,
    hass_owner_user: MockUser,
    hass_admin_user: MockUser,
) -> None:
    """The owner sees other admins as targets."""
    token, _ = await access_token(hass, hass_owner_user)
    request = await create_ok(client)
    screen = await (await pending(client, request["code"], token)).json()
    assert hass_admin_user.id in [target["id"] for target in screen["targets"]]
    response = await approve(client, request, token, target_user_id=hass_admin_user.id)
    assert response.status == 200


async def test_local_only_user(
    hass: HomeAssistant, client: TestClient, admin_token: str
) -> None:
    """Local-only users can only be signed in on devices of the local network."""
    kiosk = MockUser(name="Kiosk").add_to_hass(hass)
    kiosk.local_only = True

    remote = await create_ok(client)
    response = await approve(client, remote, admin_token, target_user_id=kiosk.id)
    assert response.status == 403
    assert (await response.json())["code"] == "local_only"

    local = await create_ok(client, ip="192.168.1.50")
    response = await approve(client, local, admin_token, target_user_id=kiosk.id)
    assert response.status == 200
    # The device moved to the internet before collecting its tokens.
    response = await poll(client, local, ip=DEVICE_IP)
    assert await response.json() == {"status": "denied", "reason": "local_only"}

    local = await create_ok(client, ip="192.168.1.50")
    assert (
        await approve(client, local, admin_token, target_user_id=kiosk.id)
    ).status == 200
    with patch("custom_components.beamin.views.is_cloud_connection", return_value=True):
        response = await poll(client, local, ip="192.168.1.50")
    assert await response.json() == {"status": "denied", "reason": "local_only"}

    local = await create_ok(client, ip="192.168.1.50")
    assert (
        await approve(client, local, admin_token, target_user_id=kiosk.id)
    ).status == 200
    response = await poll(client, local, ip="192.168.1.50")
    assert (await response.json())["status"] == "approved"


async def test_user_deactivated_before_delivery(
    hass: HomeAssistant, client: TestClient, admin_token: str
) -> None:
    """No session is created for a user deactivated after the approval."""
    tablet = MockUser(name="Tablet").add_to_hass(hass)
    request = await create_ok(client)
    assert (
        await approve(client, request, admin_token, target_user_id=tablet.id)
    ).status == 200
    tablet.is_active = False
    response = await poll(client, request)
    assert await response.json() == {"status": "denied", "reason": "user_unavailable"}
    assert not tablet.refresh_tokens


async def test_wrong_codes_lock_the_approver_out(
    hass: HomeAssistant,
    client: TestClient,
    admin_token: str,
    hass_read_only_user: MockUser,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Five wrong codes lock the user for five minutes, even for a right code."""
    request = await create_ok(client)
    for code in ("AAA-AAA", "BBB-BBB", "CCC-CCC", "DDD-DDD"):
        assert (await pending(client, code, admin_token)).status == 404
    # A right code in between does not reset the counter.
    assert (await pending(client, request["code"], admin_token)).status == 200
    assert (await deny(client, "EEE-EEE", admin_token)).status == 404

    response = await pending(client, request["code"], admin_token)
    assert response.status == 429
    body = await response.json()
    assert body["code"] == "locked"
    assert 290 <= body["retry_after"] <= 300
    assert response.headers["Retry-After"] == str(body["retry_after"])
    assert (await approve(client, request, admin_token)).status == 429

    # Other users are not affected.
    other, _ = await access_token(hass, hass_read_only_user)
    assert (await pending(client, request["code"], other)).status == 200

    freezer.tick(timedelta(seconds=250))
    fresh = await create_ok(client)
    assert (await pending(client, fresh["code"], admin_token)).status == 429
    freezer.tick(timedelta(seconds=51))
    assert (await pending(client, fresh["code"], admin_token)).status == 200


async def test_malformed_codes_are_not_counted(
    hass: HomeAssistant, client: TestClient, admin_token: str
) -> None:
    """Codes that cannot exist are rejected without touching the lockout."""
    for code in ("0O1IL0", "TOOLONGCODE", "ab", "AB-12"):
        response = await pending(client, code, admin_token)
        assert response.status == 400
        assert (await response.json())["code"] == "invalid_format"
    request = await create_ok(client)
    assert (await pending(client, request["code"], admin_token)).status == 200


async def test_pending_limits(hass: HomeAssistant, client: TestClient) -> None:
    """At most 3 waiting requests per address (IPv6: per /64) and 10 overall."""
    for _ in range(3):
        await create_ok(client)
    response = await create(client)
    assert response.status == 429
    body = await response.json()
    assert body["code"] == "too_many_pending"
    assert 1 <= body["retry_after"] <= 120

    for host in range(1, 4):
        await create_ok(client, ip=f"2001:db8:1:2::{host}")
    response = await create(client, ip="2001:db8:1:2:ffff::1")
    assert response.status == 429

    for ip in ("198.51.100.1", "198.51.100.1", "198.51.100.1", "198.51.100.2"):
        await create_ok(client, ip=ip)
    response = await create(client, ip="198.51.100.3")
    assert response.status == 429
    assert (await response.json())["code"] == "too_many_pending"


async def test_request_rate_limit(hass: HomeAssistant, client: TestClient) -> None:
    """Request creation is rate limited per address."""
    with (
        patch.object(manager_module, "MAX_PENDING_PER_IP", 100),
        patch.object(manager_module, "MAX_PENDING_TOTAL", 100),
    ):
        for _ in range(6):
            await create_ok(client)
        response = await create(client)
    assert response.status == 429
    assert (await response.json())["code"] == "rate_limited"


async def test_poll_rate_limit(hass: HomeAssistant, client: TestClient) -> None:
    """Polling is rate limited per address."""
    request = await create_ok(client)
    statuses = [(await poll(client, request)).status for _ in range(121)]
    assert statuses[:120] == [200] * 120
    assert statuses[120] == 429


async def test_page_rate_limit(hass: HomeAssistant, client: TestClient) -> None:
    """The /beam page is rate limited per address too."""
    statuses = [
        (await client.get("/beam", headers=headers(DEVICE_IP))).status
        for _ in range(31)
    ]
    assert statuses[:30] == [200] * 30
    assert statuses[30] == 429
    assert (await client.get("/beam", headers=headers(PHONE_IP))).status == 200


@pytest.mark.parametrize(
    ("client_id", "origin"),
    [
        (None, None),
        (42, None),
        ("ftp://ha.example.com/", None),
        ("https://ha.example.com/lovelace", None),
        ("https://ha.example.com/?x=1", None),
        ("https://ha.example.com/#x", None),
        ("https://user:pass@ha.example.com/", None),
        ("https://ha.example.com:99999/", None),
        ("https://8.8.8.8/", None),
        ("https:///", None),
        (CLIENT_ID, "https://evil.example.com"),
    ],
)
async def test_invalid_client_id(
    hass: HomeAssistant, client: TestClient, client_id: object, origin: str | None
) -> None:
    """The client id must be the page origin, as the frontend computes it."""
    extra = {"Origin": origin} if origin else {}
    response = await create(client, body={"client_id": client_id}, **extra)
    assert response.status == 400
    assert (await response.json())["code"] == "invalid_client"


@pytest.mark.parametrize(
    "client_id",
    [CLIENT_ID, "http://192.168.1.2:8123/", "http://homeassistant.local:8123/"],
)
async def test_valid_client_id(
    hass: HomeAssistant, client: TestClient, client_id: str
) -> None:
    """Domain names and local addresses are accepted, matching the Origin header."""
    response = await create(
        client, body={"client_id": client_id}, Origin=client_id[:-1]
    )
    assert response.status == 200


async def test_invalid_bodies(hass: HomeAssistant, client: TestClient) -> None:
    """Only small JSON objects are accepted."""
    response = await client.post(
        "/api/beamin/request", data="client_id=x", headers=headers(DEVICE_IP)
    )
    assert response.status == 415
    response = await client.post(
        "/api/beamin/request",
        data="{",
        headers=headers(DEVICE_IP, **{"Content-Type": "application/json"}),
    )
    assert response.status == 400
    response = await client.post(
        "/api/beamin/request", json=["x"], headers=headers(DEVICE_IP)
    )
    assert response.status == 400
    response = await client.post(
        "/api/beamin/request",
        json={"client_id": CLIENT_ID, "padding": "x" * 5000},
        headers=headers(DEVICE_IP),
    )
    assert response.status == 413
    response = await client.post(
        "/api/beamin/poll",
        json={"request_id": 1, "secret": None},
        headers=headers(DEVICE_IP),
    )
    assert response.status == 400


async def test_invalid_approval_payloads(
    hass: HomeAssistant, client: TestClient, admin_token: str
) -> None:
    """Unknown durations and malformed targets are rejected without side effects."""
    request = await create_ok(client)
    response = await approve(client, request, admin_token, duration="forever")
    assert response.status == 400
    response = await approve(client, request, admin_token, target_user_id=["x"])
    assert response.status == 400
    assert (await approve(client, request, admin_token)).status == 200


async def test_page_and_api_headers(hass: HomeAssistant, client: TestClient) -> None:
    """The page is never cached nor framed and loads nothing external."""
    response = await client.get("/beam")
    assert response.status == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    # Home Assistant rewrites X-Frame-Options; CSP frame-ancestors is enforced first.
    assert response.headers["X-Frame-Options"] in ("DENY", "SAMEORIGIN")
    csp = response.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp
    assert "default-src 'none'" in csp
    assert "script-src 'self';" in csp
    assert "unsafe-inline" not in csp
    html = await response.text()
    assert "<script>" not in html
    assert "http://" not in html
    assert "https://" not in html

    response = await create(client)
    assert response.headers["Cache-Control"] == "no-store"


async def test_secrets_never_logged_or_in_diagnostics(
    hass: HomeAssistant,
    client: TestClient,
    entry: MockConfigEntry,
    admin_token: str,
    hass_client: ClientSessionGenerator,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Secrets, tokens and codes stay out of logs and diagnostics."""
    caplog.set_level(logging.DEBUG)
    request = await create_ok(client)
    waiting = await create_ok(client, ip="192.168.1.9")
    await poll(client, request)
    await pending(client, request["code"], admin_token)
    await approve(client, request, admin_token)

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    tokens = await (await poll(client, request)).json()

    beamin_logs = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("custom_components.beamin")
    )
    assert "signed in as" in beamin_logs
    for value in (request["code"], request["code"].replace("-", ""), waiting["code"]):
        assert value not in beamin_logs
    for value in (
        request["secret"],
        waiting["secret"],
        request["request_id"],
        tokens["access_token"],
        tokens["refresh_token"],
    ):
        assert value not in caplog.text

    dump = json.dumps(diagnostics)
    for value in (
        request["secret"],
        request["request_id"],
        request["code"].replace("-", ""),
        waiting["code"].replace("-", ""),
        DEVICE_IP,
        "192.168.1.9",
    ):
        assert value not in dump
    assert diagnostics["state"]["requests"] == {"approved": 1, "pending": 1}
