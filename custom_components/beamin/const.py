"""Constants for BeamIn."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from homeassistant.util.hass_dict import HassKey

if TYPE_CHECKING:
    from .auth_helpers import TemporarySessions
    from .manager import BeamInManager

DOMAIN: Final = "beamin"
NAME: Final = "BeamIn"

# Present only while the config entry is loaded; the views answer 404 otherwise.
DATA_MANAGER: HassKey[BeamInManager] = HassKey(DOMAIN)
DATA_SESSIONS: HassKey[TemporarySessions] = HassKey(f"{DOMAIN}_sessions")

CONF_REQUEST_TTL: Final = "request_ttl"
CONF_TEMPORARY_MINUTES: Final = "temporary_minutes"
CONF_PUBLIC_URL: Final = "public_url"
CONF_SHOW_IN_SIDEBAR: Final = "show_in_sidebar"

DEFAULT_REQUEST_TTL: Final = 120
MIN_REQUEST_TTL: Final = 60
MAX_REQUEST_TTL: Final = 300
DEFAULT_TEMPORARY_MINUTES: Final = 60
MIN_TEMPORARY_MINUTES: Final = 5
MAX_TEMPORARY_MINUTES: Final = 1440
DEFAULT_SHOW_IN_SIDEBAR: Final = True

# No 0/O, 1/I/L: the code must survive being read aloud or typed on a TV remote.
CODE_ALPHABET: Final = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH: Final = 6
MATCH_MIN: Final = 10
MATCH_MAX: Final = 99
MATCH_CHOICES: Final = 3

MAX_PENDING_TOTAL: Final = 10
MAX_PENDING_PER_IP: Final = 3
PAGE_RATE_LIMIT: Final = 30
PAGE_RATE_WINDOW: Final = 60.0
CREATE_RATE_LIMIT: Final = 6
CREATE_RATE_WINDOW: Final = 60.0
POLL_RATE_LIMIT: Final = 120
POLL_RATE_WINDOW: Final = 60.0
POLL_INTERVAL: Final = 2
APPROVER_MAX_FAILURES: Final = 5
APPROVER_FAILURE_WINDOW: Final = 300.0
APPROVER_LOCKOUT: Final = 300.0

BEAM_PAGE_URL: Final = "/beam"
STATIC_URL: Final = "/beamin_static"
API_URL: Final = "/api/beamin"
PANEL_URL_PATH: Final = "beamin"
PANEL_COMPONENT: Final = "beamin-panel"
PANEL_ICON: Final = "mdi:qrcode-scan"

EVENT_REQUESTED: Final = "beamin_login_requested"
EVENT_APPROVED: Final = "beamin_login_approved"
EVENT_DENIED: Final = "beamin_login_denied"
EVENT_EXPIRED: Final = "beamin_login_expired"

DURATION_NORMAL: Final = "normal"
DURATION_TEMPORARY: Final = "temporary"

STORAGE_KEY: Final = "beamin.temporary_sessions"
STORAGE_VERSION: Final = 1

CLIENT_NAME_PREFIX: Final = "BeamIn – "  # noqa: RUF001 - deliberate en dash
