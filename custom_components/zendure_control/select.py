"""Select: regulation mode."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import ZendureControlConfigEntry
from .const import MODES
from .entity import ZendureControlEntity


async def async_setup_entry(_hass: HomeAssistant, entry: ZendureControlConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([ModeSelect(entry.runtime_data, "mode")])


class ModeSelect(ZendureControlEntity, SelectEntity, RestoreEntity):
    """Regulation mode."""

    _attr_options = MODES
    _attr_icon = "mdi:tune-variant"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None and state.state in MODES:
            self.controller.mode = state.state

    @property
    def current_option(self) -> str:
        return self.controller.mode

    async def async_select_option(self, option: str) -> None:
        self.controller.mode = option
        self.controller.regulator.export_since = None
        self.async_write_ha_state()
