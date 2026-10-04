"""Config flow for BeamIn: one click to add, options for the details."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from .const import (
    BEAM_PAGE_URL,
    CONF_PUBLIC_URL,
    CONF_REQUEST_TTL,
    CONF_SHOW_IN_SIDEBAR,
    CONF_TEMPORARY_MINUTES,
    DEFAULT_REQUEST_TTL,
    DEFAULT_SHOW_IN_SIDEBAR,
    DEFAULT_TEMPORARY_MINUTES,
    DOMAIN,
    MAX_REQUEST_TTL,
    MAX_TEMPORARY_MINUTES,
    MIN_REQUEST_TTL,
    MIN_TEMPORARY_MINUTES,
    NAME,
)


def normalize_public_url(value: str) -> str | None:
    """Return "scheme://host[:port]" or None if the value is not such a URL."""
    try:
        parts = urlsplit(value.strip())
        _ = parts.port
    except ValueError:
        return None
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
    ):
        return None
    return f"{parts.scheme}://{parts.netloc.lower()}"


class BeamInConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add BeamIn (single instance, nothing to fill in)."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the setup."""
        if user_input is not None:
            return self.async_create_entry(title=NAME, data={})
        try:
            base_url = get_url(self.hass, prefer_external=True)
        except NoURLAvailableError:
            base_url = "http://homeassistant.local:8123"
        return self.async_show_form(
            step_id="user",
            description_placeholders={"beam_url": f"{base_url}{BEAM_PAGE_URL}"},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> BeamInOptionsFlow:
        """Return the options flow."""
        return BeamInOptionsFlow()


class BeamInOptionsFlow(OptionsFlow):
    """Tune request lifetime, temporary sessions, QR URL and sidebar entry."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and save the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            public_url = ""
            if raw_url := str(user_input.get(CONF_PUBLIC_URL) or "").strip():
                public_url = normalize_public_url(raw_url) or ""
                if not public_url:
                    errors[CONF_PUBLIC_URL] = "invalid_url"
            if not errors:
                return self.async_create_entry(
                    data={
                        CONF_REQUEST_TTL: int(user_input[CONF_REQUEST_TTL]),
                        CONF_TEMPORARY_MINUTES: int(user_input[CONF_TEMPORARY_MINUTES]),
                        CONF_PUBLIC_URL: public_url,
                        CONF_SHOW_IN_SIDEBAR: bool(user_input[CONF_SHOW_IN_SIDEBAR]),
                    }
                )

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_REQUEST_TTL,
                    default=options.get(CONF_REQUEST_TTL, DEFAULT_REQUEST_TTL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_REQUEST_TTL,
                        max=MAX_REQUEST_TTL,
                        step=10,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_TEMPORARY_MINUTES,
                    default=options.get(
                        CONF_TEMPORARY_MINUTES, DEFAULT_TEMPORARY_MINUTES
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_TEMPORARY_MINUTES,
                        max=MAX_TEMPORARY_MINUTES,
                        step=5,
                        unit_of_measurement="min",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_PUBLIC_URL,
                    description={"suggested_value": options.get(CONF_PUBLIC_URL, "")},
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
                vol.Required(
                    CONF_SHOW_IN_SIDEBAR,
                    default=options.get(CONF_SHOW_IN_SIDEBAR, DEFAULT_SHOW_IN_SIDEBAR),
                ): BooleanSelector(),
            }
        )
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders={"example_url": "https://ha.example.com"},
        )
