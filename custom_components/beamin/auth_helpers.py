"""Authorization rules, session creation and temporary-session revocation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from functools import partial
from http import HTTPStatus
from ipaddress import ip_address
import logging
import time
from typing import Any

from aiohttp import web
from homeassistant.auth.models import TOKEN_TYPE_NORMAL, RefreshToken, User
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.util.network import is_local

from .const import CLIENT_NAME_PREFIX, STORAGE_KEY, STORAGE_VERSION
from .user_agent import DeviceInfo

_process_wrong_login: Callable[[web.Request], Awaitable[None]] | None
try:
    # Not a documented integration API, but the only way to feed Home Assistant's
    # own failed-login counter and IP bans (and honour ip_ban_enabled).
    from homeassistant.components.http.ban import (
        process_wrong_login as _process_wrong_login,
    )
except ImportError:  # pragma: no cover - only if a future release moves it
    _process_wrong_login = None

_LOGGER = logging.getLogger(__name__)


class BeamInError(Exception):
    """A refused request; `code` is a stable machine-readable reason."""

    def __init__(
        self,
        code: str,
        status: HTTPStatus,
        *,
        retry_after: float | None = None,
        failed_login: bool = False,
    ) -> None:
        """Initialize the error."""
        super().__init__(code)
        self.code = code
        self.status = status
        self.retry_after = retry_after
        self.failed_login = failed_login


async def async_report_failed_login(request: web.Request) -> None:
    """Count a failed attempt in Home Assistant's IP ban mechanism."""
    if _process_wrong_login is None:  # pragma: no cover
        _LOGGER.warning("IP ban integration unavailable; failure not counted")
        return
    await _process_wrong_login(request)


def check_approver(
    hass: HomeAssistant,
    user: User | None,
    refresh_token_id: str | None,
    sessions: TemporarySessions,
) -> User:
    """Return the approving user if the request comes from a person's session.

    Long-lived access tokens and system users are refused so that no script can
    approve sign-ins, and temporary BeamIn sessions are refused so that they
    cannot mint sessions that outlive them.
    """
    if user is None or refresh_token_id is None:
        raise BeamInError("not_interactive", HTTPStatus.FORBIDDEN)
    token = hass.auth.async_get_refresh_token(refresh_token_id)
    if (
        token is None
        or token.token_type != TOKEN_TYPE_NORMAL
        or user.system_generated
        or not user.is_active
    ):
        raise BeamInError("not_interactive", HTTPStatus.FORBIDDEN)
    if sessions.is_temporary(refresh_token_id):
        raise BeamInError("temporary_session", HTTPStatus.FORBIDDEN)
    return user


def can_sign_in_as(approver: User, target: User) -> bool:
    """Return True if the approver may sign a device in as the target user."""
    if target.id == approver.id:
        return True
    if not approver.is_admin or target.system_generated or not target.is_active:
        return False
    return approver.is_owner or not target.is_owner


async def async_sign_in_targets(hass: HomeAssistant, approver: User) -> list[User]:
    """Return the users the approver may pick, the approver first."""
    if not approver.is_admin:
        return [approver]
    users = [
        u for u in await hass.auth.async_get_users() if can_sign_in_as(approver, u)
    ]
    return sorted(users, key=lambda u: (u.id != approver.id, (u.name or "").casefold()))


async def async_resolve_target(
    hass: HomeAssistant, approver: User, target_user_id: str | None
) -> User:
    """Return the user the device will be signed in as, enforcing privileges."""
    if not target_user_id or target_user_id == approver.id:
        return approver
    target = (
        await hass.auth.async_get_user(target_user_id) if approver.is_admin else None
    )
    if target is None or not can_sign_in_as(approver, target):
        _LOGGER.warning("%s may not sign a device in as another user", approver.name)
        raise BeamInError("not_allowed", HTTPStatus.FORBIDDEN)
    return target


def local_only_blocked(user: User, ip: str, via_cloud: bool) -> bool:
    """Apply Home Assistant's rule for local-only users: no remote, no cloud."""
    if not user.local_only:
        return False
    if via_cloud:
        return True
    try:
        return not is_local(ip_address(ip))
    except ValueError:
        return True


