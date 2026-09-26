"""Switch: regulation on/off."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import ZendureControlConfigEntry
from .entity import ZendureControlEntity


async def async_setup_entry(_hass: HomeAssistant, entry: ZendureControlConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([ActiveSwitch(entry.runtime_data, "active")])


class ActiveSwitch(ZendureControlEntity, SwitchEntity, RestoreEntity):
    """Regulation active."""

    _attr_icon = "mdi:auto-mode"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None and state.state == "on":
            await self.controller.async_set_enabled(True)

    @property
    def is_on(self) -> bool:
        return self.controller.enabled

    async def async_turn_on(self, **_kwargs: Any) -> None:
        await self.controller.async_set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **_kwargs: Any) -> None:
        await self.controller.async_set_enabled(False)
        self.async_write_ha_state()
