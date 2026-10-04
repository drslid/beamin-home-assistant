"""BeamIn: sign in to Home Assistant on any device by approving it from your phone."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .auth_helpers import TemporarySessions
from .const import (
    CONF_PUBLIC_URL,
    CONF_REQUEST_TTL,
    CONF_SHOW_IN_SIDEBAR,
    CONF_TEMPORARY_MINUTES,
    DATA_MANAGER,
    DATA_SESSIONS,
    DEFAULT_REQUEST_TTL,
    DEFAULT_SHOW_IN_SIDEBAR,
    DEFAULT_TEMPORARY_MINUTES,
    DOMAIN,
    NAME,
    PANEL_COMPONENT,
    PANEL_ICON,
    PANEL_URL_PATH,
    STATIC_URL,
)
from .manager import BeamInManager
from .views import (
    ApproveView,
    BeamPageView,
    DenyView,
    PendingView,
    PollView,
    RequestView,
)

type BeamInConfigEntry = ConfigEntry[BeamInManager]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
FRONTEND_DIR = Path(__file__).parent / "frontend"


def _render_page(static_url: str) -> str:
    return (
        (FRONTEND_DIR / "beam.html")
        .read_text(encoding="utf-8")
        .replace("__STATIC__", static_url)
    )


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the views and files once, and resume temporary-session revocation.

    Views and static paths cannot be unregistered: they answer 404 while no
    config entry is loaded. Revocation is not tied to the entry, so a reload
    never delays it.
    """
    integration = await async_get_integration(hass, DOMAIN)
    # A versioned path lets browsers cache the files and still get updates.
    static_url = f"{STATIC_URL}/{integration.version}"
    html = await hass.async_add_executor_job(_render_page, static_url)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(static_url, str(FRONTEND_DIR), cache_headers=True)]
    )
    hass.http.register_view(BeamPageView(hass, html))
    for view in (RequestView, PollView, PendingView, ApproveView, DenyView):
        hass.http.register_view(view(hass))

    sessions = TemporarySessions(hass)
    await sessions.async_load()
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, sessions.async_stop)
    hass.data[DATA_SESSIONS] = sessions
    return True


async def async_setup_entry(hass: HomeAssistant, entry: BeamInConfigEntry) -> bool:
    """Start accepting sign-in requests and show the approval panel."""
    options = entry.options
    manager = BeamInManager(
        hass,
        hass.data[DATA_SESSIONS],
        request_ttl=int(options.get(CONF_REQUEST_TTL, DEFAULT_REQUEST_TTL)),
        temporary_minutes=int(
            options.get(CONF_TEMPORARY_MINUTES, DEFAULT_TEMPORARY_MINUTES)
        ),
        public_url=options.get(CONF_PUBLIC_URL) or None,
    )
    entry.runtime_data = manager
    hass.data[DATA_MANAGER] = manager

    integration = await async_get_integration(hass, DOMAIN)
    show = options.get(CONF_SHOW_IN_SIDEBAR, DEFAULT_SHOW_IN_SIDEBAR)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_COMPONENT,
        # Without a title the panel leaves the sidebar but stays reachable by URL.
        sidebar_title=NAME if show else None,
        sidebar_icon=PANEL_ICON if show else None,
        module_url=f"{STATIC_URL}/{integration.version}/beamin-panel.js",
        require_admin=False,
    )
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: BeamInConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: BeamInConfigEntry) -> bool:
    """Stop accepting requests and remove the panel."""
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    entry.runtime_data.async_stop()
    hass.data.pop(DATA_MANAGER, None)
    if entry.disabled_by is not None:
        # Fail safe: a disabled integration must not leave temporary sessions alive.
        hass.data[DATA_SESSIONS].async_revoke_all()
    return True


async def async_remove_entry(hass: HomeAssistant, entry: BeamInConfigEntry) -> None:
    """Revoke every temporary session and forget the schedule."""
    if (sessions := hass.data.get(DATA_SESSIONS)) is None:
        sessions = TemporarySessions(hass)
        await sessions.async_load()
    sessions.async_revoke_all()
    sessions.async_stop()
    await sessions.async_remove_store()
