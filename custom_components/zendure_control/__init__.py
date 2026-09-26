"""Zendure Regelung: eigenständige Nulleinspeise-Regelung für Geräte der Zendure-Integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import CoreState, Event, HomeAssistant

from .controller import ZendureController

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SELECT, Platform.SENSOR, Platform.SWITCH]

type ZendureControlConfigEntry = ConfigEntry[ZendureController]


async def async_setup_entry(hass: HomeAssistant, entry: ZendureControlConfigEntry) -> bool:
    """Set up Zendure Regelung."""
    controller = ZendureController(hass, entry)
    controller.rediscover()
    entry.runtime_data = controller

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _start(_event: Event | None = None) -> None:
        await controller.async_start()

    # the Zendure integration must be loaded first, so wait for Home Assistant to be started
    if hass.state is CoreState.running:
        await _start()
    else:
        entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _start))

    entry.async_on_unload(entry.add_update_listener(_update_listener))
    return True


async def _update_listener(hass: HomeAssistant, entry: ZendureControlConfigEntry) -> None:
    """Reload on option changes."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ZendureControlConfigEntry) -> bool:
    """Unload Zendure Regelung."""
    await entry.runtime_data.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
