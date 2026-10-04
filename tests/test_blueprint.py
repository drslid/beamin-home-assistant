"""The notification blueprint."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint.models import Blueprint, BlueprintInputs
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.template import Template
from homeassistant.util import dt as dt_util
from homeassistant.util.yaml import load_yaml_dict

BLUEPRINT = (
    Path(__file__).parents[1] / "blueprints/automation/beamin/notify_new_login.yaml"
)


def _substitute() -> dict[str, Any]:
    blueprint = Blueprint(
        load_yaml_dict(BLUEPRINT),
        expected_domain="automation",
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )
    inputs = BlueprintInputs(
        blueprint,
        {
            "use_blueprint": {
                "path": "beamin/notify_new_login.yaml",
                "input": {"notify_device": "phone-device-id"},
            }
        },
    )
    inputs.validate()
    config: dict[str, Any] = inputs.async_substitute()
    return config


def _render(hass: HomeAssistant, config: dict[str, Any], data: dict[str, Any]) -> str:
    fired = dt_util.as_utc(
        datetime(2026, 10, 4, 19, 31, tzinfo=dt_util.get_default_time_zone())
    )
    trigger = {
        "event": Event(
            "beamin_login_approved", data, time_fired_timestamp=fired.timestamp()
        )
    }
    variables: dict[str, Any] = {"trigger": trigger}
    for name, template in config["variables"].items():
        variables[name] = Template(template, hass).async_render(variables)
    action = config["actions"][0]
    return str(Template(action["message"], hass).async_render(variables))


async def test_blueprint_is_valid(hass: HomeAssistant) -> None:
    """The blueprint validates and its action is a mobile_app notification."""
    config = _substitute()
    assert config["triggers"] == [
        {"trigger": "event", "event_type": "beamin_login_approved"}
    ]
    (action,) = cv.SCRIPT_SCHEMA(config["actions"])
    assert action["domain"] == "mobile_app"
    assert action["type"] == "notify"
    assert action["device_id"] == "phone-device-id"
    assert action["data"] == {
        "url": "/profile/security",
        "clickAction": "/profile/security",
    }


async def test_blueprint_message(hass: HomeAssistant) -> None:
    """The message reads like the README example."""
    await hass.config.async_set_time_zone("Europe/Paris")
    config = _substitute()
    data = {
        "device": "Tesla browser",
        "target_user_name": "Julien",
        "ip": "203.0.113.10",
        "duration": "normal",
    }
    assert _render(hass, config, data) == (
        "Tesla browser signed in as Julien at 19:31 from 203.0.113.10. "
        "Tap to review or revoke."
    )
    data["duration"] = "temporary"
    assert "19:31 (temporary session) from" in _render(hass, config, data)
