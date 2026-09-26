"""Binary sensors of Zendure Regelung."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZendureControlConfigEntry
from .entity import ZendureControlEntity


async def async_setup_entry(_hass: HomeAssistant, entry: ZendureControlConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    controller = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        StaleSensor(controller, "p1_stale"),
        BlockedSensor(controller, "blocked"),
    ]
    entities.extend(NotFollowingSensor(controller, "not_following", b) for b in controller.bindings.values())
    async_add_entities(entities)


class StaleSensor(ZendureControlEntity, BinarySensorEntity):
    """P1 sensor is stale, regulation paused."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool:
        return self.controller.p1_stale


class BlockedSensor(ZendureControlEntity, BinarySensorEntity):
    """Zendure manager still controls the devices."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool:
        return self.controller.blocked


class NotFollowingSensor(ZendureControlEntity, BinarySensorEntity):
    """Device does not deliver the requested power."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool:
        return self.binding.not_following if self.binding is not None else False
