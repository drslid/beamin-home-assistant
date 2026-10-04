"""Setup, unload, panel, static files and the QR link."""

from __future__ import annotations

from unittest.mock import patch

from aiohttp.test_utils import TestClient
from homeassistant.components.frontend import DATA_PANELS
from homeassistant.core import HomeAssistant
from homeassistant.helpers import network
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, MockUser

from custom_components.beamin.const import (
    CONF_PUBLIC_URL,
    CONF_SHOW_IN_SIDEBAR,
    DATA_MANAGER,
)
from custom_components.beamin.views import make_qr_svg

from .common import PHONE_IP, access_token, create, create_ok, headers, pending

STATIC = "/beamin_static/0.1.0"


async def test_panel_and_static_files(
    hass: HomeAssistant, client: TestClient, entry: MockConfigEntry
) -> None:
    """The panel is in the sidebar for everyone; files come from a versioned path."""
    panel = hass.data[DATA_PANELS]["beamin"]
    assert panel.sidebar_title == "BeamIn"
    assert panel.sidebar_icon == "mdi:qrcode-scan"
    assert panel.require_admin is False
    assert panel.config["_panel_custom"]["module_url"] == f"{STATIC}/beamin-panel.js"

    html = await (await client.get("/beam")).text()
    assert f'src="{STATIC}/beam.js"' in html
    assert f'href="{STATIC}/beam.css"' in html
    assert "__STATIC__" not in html
    for name in ("beam.js", "beam.css", "i18n.js", "beamin-panel.js"):
        response = await client.get(f"{STATIC}/{name}")
        assert response.status == 200, name


@pytest.mark.parametrize("options", [{CONF_SHOW_IN_SIDEBAR: False}])
async def test_panel_hidden_from_sidebar(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Hiding the panel keeps it reachable by URL (the QR code link)."""
    panel = hass.data[DATA_PANELS]["beamin"]
    assert panel.sidebar_title is None
    assert panel.sidebar_icon is None


async def test_unload_stops_everything(
    hass: HomeAssistant, client: TestClient, entry: MockConfigEntry
) -> None:
    """After unload the views answer 404 and the panel is gone; reload restores."""
    await create_ok(client)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert "beamin" not in hass.data[DATA_PANELS]
    assert DATA_MANAGER not in hass.data
    assert (await client.get("/beam")).status == 404
    response = await create(client)
    assert response.status == 404
    assert (await response.json())["code"] == "unavailable"

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert "beamin" in hass.data[DATA_PANELS]
    assert (await client.get("/beam")).status == 200


async def test_options_update_reloads(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Changing options reloads the entry with the new settings."""
    hass.config_entries.async_update_entry(
        entry,
        options={CONF_SHOW_IN_SIDEBAR: False, CONF_PUBLIC_URL: "https://x.example"},
    )
    await hass.async_block_till_done()
    assert hass.data[DATA_PANELS]["beamin"].sidebar_title is None
    assert hass.data[DATA_MANAGER].public_url == "https://x.example"


async def _qr_url(client: TestClient) -> str:
    with patch(
        "custom_components.beamin.views.make_qr_svg", side_effect=make_qr_svg
    ) as qr:
        await create_ok(client)
    url: str = qr.call_args.args[0]
    return url


@pytest.mark.parametrize("options", [{CONF_PUBLIC_URL: "https://ha.example.org:8443"}])
async def test_qr_uses_public_url_option(
    hass: HomeAssistant, client: TestClient
) -> None:
    """The configured public URL wins."""
    url = await _qr_url(client)
    assert url.startswith("https://ha.example.org:8443/beamin?code=")
    assert len(url.rsplit("=", 1)[1]) == 6


async def test_qr_prefers_external_url(hass: HomeAssistant, client: TestClient) -> None:
    """Without an option, the external URL is used."""
    await hass.config.async_update(
        external_url="https://home.example.net", internal_url="http://192.168.1.2:8123"
    )
    assert (await _qr_url(client)).startswith("https://home.example.net/beamin?code=")


async def test_qr_falls_back_to_page_origin(
    hass: HomeAssistant, client: TestClient
) -> None:
    """Without any configured URL, the origin the device used is encoded."""
    with patch(
        "custom_components.beamin.manager.get_url",
        side_effect=network.NoURLAvailableError,
    ):
        url = await _qr_url(client)
    assert url.startswith("https://ha.example.com/beamin?code=")


def test_qr_svg_is_self_contained() -> None:
    """The QR code is pure SVG with no external reference."""
    svg = make_qr_svg("https://ha.example.com/beamin?code=K7F29X")
    assert svg.startswith("<svg")
    assert 'xmlns="http://www.w3.org/2000/svg"' in svg
    assert "viewBox" in svg
    assert "href" not in svg
    assert "<script" not in svg


@pytest.mark.parametrize(
    ("device_ip", "via_cloud", "network_type"),
    [
        ("192.168.1.20", False, "local"),
        (PHONE_IP, False, "same_public_ip"),
        ("203.0.113.99", True, "cloud"),
    ],
)
async def test_network_shown_to_approver(
    hass: HomeAssistant,
    client: TestClient,
    hass_admin_user: MockUser,
    device_ip: str,
    via_cloud: bool,
    network_type: str,
) -> None:
    """The approver sees where the device connects from."""
    token, _ = await access_token(hass, hass_admin_user)
    with patch(
        "custom_components.beamin.views.is_cloud_connection", return_value=via_cloud
    ):
        request = await create_ok(client, ip=device_ip)
    screen = await (await pending(client, request["code"], token)).json()
    assert screen["network"] == network_type
    assert screen["age"] == 0
    assert screen["expires_in"] == 120


async def test_errors_are_not_cacheable(
    hass: HomeAssistant, client: TestClient
) -> None:
    """API errors are not cacheable either."""
    response = await client.post(
        "/api/beamin/poll",
        json={"request_id": "x", "secret": "y"},
        headers=headers("203.0.113.1"),
    )
    assert response.status == 404
    assert response.headers["Cache-Control"] == "no-store"
