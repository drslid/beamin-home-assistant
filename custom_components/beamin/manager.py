"""Sign-in request lifecycle: codes, secrets, number matching, approval, expiry."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from functools import partial
import hashlib
import hmac
from http import HTTPStatus
import logging
import secrets
import time
from typing import Any

from homeassistant.auth.models import User
from homeassistant.core import CALLBACK_TYPE, Context, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .auth_helpers import (
    BeamInError,
    TemporarySessions,
    async_create_session,
    async_resolve_target,
    local_only_blocked,
    session_name,
)
from .const import (
    APPROVER_FAILURE_WINDOW,
    APPROVER_LOCKOUT,
    APPROVER_MAX_FAILURES,
    CODE_ALPHABET,
    CODE_LENGTH,
    CREATE_RATE_LIMIT,
    CREATE_RATE_WINDOW,
    DURATION_NORMAL,
    DURATION_TEMPORARY,
    EVENT_APPROVED,
    EVENT_DENIED,
    EVENT_EXPIRED,
    EVENT_REQUESTED,
    MATCH_CHOICES,
    MATCH_MAX,
    MATCH_MIN,
    MAX_PENDING_PER_IP,
    MAX_PENDING_TOTAL,
    PAGE_RATE_LIMIT,
    PAGE_RATE_WINDOW,
    PANEL_URL_PATH,
    POLL_RATE_LIMIT,
    POLL_RATE_WINDOW,
)
from .rate_limit import FailureLockout, SlidingWindowLimiter, ip_key
from .user_agent import DeviceInfo, parse_user_agent

_LOGGER = logging.getLogger(__name__)


class RequestStatus(StrEnum):
    """Where a sign-in request stands."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


@dataclass(frozen=True, slots=True)
class Approval:
    """The decision taken on the approver's phone."""

    approver_id: str
    target_user_id: str
    temporary_seconds: int | None


@dataclass(slots=True)
class BeamRequest:
    """A sign-in request; lives in memory only, for at most the request TTL."""

    request_id: str = field(repr=False)
    secret_hash: bytes = field(repr=False)
    code: str = field(repr=False)
    match_number: int = field(repr=False)
    choices: tuple[int, ...]
    created_at: float
    expires_at: float
    ip: str
    via_cloud: bool
    device: DeviceInfo
    client_id: str
    status: RequestStatus = RequestStatus.PENDING
    approval: Approval | None = None
    deny_reason: str | None = None
    cancel_expiry: CALLBACK_TYPE | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class NewRequest:
    """A freshly created request and the secret only its creator receives."""

    request: BeamRequest
    secret: str = field(repr=False)


def normalize_code(value: object) -> str | None:
    """Return the canonical code ("K7F29X") or None if it cannot be one."""
    if not isinstance(value, str):
        return None
    code = "".join(char for char in value.upper() if char not in " -")
    if len(code) != CODE_LENGTH or any(char not in CODE_ALPHABET for char in code):
        return None
    return code


def format_code(code: str) -> str:
    """Return the displayed form of a code, e.g. "K7F-29X"."""
    return f"{code[:3]}-{code[3:]}"


def _hash_secret(secret: str) -> bytes:
    # The secret carries 256 random bits: a fast hash is enough.
    return hashlib.sha256(secret.encode()).digest()


def _random_number() -> int:
    return MATCH_MIN + secrets.randbelow(MATCH_MAX - MATCH_MIN + 1)


