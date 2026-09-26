"""Base entity of Zendure Regelung."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, SIGNAL_UPDATE
from .controller import Binding, ZendureController


class ZendureControlEntity(Entity):
    """Common base: one device "Zendure Regelung", updates via dispatcher."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller: ZendureController, key: str, binding: Binding | None = None) -> None:
        self.controller = controller
        self.binding = binding
        self._attr_translation_key = key
        suffix = f"{binding.key}_{key}" if binding is not None else key
        self._attr_unique_id = f"{DOMAIN}_{suffix}"
        if binding is not None:
            self._attr_translation_placeholders = {"device": binding.name}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, controller.entry.entry_id)},
            name="Zendure Regelung",
            manufacturer="Eigenbau",
            model="Nulleinspeise-Regelung",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_UPDATE, self.async_write_ha_state))
