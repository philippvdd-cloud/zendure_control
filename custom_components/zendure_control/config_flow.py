"""Config flow for Zendure Regelung."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import COMMAND_AUTO, COMMAND_MODES, CONF_COMMAND_MODE, CONF_EXCLUDED, CONF_P1_SENSOR, DOMAIN, SOURCE_DOMAIN
from .controller import discover_devices


def _schema(hass: Any, defaults: dict[str, Any], with_devices: bool) -> vol.Schema:
    fields: dict[Any, Any] = {
        vol.Required(CONF_P1_SENSOR, default=defaults.get(CONF_P1_SENSOR, vol.UNDEFINED)): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor", device_class="power")
        ),
        vol.Required(CONF_COMMAND_MODE, default=defaults.get(CONF_COMMAND_MODE, COMMAND_AUTO)): selector.SelectSelector(
            selector.SelectSelectorConfig(options=COMMAND_MODES, translation_key=CONF_COMMAND_MODE, mode=selector.SelectSelectorMode.DROPDOWN)
        ),
    }
    if with_devices:
        names = sorted(b.name for b in discover_devices(hass)[0].values())
        fields[vol.Optional(CONF_EXCLUDED, default=defaults.get(CONF_EXCLUDED, []))] = selector.SelectSelector(
            selector.SelectSelectorConfig(options=names, multiple=True, mode=selector.SelectSelectorMode.LIST)
        )
    return vol.Schema(fields)


class ZendureControlConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the setup."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        if not self.hass.config_entries.async_entries(SOURCE_DOMAIN):
            return self.async_abort(reason="no_source")
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title="Zendure Regelung", data=user_input)
        return self.async_show_form(step_id="user", data_schema=_schema(self.hass, {}, with_devices=False))

    @staticmethod
    @callback
    def async_get_options_flow(_config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return ZendureControlOptionsFlow()


class ZendureControlOptionsFlow(config_entries.OptionsFlow):
    """Change P1 sensor, command mode and excluded devices."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        defaults = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_schema(self.hass, defaults, with_devices=True))
