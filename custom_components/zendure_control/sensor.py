"""Sensors of Zendure Regelung."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZendureControlConfigEntry
from .entity import ZendureControlEntity


async def async_setup_entry(_hass: HomeAssistant, entry: ZendureControlConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    controller = entry.runtime_data
    entities: list[SensorEntity] = [
        DemandSensor(controller, "demand"),
        GridSensor(controller, "grid_power"),
        DecisionSensor(controller, "decision"),
    ]
    for binding in controller.bindings.values():
        entities.append(RequestedSensor(controller, "requested_power", binding))
        entities.append(StatusSensor(controller, "device_status", binding))
    async_add_entities(entities)


class _PowerSensor(ZendureControlEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT


class DemandSensor(_PowerSensor):
    """Total AC power the devices should deliver (negative = charge)."""

    _attr_icon = "mdi:target"

    @property
    def native_value(self) -> int | None:
        return self.controller.decision.demand if self.controller.decision is not None else None


class GridSensor(_PowerSensor):
    """Grid power used for the last regulation step."""

    _attr_icon = "mdi:transmission-tower"

    @property
    def native_value(self) -> int | None:
        return self.controller.p1

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        age = self.controller.p1_age
        return {"alter_s": round(age, 1) if age is not None else None, "quelle": self.controller.p1_entity}


class DecisionSensor(ZendureControlEntity, SensorEntity):
    """Text of the last decision."""

    _attr_icon = "mdi:text-box-outline"

    @property
    def native_value(self) -> str:
        return self.controller.decision_text[:250]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self.controller
        commands = {}
        if c.decision is not None:
            commands = {b.name: c.decision.commands.get(b.key, 0) for b in c.bindings.values()}
        return {
            "befehle": commands,
            "modus": c.mode,
            "ziel_w": c.target,
            "halten": c.decision.hold if c.decision is not None else None,
            "steuerung": {b.name: ("Treiber" if c._use_driver(b) else "Entitäten") for b in c.bindings.values()},  # noqa: SLF001
        }


class RequestedSensor(_PowerSensor):
    """Last power requested from one device."""

    _attr_icon = "mdi:arrow-decision-outline"

    @property
    def native_value(self) -> int | None:
        return self.binding.cmd if self.binding is not None else None


class StatusSensor(ZendureControlEntity, SensorEntity):
    """Status of one device from the regulation's point of view."""

    _attr_icon = "mdi:battery-sync-outline"

    @property
    def native_value(self) -> str:
        return self.binding.note if self.binding is not None else ""

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        b = self.binding
        if b is None or b.last_input is None:
            return {}
        d = b.last_input
        return {"ist_w": d.net, "soll_w": b.cmd, "soc": d.soc, "solar_w": d.solar, "bypass": d.bypass, "online": d.online}
