"""Number: target grid power."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberMode, RestoreNumber
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZendureControlConfigEntry
from .entity import ZendureControlEntity


async def async_setup_entry(_hass: HomeAssistant, entry: ZendureControlConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([TargetNumber(entry.runtime_data, "target_power")])


class TargetNumber(ZendureControlEntity, RestoreNumber):
    """Grid power the regulation aims for (positive = small import)."""

    _attr_device_class = NumberDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_native_min_value = -200
    _attr_native_max_value = 200
    _attr_native_step = 5
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:target"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (data := await self.async_get_last_number_data()) is not None and data.native_value is not None:
            self.controller.target = int(data.native_value)

    @property
    def native_value(self) -> float:
        return self.controller.target

    async def async_set_native_value(self, value: float) -> None:
        self.controller.target = int(value)
        self.async_write_ha_state()
