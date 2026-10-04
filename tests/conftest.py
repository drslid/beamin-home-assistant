"""Shared fixtures for the BeamIn tests."""

from __future__ import annotations

from collections.abc import Generator
from socket import herror
from unittest.mock import patch

from aiohttp.test_utils import TestClient
from homeassistant.components.http.config import DATA_STORE as HTTP_CONFIG_STORE
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.beamin.const import DOMAIN

HTTP_CONFIG = {
    # Lets tests pick the client address with X-Forwarded-For.
    "use_x_forwarded_for": True,
    "trusted_proxies": ["127.0.0.1", "::1"],
    "ip_ban_enabled": True,
    "login_attempts_threshold": 3,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration from custom_components."""


@pytest.fixture
def hass_config_dir(hass_tmp_config_dir: str) -> str:
    """Write ip_bans.yaml and friends to a temporary directory."""
    return hass_tmp_config_dir


@pytest.fixture(autouse=True)
def no_reverse_dns() -> Generator[None]:
    """Keep the IP ban code from resolving test addresses."""
    with patch("homeassistant.components.http.ban.gethostbyaddr", side_effect=herror):
        yield


@pytest.fixture
def options() -> dict[str, object]:
    """Return the config entry options (override per test)."""
    return {}


@pytest.fixture
async def entry(hass: HomeAssistant, options: dict[str, object]) -> MockConfigEntry:
    """Set up HTTP and a loaded BeamIn config entry."""
    assert await async_setup_component(hass, "http", {"http": HTTP_CONFIG})
    # YAML HTTP settings are a 5-minute trial that restarts Home Assistant
    # unless confirmed; tests that move time forward would trigger it.
    await hass.data[HTTP_CONFIG_STORE].async_promote_pending()
    config_entry = MockConfigEntry(
        domain=DOMAIN, title="BeamIn", data={}, options=options
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


@pytest.fixture
async def client(
    entry: MockConfigEntry, hass_client_no_auth: ClientSessionGenerator
) -> TestClient:
    """Return an HTTP client; tests add auth and address headers per request."""
    return await hass_client_no_auth()
