"""Temporary sessions: revoked on time, across restarts, and fail-safe."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from aiohttp.test_utils import TestClient
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockUser,
    async_fire_time_changed,
)

from custom_components.beamin.auth_helpers import TemporarySessions
from custom_components.beamin.const import (
    CLIENT_NAME_PREFIX,
    CONF_TEMPORARY_MINUTES,
    DATA_SESSIONS,
    STORAGE_KEY,
)

from .common import access_token, approve, create_ok, poll


async def _temporary_sign_in(
    hass: HomeAssistant, client: TestClient, user: MockUser
) -> dict[str, Any]:
    token, _ = await access_token(hass, user)
    request = await create_ok(client)
    response = await approve(client, request, token, duration="temporary")
    assert response.status == 200
    tokens: dict[str, Any] = await (await poll(client, request)).json()
    assert tokens["status"] == "approved"
    return tokens


def _token_id(hass: HomeAssistant, tokens: dict[str, Any]) -> str:
    refresh_token = hass.auth.async_get_refresh_token_by_token(tokens["refresh_token"])
    assert refresh_token is not None
    return refresh_token.id


async def test_temporary_session_revoked_after_delay(
    hass: HomeAssistant,
    client: TestClient,
    hass_admin_user: MockUser,
    hass_storage: dict[str, Any],
    freezer: FrozenDateTimeFactory,
) -> None:
    """The refresh token disappears after an hour; normal sessions stay."""
    temporary = await _temporary_sign_in(hass, client, hass_admin_user)
    token_id = _token_id(hass, temporary)
    refresh_token = hass.auth.async_get_refresh_token(token_id)
    assert refresh_token is not None
    assert refresh_token.client_name == f"{CLIENT_NAME_PREFIX}Tesla browser (temporary)"
    assert token_id in hass_storage[STORAGE_KEY]["data"]["sessions"]

    token, _ = await access_token(hass, hass_admin_user)
    request = await create_ok(client)
    await approve(client, request, token)
    normal = await (await poll(client, request)).json()

    freezer.tick(timedelta(minutes=59))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.auth.async_get_refresh_token(token_id) is not None

    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.auth.async_get_refresh_token(token_id) is None
    assert hass.auth.async_get_refresh_token(_token_id(hass, normal)) is not None
    response = await client.get(
        "/api/", headers={"Authorization": f"Bearer {temporary['access_token']}"}
    )
    assert response.status == 401

    freezer.tick(timedelta(seconds=5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass_storage[STORAGE_KEY]["data"]["sessions"] == {}


@pytest.mark.parametrize("options", [{CONF_TEMPORARY_MINUTES: 15}])
async def test_temporary_duration_option(
    hass: HomeAssistant,
    client: TestClient,
    hass_admin_user: MockUser,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The temporary duration follows the options."""
    token_id = _token_id(hass, await _temporary_sign_in(hass, client, hass_admin_user))
    freezer.tick(timedelta(minutes=15, seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.auth.async_get_refresh_token(token_id) is None


async def test_revocation_survives_restart(
    hass: HomeAssistant,
    client: TestClient,
    hass_admin_user: MockUser,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Overdue sessions are revoked at startup, the others are rescheduled."""
    overdue = _token_id(hass, await _temporary_sign_in(hass, client, hass_admin_user))
    freezer.tick(timedelta(minutes=30))
    later = _token_id(hass, await _temporary_sign_in(hass, client, hass_admin_user))

    # Simulate a shutdown: the timers die, the schedule stays on disk.
    hass.data[DATA_SESSIONS].async_stop()
    freezer.tick(timedelta(minutes=45))

    restarted = TemporarySessions(hass)
    await restarted.async_load()
    assert hass.auth.async_get_refresh_token(overdue) is None
    assert hass.auth.async_get_refresh_token(later) is not None
    assert restarted.is_temporary(later)
    assert not restarted.is_temporary(overdue)

    freezer.tick(timedelta(minutes=16))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.auth.async_get_refresh_token(later) is None
    assert restarted.count == 0


async def test_corrupt_schedule_is_ignored(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """Malformed entries are dropped instead of breaking the setup."""
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "key": STORAGE_KEY,
        "data": {"sessions": {"a": "soon", "b": True, "c": 4102444800.0}},
    }
    sessions = TemporarySessions(hass)
    await sessions.async_load()
    assert sessions.count == 1
    assert sessions.is_temporary("c")
    sessions.async_stop()


async def test_disabling_revokes_temporary_sessions(
    hass: HomeAssistant,
    client: TestClient,
    entry: MockConfigEntry,
    hass_admin_user: MockUser,
) -> None:
    """A disabled integration cannot leave a temporary session running forever."""
    token_id = _token_id(hass, await _temporary_sign_in(hass, client, hass_admin_user))
    assert await hass.config_entries.async_reload(entry.entry_id)
    assert hass.auth.async_get_refresh_token(token_id) is not None

    await hass.config_entries.async_set_disabled_by(
        entry.entry_id, ConfigEntryDisabler.USER
    )
    await hass.async_block_till_done()
    assert hass.auth.async_get_refresh_token(token_id) is None


async def test_removing_revokes_temporary_sessions(
    hass: HomeAssistant,
    client: TestClient,
    entry: MockConfigEntry,
    hass_admin_user: MockUser,
    hass_storage: dict[str, Any],
) -> None:
    """Removing the integration revokes temporary sessions and forgets the schedule."""
    temporary = _token_id(hass, await _temporary_sign_in(hass, client, hass_admin_user))
    token, _ = await access_token(hass, hass_admin_user)
    request = await create_ok(client)
    await approve(client, request, token)
    normal = _token_id(hass, await (await poll(client, request)).json())

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.auth.async_get_refresh_token(temporary) is None
    assert hass.auth.async_get_refresh_token(normal) is not None
    assert STORAGE_KEY not in hass_storage


async def test_remove_entry_never_loaded(
    hass: HomeAssistant, hass_admin_user: MockUser, hass_storage: dict[str, Any]
) -> None:
    """Removal still revokes when the component never started (entry disabled)."""
    refresh_token = await hass.auth.async_create_refresh_token(
        hass_admin_user, "https://ha.example.com/"
    )
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "key": STORAGE_KEY,
        "data": {"sessions": {refresh_token.id: 4102444800.0}},
    }
    entry = MockConfigEntry(
        domain="beamin", disabled_by=ConfigEntryDisabler.USER, data={}, options={}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.auth.async_get_refresh_token(refresh_token.id) is None
    assert STORAGE_KEY not in hass_storage
