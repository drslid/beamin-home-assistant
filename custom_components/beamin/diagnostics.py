"""Diagnostics for BeamIn: counters and options only, never secrets."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import BeamInConfigEntry
from .const import CONF_PUBLIC_URL


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BeamInConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the config entry."""
    return {
        "options": async_redact_data(dict(entry.options), {CONF_PUBLIC_URL}),
        "state": entry.runtime_data.diagnostics(),
    }
