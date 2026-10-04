"""HTTP views: the /beam page and the BeamIn API."""

from __future__ import annotations

from http import HTTPStatus
import io
from ipaddress import ip_address
import json
import math
import time
from typing import Any
from urllib.parse import urlsplit

from aiohttp import hdrs, web
from homeassistant.auth.models import User
from homeassistant.components.http import (
    KEY_HASS_REFRESH_TOKEN_ID,
    KEY_HASS_USER,
    HomeAssistantView,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import is_cloud_connection
from homeassistant.util.network import is_local
import segno

from .auth_helpers import (
    BeamInError,
    async_report_failed_login,
    async_sign_in_targets,
    check_approver,
)
from .const import API_URL, BEAM_PAGE_URL, DATA_MANAGER, DURATION_NORMAL, POLL_INTERVAL
from .manager import BeamInManager, BeamRequest, format_code

MAX_BODY_BYTES = 4096
MAX_CLIENT_ID_LENGTH = 255

NO_STORE: dict[str, str] = {hdrs.CACHE_CONTROL: "no-store", hdrs.PRAGMA: "no-cache"}

# Home Assistant's middleware rewrites X-Frame-Options to SAMEORIGIN when
# use_x_frame_options is on; frame-ancestors is what browsers enforce first.
PAGE_HEADERS: dict[str, str] = {
    **NO_STORE,
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Permissions-Policy": (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def validate_client_id(value: object, origin: str | None) -> str:
    """Return the OAuth client id for the page origin, as the frontend computes it.

    The frontend refreshes tokens with `${location.protocol}//${location.host}/`,
    so the refresh token must carry exactly that client id. Host rules follow
    Home Assistant's own check (domain names or local IP addresses).
    """
    if not isinstance(value, str) or len(value) > MAX_CLIENT_ID_LENGTH:
        raise BeamInError("invalid_client", HTTPStatus.BAD_REQUEST)
    try:
        parts = urlsplit(value)
        _ = parts.port
    except ValueError as err:
        raise BeamInError("invalid_client", HTTPStatus.BAD_REQUEST) from err
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.path != "/"
        or parts.query
        or parts.fragment
    ):
        raise BeamInError("invalid_client", HTTPStatus.BAD_REQUEST)
    netloc = parts.netloc.lower()
    host = netloc[1:-1] if netloc.startswith("[") and netloc.endswith("]") else netloc
    try:
        address = ip_address(host)
    except ValueError:
        address = None
    if address is not None and not is_local(address):
        raise BeamInError("invalid_client", HTTPStatus.BAD_REQUEST)
    page_origin = f"{parts.scheme}://{netloc}"
    if origin is not None and origin.lower() != page_origin:
        raise BeamInError("invalid_client", HTTPStatus.BAD_REQUEST)
    return f"{page_origin}/"


def make_qr_svg(url: str) -> str:
    """Return the QR code of a URL as standalone SVG markup."""
    qr = segno.make(url, error="m", micro=False)
    buffer = io.BytesIO()
    qr.save(
        buffer,
        kind="svg",
        scale=1,
        border=4,
        dark="#000",
        light="#fff",
        xmldecl=False,
        svgns=True,
        omitsize=True,
    )
    return buffer.getvalue().decode()


def network_type(request: BeamRequest, approver_ip: str | None) -> str:
    """Classify where the requesting device connects from."""
    if request.via_cloud:
        return "cloud"
    try:
        address = ip_address(request.ip)
    except ValueError:
        return "unknown"
    if is_local(address):
        return "local"
    if request.ip == approver_ip:
        return "same_public_ip"
    return "internet"


def describe_request(
    request: BeamRequest,
    approver: User,
    targets: list[User],
    *,
    approver_ip: str | None,
    temporary_minutes: int,
) -> dict[str, Any]:
    """Return what the approval screen shows. The matching number stays hidden."""
    now = time.time()
    device = request.device
    return {
        "code": format_code(request.code),
        "device": {
            "kind": device.kind,
            "model": device.model,
            "browser": device.browser,
            "label": device.label,
            "shared": device.shared,
        },
        "ip": request.ip,
        "network": network_type(request, approver_ip),
        "age": max(0, round(now - request.created_at)),
        "expires_in": max(0, round(request.expires_at - now)),
        "choices": list(request.choices),
        "temporary_minutes": temporary_minutes,
        "approver": {
            "id": approver.id,
            "name": approver.name,
            "is_admin": approver.is_admin,
        },
        "targets": [
            {"id": user.id, "name": user.name, "is_admin": user.is_admin}
            for user in targets
        ]
        if approver.is_admin
        else [],
    }


async def read_json(request: web.Request) -> dict[str, Any]:
    """Read a small JSON object body."""
    if request.content_type != "application/json":
        raise BeamInError("invalid_request", HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
    raw = b""
    while len(raw) <= MAX_BODY_BYTES:
        if not (chunk := await request.content.read(MAX_BODY_BYTES + 1 - len(raw))):
            break
        raw += chunk
    if len(raw) > MAX_BODY_BYTES:
        raise BeamInError("invalid_request", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
    try:
        data = json.loads(raw)
    except ValueError as err:
        raise BeamInError("invalid_request", HTTPStatus.BAD_REQUEST) from err
    if not isinstance(data, dict):
        raise BeamInError("invalid_request", HTTPStatus.BAD_REQUEST)
    return data


class BeamInView(HomeAssistantView):
    """Shared plumbing of the BeamIn endpoints."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the view."""
        self.hass = hass

    def manager(self) -> BeamInManager:
        """Return the manager, or refuse if the integration is not loaded."""
        if (manager := self.hass.data.get(DATA_MANAGER)) is None:
            raise BeamInError("unavailable", HTTPStatus.NOT_FOUND)
        return manager

    def approver(self, request: web.Request, manager: BeamInManager) -> User:
        """Return the approving user of an authenticated request."""
        return check_approver(
            self.hass,
            request.get(KEY_HASS_USER),
            request.get(KEY_HASS_REFRESH_TOKEN_ID),
            manager.sessions,
        )

    async def error(self, request: web.Request, err: BeamInError) -> web.Response:
        """Answer a refused request, feeding the IP ban counter when relevant."""
        if err.failed_login:
            await async_report_failed_login(request)
        body: dict[str, Any] = {"code": err.code}
        headers = dict(NO_STORE)
        if err.retry_after is not None:
            seconds = max(1, math.ceil(err.retry_after))
            body["retry_after"] = seconds
            headers[hdrs.RETRY_AFTER] = str(seconds)
        return self.json(body, err.status, headers=headers)


class BeamPageView(BeamInView):
    """Serve the page a signed-out device opens."""

    url = BEAM_PAGE_URL
    name = "beamin:page"
    requires_auth = False

    def __init__(self, hass: HomeAssistant, html: str) -> None:
        """Initialize the view with the rendered page."""
        super().__init__(hass)
        self._html = html

    async def get(self, request: web.Request) -> web.Response:
        """Return the sign-in page."""
        if self.hass.data.get(DATA_MANAGER) is None:
            return web.Response(status=HTTPStatus.NOT_FOUND, headers=NO_STORE)
        return web.Response(
            text=self._html,
            content_type="text/html",
            charset="utf-8",
            headers=PAGE_HEADERS,
        )


class RequestView(BeamInView):
    """Create a sign-in request (unauthenticated)."""

    url = f"{API_URL}/request"
    name = "beamin:request"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        """Create a request and return its code, QR code and secret."""
        try:
            manager = self.manager()
            body = await read_json(request)
            client_id = validate_client_id(
                body.get("client_id"), request.headers.get(hdrs.ORIGIN)
            )
            new = manager.async_create_request(
                ip=request.remote or "",
                via_cloud=is_cloud_connection(self.hass),
                user_agent=request.headers.get(hdrs.USER_AGENT),
                touch=body.get("touch") is True,
                client_id=client_id,
            )
        except BeamInError as err:
            return await self.error(request, err)
        beam = new.request
        return self.json(
            {
                "request_id": beam.request_id,
                "secret": new.secret,
                "code": format_code(beam.code),
                "match_number": beam.match_number,
                "qr_svg": make_qr_svg(manager.approval_url(beam.code, client_id)),
                "expires_in": manager.request_ttl,
                "expires_at": int(beam.expires_at),
                "poll_interval": POLL_INTERVAL,
            },
            headers=NO_STORE,
        )


class PollView(BeamInView):
    """Let the requesting device follow its request (secret-bound)."""

    url = f"{API_URL}/poll"
    name = "beamin:poll"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        """Return the status, and the tokens once approved."""
        try:
            manager = self.manager()
            body = await read_json(request)
            result = await manager.async_poll(
                body.get("request_id"),
                body.get("secret"),
                ip=request.remote or "",
                via_cloud=is_cloud_connection(self.hass),
            )
        except BeamInError as err:
            return await self.error(request, err)
        return self.json(result, headers=NO_STORE)


class PendingView(BeamInView):
    """Show a pending request on the approver's phone (read-only)."""

    url = f"{API_URL}/pending/{{code}}"
    name = "beamin:pending"

    async def get(self, request: web.Request, code: str) -> web.Response:
        """Return what the approval screen needs."""
        try:
            manager = self.manager()
            approver = self.approver(request, manager)
            beam = manager.async_find(approver, code)
            targets = await async_sign_in_targets(self.hass, approver)
        except BeamInError as err:
            return await self.error(request, err)
        return self.json(
            describe_request(
                beam,
                approver,
                targets,
                approver_ip=request.remote,
                temporary_minutes=manager.temporary_minutes,
            ),
            headers=NO_STORE,
        )


class ApproveView(BeamInView):
    """Approve a request: authenticated POST with an explicit choice only."""

    url = f"{API_URL}/approve"
    name = "beamin:approve"

    async def post(self, request: web.Request) -> web.Response:
        """Approve after number matching and privilege checks."""
        try:
            manager = self.manager()
            approver = self.approver(request, manager)
            body = await read_json(request)
            beam, target = await manager.async_approve(
                approver,
                code=body.get("code"),
                match_choice=body.get("match_choice"),
                duration=body.get("duration", DURATION_NORMAL),
                target_user_id=body.get("target_user_id"),
            )
        except BeamInError as err:
            return await self.error(request, err)
        return self.json(
            {"status": "approved", "device": beam.device.label, "user": target.name},
            headers=NO_STORE,
        )


class DenyView(BeamInView):
    """Deny a request."""

    url = f"{API_URL}/deny"
    name = "beamin:deny"

    async def post(self, request: web.Request) -> web.Response:
        """Deny the request matching the code."""
        try:
            manager = self.manager()
            approver = self.approver(request, manager)
            body = await read_json(request)
            manager.async_deny(approver, body.get("code"))
        except BeamInError as err:
            return await self.error(request, err)
        return self.json({"status": "denied"}, headers=NO_STORE)
