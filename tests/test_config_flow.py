"""Config and options flows."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.network import NoURLAvailableError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.beamin.config_flow import normalize_public_url
from custom_components.beamin.const import (
    CONF_PUBLIC_URL,
    CONF_REQUEST_TTL,
    CONF_SHOW_IN_SIDEBAR,
    CONF_TEMPORARY_MINUTES,
    DOMAIN,
)

TRANSLATIONS = Path(__file__).parents[1] / "custom_components/beamin/translations"


async def test_user_flow_creates_single_entry(hass: HomeAssistant) -> None:
    """One confirmation creates the entry; a second flow aborts."""
    with patch("custom_components.beamin.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "BeamIn"
        assert result["data"] == {}

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_user_flow_shows_this_instance_url(hass: HomeAssistant) -> None:
    """The setup step shows the address to bookmark on the new device."""
    await hass.config.async_update(external_url="https://home.example.net")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["description_placeholders"] == {
        "beam_url": "https://home.example.net/beam"
    }


async def test_user_flow_without_any_url(hass: HomeAssistant) -> None:
    """Without a known URL, the setup step shows the usual local address."""
    with patch(
        "custom_components.beamin.config_flow.get_url",
        side_effect=NoURLAvailableError,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
    assert result["description_placeholders"] == {
        "beam_url": "http://homeassistant.local:8123/beam"
    }


async def test_options_flow(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Options are validated and normalized."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    user_input = {
        CONF_REQUEST_TTL: 90.0,
        CONF_TEMPORARY_MINUTES: 30.0,
        CONF_PUBLIC_URL: "https://ha.example.com/lovelace",
        CONF_SHOW_IN_SIDEBAR: False,
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_PUBLIC_URL: "invalid_url"}

    user_input[CONF_PUBLIC_URL] = " HTTPS://HA.Example.com:8443/ "
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        CONF_REQUEST_TTL: 90,
        CONF_TEMPORARY_MINUTES: 30,
        CONF_PUBLIC_URL: "https://ha.example.com:8443",
        CONF_SHOW_IN_SIDEBAR: False,
    }


async def test_options_flow_clears_url(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """An empty URL falls back to Home Assistant's own URLs."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_REQUEST_TTL: 120, CONF_TEMPORARY_MINUTES: 60, CONF_SHOW_IN_SIDEBAR: True},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_PUBLIC_URL] == ""


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://ha.example.com", "https://ha.example.com"),
        ("http://192.168.1.2:8123/", "http://192.168.1.2:8123"),
        ("ha.example.com", None),
        ("ftp://ha.example.com", None),
        ("https://user@ha.example.com", None),
        ("https://ha.example.com/?a=1", None),
        ("https://ha.example.com:port", None),
        ("https://", None),
    ],
)
def test_normalize_public_url(value: str, expected: str | None) -> None:
    """Only bare http(s) origins are accepted."""
    assert normalize_public_url(value) == expected


def test_translations_match() -> None:
    """French covers exactly the English keys."""

    def keys(node: object, prefix: str = "") -> set[str]:
        if isinstance(node, dict):
            return {
                k for key, value in node.items() for k in keys(value, f"{prefix}{key}.")
            }
        return {prefix}

    english = json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8"))
    french = json.loads((TRANSLATIONS / "fr.json").read_text(encoding="utf-8"))
    assert keys(french) == keys(english)