class BeamInManager:
    """Create, approve, deny, deliver and expire sign-in requests."""

    def __init__(
        self,
        hass: HomeAssistant,
        sessions: TemporarySessions,
        *,
        request_ttl: int,
        temporary_minutes: int,
        public_url: str | None,
    ) -> None:
        """Initialize the manager."""
        self.hass = hass
        self.sessions = sessions
        self.request_ttl = request_ttl
        self.temporary_minutes = temporary_minutes
        self.public_url = public_url
        self._requests: dict[str, BeamRequest] = {}
        self._codes: dict[str, str] = {}
        self._page_limiter = SlidingWindowLimiter(PAGE_RATE_LIMIT, PAGE_RATE_WINDOW)
        self._create_limiter = SlidingWindowLimiter(
            CREATE_RATE_LIMIT, CREATE_RATE_WINDOW
        )
        self._poll_limiter = SlidingWindowLimiter(POLL_RATE_LIMIT, POLL_RATE_WINDOW)
        self._lockout = FailureLockout(
            APPROVER_MAX_FAILURES, APPROVER_FAILURE_WINDOW, APPROVER_LOCKOUT
        )

    # Requesting device (unauthenticated) -----------------------------------

    @callback
    def async_check_page_rate(self, ip: str) -> None:
        """Rate limit the /beam page itself."""
        if (wait := self._page_limiter.hit(ip_key(ip), time.time())) is not None:
            raise BeamInError(
                "rate_limited", HTTPStatus.TOO_MANY_REQUESTS, retry_after=wait
            )

    @callback
    def async_create_request(
        self,
        *,
        ip: str,
        via_cloud: bool,
        user_agent: str | None,
        touch: bool,
        client_id: str,
    ) -> NewRequest:
        """Create a sign-in request for an unauthenticated device."""
        now = time.time()
        key = ip_key(ip)
        if (wait := self._create_limiter.hit(key, now)) is not None:
            raise BeamInError(
                "rate_limited", HTTPStatus.TOO_MANY_REQUESTS, retry_after=wait
            )
        live = [r for r in self._requests.values() if r.expires_at > now]
        same_ip = [r for r in live if ip_key(r.ip) == key]
        if len(live) >= MAX_PENDING_TOTAL or len(same_ip) >= MAX_PENDING_PER_IP:
            blocking = same_ip if len(same_ip) >= MAX_PENDING_PER_IP else live
            raise BeamInError(
                "too_many_pending",
                HTTPStatus.TOO_MANY_REQUESTS,
                retry_after=min(r.expires_at for r in blocking) - now,
            )

        secret = secrets.token_urlsafe(32)
        match_number = _random_number()
        choices = {match_number}
        while len(choices) < MATCH_CHOICES:
            choices.add(_random_number())
        shuffled = list(choices)
        secrets.SystemRandom().shuffle(shuffled)
        request = BeamRequest(
            request_id=secrets.token_urlsafe(16),
            secret_hash=_hash_secret(secret),
            code=self._new_code(),
            match_number=match_number,
            choices=tuple(shuffled),
            created_at=now,
            expires_at=now + self.request_ttl,
            ip=ip,
            via_cloud=via_cloud,
            device=parse_user_agent(user_agent, touch=touch),
            client_id=client_id,
        )
        request.cancel_expiry = async_call_later(
            self.hass, self.request_ttl, partial(self._async_expire, request.request_id)
        )
        self._requests[request.request_id] = request
        self._codes[request.code] = request.request_id
        self.hass.bus.async_fire(EVENT_REQUESTED, self._event_data(request))
        _LOGGER.info("Sign-in requested by %s from %s", request.device.label, ip)
        return NewRequest(request, secret)

    async def async_poll(
        self, request_id: object, secret: object, *, ip: str, via_cloud: bool
    ) -> dict[str, Any]:
        """Report the request status to its creator; deliver tokens exactly once."""
        now = time.time()
        if (wait := self._poll_limiter.hit(ip_key(ip), now)) is not None:
            raise BeamInError(
                "rate_limited", HTTPStatus.TOO_MANY_REQUESTS, retry_after=wait
            )
        if not isinstance(request_id, str) or not isinstance(secret, str):
            raise BeamInError("invalid_request", HTTPStatus.BAD_REQUEST)
        request = self._requests.get(request_id)
        if request is None or request.expires_at <= now:
            if request is not None:
                self._async_expire(request_id)
            raise BeamInError("expired", HTTPStatus.NOT_FOUND)
        if not hmac.compare_digest(request.secret_hash, _hash_secret(secret)):
            # Only the creator knows the request id: a wrong secret is an attack.
            self._remove(request)
            self._fire_denied(request, "invalid_secret", None)
            raise BeamInError("invalid_secret", HTTPStatus.FORBIDDEN, failed_login=True)
        if request.status is RequestStatus.PENDING:
            return {"status": "pending", "expires_in": round(request.expires_at - now)}

        # Removed before any await: a concurrent poll can never get tokens too.
        self._remove(request)
        if request.approval is None:
            return {"status": "denied", "reason": request.deny_reason}
        return await self._async_deliver(request, request.approval, ip, via_cloud)

    async def _async_deliver(
        self, request: BeamRequest, approval: Approval, ip: str, via_cloud: bool
    ) -> dict[str, Any]:
        """Create the session now, in the context of the device receiving it."""
        user = await self.hass.auth.async_get_user(approval.target_user_id)
        if user is None or not user.is_active or user.system_generated:
            return self._refuse_delivery(request, approval, "user_unavailable")
        if local_only_blocked(user, ip, via_cloud):
            return self._refuse_delivery(request, approval, "local_only")

        temporary = approval.temporary_seconds is not None
        refresh_token, access_token = await async_create_session(
            self.hass,
            self.sessions,
            user,
            client_id=request.client_id,
            client_name=session_name(request.device, temporary=temporary),
            remote_ip=ip,
            temporary_seconds=approval.temporary_seconds,
        )
        approver = await self.hass.auth.async_get_user(approval.approver_id)
        self.hass.bus.async_fire(
            EVENT_APPROVED,
            {
                **self._event_data(request),
                "user_id": approval.approver_id,
                "user_name": approver.name if approver else None,
                "target_user_id": user.id,
                "target_user_name": user.name,
                "duration": DURATION_TEMPORARY if temporary else DURATION_NORMAL,
            },
            context=Context(user_id=approval.approver_id),
        )
        _LOGGER.info(
            "%s signed in as %s from %s (%s session, approved by %s)",
            request.device.label,
            user.name,
            ip,
            DURATION_TEMPORARY if temporary else DURATION_NORMAL,
            approver.name if approver else approval.approver_id,
        )
        return {
            "status": "approved",
            "access_token": access_token,
            "refresh_token": refresh_token.token,
            "token_type": "Bearer",
            "expires_in": int(refresh_token.access_token_expiration.total_seconds()),
            "client_id": request.client_id,
        }

    # Approver (authenticated) -------------------------------------------------

    @callback
    def async_find(self, approver: User, code: object) -> BeamRequest:
        """Return the pending request for a code typed or scanned by the approver."""
        now = time.time()
        if (wait := self._lockout.locked_for(approver.id, now)) is not None:
            raise BeamInError("locked", HTTPStatus.TOO_MANY_REQUESTS, retry_after=wait)
        normalized = normalize_code(code)
        if normalized is None:
            raise BeamInError("invalid_format", HTTPStatus.BAD_REQUEST)
        request_id = self._codes.get(normalized)
        request = self._requests.get(request_id) if request_id else None
        if (
            request is None
            or request.status is not RequestStatus.PENDING
            or request.expires_at <= now
        ):
            self._record_failure(approver, now)
            raise BeamInError("invalid_code", HTTPStatus.NOT_FOUND)
        return request

    async def async_approve(
        self,
        approver: User,
        *,
        code: object,
        match_choice: object,
        duration: object,
        target_user_id: object,
    ) -> tuple[BeamRequest, User]:
        """Approve a request after checking the number shown on the device."""
        request = self.async_find(approver, code)
        if duration not in (DURATION_NORMAL, DURATION_TEMPORARY) or not (
            target_user_id is None or isinstance(target_user_id, str)
        ):
            raise BeamInError("invalid_request", HTTPStatus.BAD_REQUEST)
        if match_choice != request.match_number:
            self._record_failure(approver, time.time())
            self._deny(request, "wrong_number", approver.id)
            raise BeamInError("wrong_number", HTTPStatus.BAD_REQUEST)
        target = await async_resolve_target(self.hass, approver, target_user_id)
        if local_only_blocked(target, request.ip, request.via_cloud):
            raise BeamInError("local_only", HTTPStatus.FORBIDDEN)
        if (
            self._requests.get(request.request_id) is not request
            or request.status is not RequestStatus.PENDING
        ):
            raise BeamInError("invalid_code", HTTPStatus.NOT_FOUND)

        request.status = RequestStatus.APPROVED
        request.approval = Approval(
            approver_id=approver.id,
            target_user_id=target.id,
            temporary_seconds=(
                self.temporary_minutes * 60 if duration == DURATION_TEMPORARY else None
            ),
        )
        self._codes.pop(request.code, None)
        _LOGGER.info(
            "%s approved the sign-in of %s as %s",
            approver.name,
            request.device.label,
            target.name,
        )
        return request, target

    @callback
    def async_deny(self, approver: User, code: object) -> BeamRequest:
        """Deny a pending request."""
        request = self.async_find(approver, code)
        self._deny(request, "denied", approver.id)
        return request

    # Housekeeping -------------------------------------------------------------

    def approval_url(self, code: str, fallback_base: str) -> str:
        """Return the URL encoded in the QR code."""
        base = self.public_url
        if not base:
            try:
                base = get_url(self.hass, prefer_external=True)
            except NoURLAvailableError:
                base = fallback_base
        return f"{base.rstrip('/')}/{PANEL_URL_PATH}?code={code}"

    @callback
    def async_stop(self) -> None:
        """Drop every request and cancel the timers."""
        for request in list(self._requests.values()):
            self._remove(request)

    def diagnostics(self) -> dict[str, Any]:
        """Return counters only: no code, id, address or user."""
        return {
            "requests": dict(Counter(r.status.value for r in self._requests.values())),
            "request_ttl": self.request_ttl,
            "temporary_minutes": self.temporary_minutes,
            "public_url_configured": bool(self.public_url),
            "locked_approvers": self._lockout.locked_count(time.time()),
            "temporary_sessions": self.sessions.count,
        }

    def _new_code(self) -> str:
        while True:
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            if code not in self._codes:
                return code

    def _record_failure(self, approver: User, now: float) -> None:
        if self._lockout.record_failure(approver.id, now):
            _LOGGER.warning(
                "%s entered too many wrong codes: approvals locked for %d minutes",
                approver.name,
                APPROVER_LOCKOUT // 60,
            )

    @callback
    def _deny(self, request: BeamRequest, reason: str, user_id: str) -> None:
        request.status = RequestStatus.DENIED
        request.deny_reason = reason
        self._codes.pop(request.code, None)
        self._fire_denied(request, reason, user_id)

    @callback
    def _refuse_delivery(
        self, request: BeamRequest, approval: Approval, reason: str
    ) -> dict[str, Any]:
        self._fire_denied(request, reason, approval.approver_id)
        return {"status": "denied", "reason": reason}

    @callback
    def _fire_denied(
        self, request: BeamRequest, reason: str, user_id: str | None
    ) -> None:
        self.hass.bus.async_fire(
            EVENT_DENIED,
            {**self._event_data(request), "user_id": user_id, "reason": reason},
            context=Context(user_id=user_id),
        )
        _LOGGER.info(
            "Sign-in of %s from %s refused: %s",
            request.device.label,
            request.ip,
            reason,
        )

    @callback
    def _async_expire(self, request_id: str, _now: datetime | None = None) -> None:
        if (request := self._requests.get(request_id)) is None:
            return
        self._remove(request)
        if request.status is RequestStatus.DENIED:
            return
        self.hass.bus.async_fire(
            EVENT_EXPIRED,
            {
                **self._event_data(request),
                "approved": request.status is RequestStatus.APPROVED,
            },
        )
        _LOGGER.info("Sign-in request of %s expired", request.device.label)

    @callback
    def _remove(self, request: BeamRequest) -> None:
        self._requests.pop(request.request_id, None)
        if self._codes.get(request.code) == request.request_id:
            del self._codes[request.code]
        if request.cancel_expiry is not None:
            request.cancel_expiry()
            request.cancel_expiry = None

    @staticmethod
    def _event_data(request: BeamRequest) -> dict[str, Any]:
        return {
            "device": request.device.label,
            "device_type": request.device.kind,
            "ip": request.ip,
        }