def session_name(device: DeviceInfo, *, temporary: bool) -> str:
    """Return the name shown in Profile → Security → Refresh tokens."""
    name = f"{CLIENT_NAME_PREFIX}{device.label}"
    return f"{name} (temporary)" if temporary else name


async def async_create_session(
    hass: HomeAssistant,
    sessions: TemporarySessions,
    user: User,
    *,
    client_id: str,
    client_name: str,
    remote_ip: str,
    temporary_seconds: int | None,
) -> tuple[RefreshToken, str]:
    """Create the refresh and access tokens through the official auth API.

    A temporary session is persisted for revocation before any token leaves the
    server, so a crash can never turn it into a permanent one.
    """
    refresh_token = await hass.auth.async_create_refresh_token(
        user, client_id=client_id, client_name=client_name
    )
    try:
        if temporary_seconds is not None:
            await sessions.async_add(refresh_token.id, temporary_seconds)
        access_token = hass.auth.async_create_access_token(refresh_token, remote_ip)
    except BaseException:
        hass.auth.async_remove_refresh_token(refresh_token)
        raise
    return refresh_token, access_token


class TemporarySessions:
    """Revoke temporary refresh tokens on time, across restarts."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the revoker."""
        self._hass = hass
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY, private=True, atomic_writes=True
        )
        self._revoke_at: dict[str, float] = {}
        self._cancel: dict[str, CALLBACK_TYPE] = {}

    @property
    def count(self) -> int:
        """Return how many temporary sessions are scheduled for revocation."""
        return len(self._revoke_at)

    def is_temporary(self, refresh_token_id: str) -> bool:
        """Return True if the refresh token is a temporary BeamIn session."""
        return refresh_token_id in self._revoke_at

    async def async_load(self) -> None:
        """Load the schedule, revoke overdue sessions and schedule the others."""
        data = await self._store.async_load()
        sessions = data.get("sessions") if isinstance(data, dict) else None
        if isinstance(sessions, dict):
            self._revoke_at = {
                token_id: float(revoke_at)
                for token_id, revoke_at in sessions.items()
                if isinstance(token_id, str)
                and isinstance(revoke_at, int | float)
                and not isinstance(revoke_at, bool)
            }
        now = time.time()
        overdue = [t for t, revoke_at in self._revoke_at.items() if revoke_at <= now]
        for token_id in overdue:
            self._revoke(token_id)
        for token_id, revoke_at in self._revoke_at.items():
            self._schedule(token_id, revoke_at - now)
        if overdue:
            await self._store.async_save(self._data())

    async def async_add(self, refresh_token_id: str, seconds: float) -> None:
        """Schedule a refresh token for revocation and persist it immediately."""
        self._revoke_at[refresh_token_id] = time.time() + seconds
        self._schedule(refresh_token_id, seconds)
        await self._store.async_save(self._data())

    @callback
    def async_revoke_all(self) -> None:
        """Revoke every temporary session now (integration disabled or removed)."""
        for token_id in list(self._revoke_at):
            self._revoke(token_id)
        self._store.async_delay_save(self._data, 0)

    @callback
    def async_stop(self, _event: Event | None = None) -> None:
        """Cancel the timers; the schedule stays on disk for the next start."""
        for cancel in self._cancel.values():
            cancel()
        self._cancel.clear()

    async def async_remove_store(self) -> None:
        """Delete the schedule file."""
        await self._store.async_remove()

    @callback
    def _schedule(self, token_id: str, delay: float) -> None:
        self._cancel[token_id] = async_call_later(
            self._hass, max(delay, 0), partial(self._async_revoke_due, token_id)
        )

    @callback
    def _async_revoke_due(self, token_id: str, _now: datetime) -> None:
        self._cancel.pop(token_id, None)
        self._revoke(token_id)
        self._store.async_delay_save(self._data, 0)

    @callback
    def _revoke(self, token_id: str) -> None:
        self._revoke_at.pop(token_id, None)
        if (cancel := self._cancel.pop(token_id, None)) is not None:
            cancel()
        if (token := self._hass.auth.async_get_refresh_token(token_id)) is not None:
            self._hass.auth.async_remove_refresh_token(token)
            _LOGGER.info("Revoked temporary session %s", token.client_name)

    def _data(self) -> dict[str, Any]:
        return {"sessions": dict(self._revoke_at)}
