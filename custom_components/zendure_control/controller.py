"""Controller of Zendure Regelung: reads the Zendure entities, runs the regulator, sends commands."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    COMMAND_AUTO,
    COMMAND_DRIVER,
    COMMAND_ENTITIES,
    COMMAND_REFRESH,
    CONF_COMMAND_MODE,
    CONF_EXCLUDED,
    CONF_P1_SENSOR,
    DISCOVERY_INTERVAL,
    DOMAIN,
    DRIVER_TOLERANCE,
    ENTITY_MIN_INTERVAL,
    ENTITY_TOLERANCE,
    MIN_INTERVAL,
    MODE_MATCHING,
    P1_STALE_AGE,
    P1_STALE_STOP,
    SIGNAL_UPDATE,
    SOLAR_MIN,
    SOURCE_DOMAIN,
    UNRESPONSIVE_TIME,
    VERIFY_TIME,
    VERIFY_TOLERANCE_MIN,
    VERIFY_TOLERANCE_REL,
    WATCHDOG_INTERVAL,
    WATCHDOG_MAXAGE,
)
from .regulator import Decision, DeviceInput, Regulator

_LOGGER = logging.getLogger(__name__)

# translation keys of the Zendure (FireSon) integration entities that are used
WANTED_KEYS = {
    "output_home_power",
    "grid_input_power",
    "solar_input_power",
    "electric_level",
    "min_soc",
    "soc_set",
    "pass",
    "output_limit",
    "input_limit",
    "ac_mode",
    "connection_status",
}
MANAGER_OPERATION_KEY = "operation"


@dataclass
class Binding:
    """One Zendure device and everything the controller knows about it."""

    key: str
    name: str
    entities: dict[str, str]
    driver: Any | None = None
    cmd: int | None = None
    cmd_time: float = 0.0
    sent: int | None = None
    sent_time: float = 0.0
    unresponsive_until: float = 0.0
    not_following: bool = False
    note: str = "unbekannt"
    last_input: DeviceInput | None = field(default=None, repr=False)


def discover_devices(hass: HomeAssistant) -> tuple[dict[str, Binding], str | None]:
    """Find all Zendure devices and the operation select of the Zendure manager."""
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    found: dict[str, dict[str, str]] = {}
    operation_entity: str | None = None
    drivers: dict[str, Any] = {}

    for entry in hass.config_entries.async_entries(SOURCE_DOMAIN):
        manager = getattr(entry, "runtime_data", None)
        for drv in getattr(manager, "devices", None) or []:
            if (name := getattr(drv, "name", None)) is not None:
                drivers[name] = drv

        for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
            if reg_entry.disabled_by is not None or reg_entry.device_id is None:
                continue
            key = reg_entry.translation_key
            if key == MANAGER_OPERATION_KEY and reg_entry.domain == "select":
                operation_entity = reg_entry.entity_id
            elif key in WANTED_KEYS:
                found.setdefault(reg_entry.device_id, {})[key] = reg_entry.entity_id

    bindings: dict[str, Binding] = {}
    for device_id, entities in found.items():
        if "output_home_power" not in entities or "electric_level" not in entities:
            continue  # batteries, manager and other helper devices
        device = dev_reg.async_get(device_id)
        name = device.name if device is not None and device.name else device_id
        bindings[device_id] = Binding(key=device_id, name=name, entities=entities, driver=drivers.get(name))
    return bindings, operation_entity


class ZendureController:
    """Regulation loop."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        cfg = {**entry.data, **entry.options}
        self.p1_entity: str = cfg[CONF_P1_SENSOR]
        self.command_mode: str = cfg.get(CONF_COMMAND_MODE, COMMAND_AUTO)
        self.excluded: list[str] = list(cfg.get(CONF_EXCLUDED, []))

        self.regulator = Regulator()
        self.bindings: dict[str, Binding] = {}
        self.operation_entity: str | None = None

        # settings, restored by the entities
        self.enabled = False
        self.mode = MODE_MATCHING
        self.target = 0

        # status
        self.p1: int | None = None
        self.p1_age: float | None = None
        self.p1_stale = False
        self.blocked = False
        self.safe_stopped = False
        self.decision: Decision | None = None
        self.decision_text = "Noch keine Regelung"

        self._lock = asyncio.Lock()
        self._last_run = 0.0
        self._last_discovery = 0.0
        self._pending: Any = None
        self._unsubs: list[Any] = []
        self._warned_blocked = False

    # ------------------------------------------------------------------------------------
    async def async_start(self) -> None:
        """Discover devices and start listening."""
        self.rediscover()
        self._unsubs.append(async_track_state_change_event(self.hass, [self.p1_entity], self._p1_changed))
        self._unsubs.append(async_track_time_interval(self.hass, self._watchdog, timedelta(seconds=WATCHDOG_INTERVAL)))

    async def async_stop(self) -> None:
        """Stop listening and put all devices into a safe state."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._pending is not None:
            self._pending()
            self._pending = None
        if self.enabled:
            await self.async_all_zero("Regelung beendet")

    def rediscover(self) -> None:
        """Refresh the device list of the Zendure integration."""
        self._last_discovery = time.monotonic()
        bindings, self.operation_entity = discover_devices(self.hass)
        for key, binding in bindings.items():
            if binding.name in self.excluded:
                continue
            if (old := self.bindings.get(key)) is not None:
                # keep the command history, refresh entities and driver
                old.entities = binding.entities
                old.driver = binding.driver
                old.name = binding.name
            else:
                self.bindings[key] = binding
                _LOGGER.info("Zendure device found: %s (driver: %s)", binding.name, binding.driver is not None)
        for key in list(self.bindings):
            if key not in bindings or self.bindings[key].name in self.excluded:
                self.bindings.pop(key)

    # ------------------------------------------------------------------------------------
    async def _p1_changed(self, _event: Event[EventStateChangedData]) -> None:
        self._schedule()

    async def _watchdog(self, _now: Any) -> None:
        now = time.monotonic()
        if now - self._last_discovery > DISCOVERY_INTERVAL:
            self.rediscover()
        if now - self._last_run > WATCHDOG_MAXAGE:
            await self.async_regulate()

    @callback
    def _schedule(self) -> None:
        """Run the regulation now or as soon as the minimum interval has passed."""
        if self._pending is not None:
            return
        wait = MIN_INTERVAL - (time.monotonic() - self._last_run)
        if wait <= 0:
            self.hass.async_create_task(self.async_regulate())
            return

        @callback
        def _run(_now: Any) -> None:
            self._pending = None
            self.hass.async_create_task(self.async_regulate())

        self._pending = async_call_later(self.hass, wait, _run)

    # ------------------------------------------------------------------------------------
    def _state(self, entity_id: str | None) -> Any:
        return self.hass.states.get(entity_id) if entity_id else None

    def _num(self, entity_id: str | None, default: float = 0.0) -> float:
        state = self._state(entity_id)
        try:
            return float(state.state) if state is not None else default
        except (TypeError, ValueError):
            return default

    def _read_p1(self) -> tuple[int | None, float | None]:
        state = self._state(self.p1_entity)
        if state is None:
            return None, None
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return None, None
        if state.attributes.get("unit_of_measurement") in ("kW", "kilowatt", "kilowatts"):
            value *= 1000
        reported = getattr(state, "last_reported", None) or state.last_updated
        return int(round(value)), (dt_util.utcnow() - reported).total_seconds()

    def _read_device(self, b: Binding) -> DeviceInput:
        e = b.entities
        home = self._state(e.get("output_home_power"))
        connection = self._state(e.get("connection_status"))
        online = home is not None and home.state not in ("unavailable", "unknown")
        if connection is not None:
            try:
                online = online and int(float(connection.state)) >= 10
            except (TypeError, ValueError):
                online = online and connection.state not in ("unavailable", "unknown")

        out_limit = self._state(e.get("output_limit"))
        in_limit = self._state(e.get("input_limit"))
        max_out = int(out_limit.attributes.get("max", 800)) if out_limit is not None else 800
        max_in = int(in_limit.attributes.get("max", 0)) if in_limit is not None else 0

        return DeviceInput(
            key=b.key,
            name=b.name,
            soc=self._num(e.get("electric_level")),
            min_soc=self._num(e.get("min_soc"), 10),
            soc_set=self._num(e.get("soc_set"), 100),
            max_out=max_out,
            max_in=max_in,
            ac_out=int(self._num(e.get("output_home_power"))),
            ac_in=int(self._num(e.get("grid_input_power"))),
            solar=int(self._num(e.get("solar_input_power"))),
            bypass=self._num(e.get("pass")) > 0,
            online=online,
        )

    def _verify(self, b: Binding, dev: DeviceInput, now: float) -> None:
        """Check whether the device delivers the last requested power."""
        if b.cmd is not None and dev.online and now - b.cmd_time >= VERIFY_TIME:
            expected = b.cmd
            impossible = dev.bypass or (expected < 0 and dev.full) or (expected > 0 and dev.empty and dev.solar <= SOLAR_MIN)
            if not impossible:
                allowed = max(VERIFY_TOLERANCE_MIN, int(abs(expected) * VERIFY_TOLERANCE_REL))
                if abs(expected - dev.net) > allowed:
                    if not b.not_following:
                        _LOGGER.warning("%s does not follow: requested %sW, actual %sW", b.name, expected, dev.net)
                    b.not_following = True
                    b.unresponsive_until = now + UNRESPONSIVE_TIME
                    b.cmd_time = now
        if b.not_following and now >= b.unresponsive_until:
            b.not_following = False
        dev.responsive = not b.not_following

    def _check_blocked(self) -> bool:
        state = self._state(self.operation_entity)
        blocked = state is not None and state.state not in ("off", "unavailable", "unknown")
        if blocked and not self._warned_blocked:
            persistent_notification.async_create(
                self.hass,
                "Der Zendure Manager steuert noch selbst (Betriebsmodus nicht 'Aus'). "
                "Zendure Regelung pausiert, bis der Betriebsmodus auf 'Aus' steht.",
                "Zendure Regelung",
                f"{DOMAIN}_blocked",
            )
        if not blocked and self._warned_blocked:
            persistent_notification.async_dismiss(self.hass, f"{DOMAIN}_blocked")
        self._warned_blocked = blocked
        return blocked

    # ------------------------------------------------------------------------------------
    async def async_regulate(self) -> None:
        """One regulation step."""
        async with self._lock:
            now = time.monotonic()
            self._last_run = now
            try:
                await self._regulate(now)
            except Exception:
                _LOGGER.exception("Regulation failed")
            async_dispatcher_send(self.hass, SIGNAL_UPDATE)

    async def _regulate(self, now: float) -> None:
        self.blocked = self._check_blocked()
        self.p1, self.p1_age = self._read_p1()
        inputs = []
        for b in self.bindings.values():
            dev = self._read_device(b)
            self._verify(b, dev, now)
            b.last_input = dev
            inputs.append(dev)

        if not self.enabled:
            self.decision_text = "Regelung ausgeschaltet"
            return
        if self.blocked:
            self.decision_text = "Pausiert: Zendure Manager steht nicht auf 'Aus'"
            return
        if not inputs:
            self.decision_text = "Keine Zendure-Geräte gefunden"
            return

        # stale P1: pause, and after a longer time put everything into a safe state
        if self.p1 is None or self.p1_age is None or self.p1_age > P1_STALE_AGE:
            if not self.p1_stale:
                _LOGGER.warning("P1 sensor %s is stale (%ss), regulation paused", self.p1_entity, self.p1_age)
            self.p1_stale = True
            self.decision_text = f"Pausiert: Netzsensor veraltet ({int(self.p1_age or 0)}s)"
            if self.p1_age is None or self.p1_age > P1_STALE_STOP:
                if not self.safe_stopped:
                    await self.async_all_zero("Netzsensor veraltet")
                    self.safe_stopped = True
            return
        if self.p1_stale:
            _LOGGER.warning("P1 sensor %s reports again, regulation resumed", self.p1_entity)
        self.p1_stale = False
        self.safe_stopped = False

        decision = self.regulator.step(self.p1, self.target, inputs, now, self.mode)
        self.decision = decision
        self.decision_text = decision.text
        for b in self.bindings.values():
            b.note = decision.notes.get(b.key, "")
            if b.last_input is not None and b.last_input.online:
                await self._send(b, decision.commands.get(b.key, 0), now)
        _LOGGER.info("P1 %sW target %sW demand %sW -> %s", self.p1, self.target, decision.demand, decision.text)

    # ------------------------------------------------------------------------------------
    def _use_driver(self, b: Binding) -> bool:
        if self.command_mode == COMMAND_ENTITIES:
            return False
        has_driver = b.driver is not None and hasattr(b.driver, "power_discharge") and hasattr(b.driver, "power_charge")
        if self.command_mode == COMMAND_DRIVER and not has_driver:
            _LOGGER.warning("No driver for %s, using entities", b.name)
        return has_driver

    async def _send(self, b: Binding, power: int, now: float, force: bool = False) -> None:
        driver = self._use_driver(b)
        tolerance = DRIVER_TOLERANCE if driver else ENTITY_TOLERANCE
        if not force and b.sent is not None:
            unchanged = abs(power - b.sent) < tolerance
            if unchanged and now - b.sent_time < COMMAND_REFRESH:
                return
            if not driver and now - b.sent_time < ENTITY_MIN_INTERVAL:
                return

        try:
            if driver:
                if power >= 0:
                    await b.driver.power_discharge(power)
                else:
                    await b.driver.power_charge(power)
            else:
                await self._write_entities(b, power)
        except Exception:
            _LOGGER.exception("Command for %s failed (%sW)", b.name, power)
            return

        if b.cmd is None or abs(power - b.cmd) > DRIVER_TOLERANCE:
            b.cmd_time = now
        b.cmd = power
        b.sent = power
        b.sent_time = now

    async def _write_entities(self, b: Binding, power: int) -> None:
        """Fallback: write the number/select entities of the Zendure integration."""
        e = b.entities
        mode = "output" if power >= 0 else "input"
        if (ac_mode := e.get("ac_mode")) and (state := self._state(ac_mode)) is not None and state.state != mode:
            await self.hass.services.async_call("select", "select_option", {"entity_id": ac_mode, "option": mode}, blocking=True)
        out_value = max(power, 0)
        in_value = max(-power, 0)
        for key, value in (("output_limit", out_value), ("input_limit", in_value)):
            if (entity_id := e.get(key)) is None:
                continue
            if int(self._num(entity_id, -1)) != value:
                await self.hass.services.async_call("number", "set_value", {"entity_id": entity_id, "value": value}, blocking=True)

    async def async_all_zero(self, reason: str) -> None:
        """Set all devices to 0 W."""
        _LOGGER.info("All devices to 0 W: %s", reason)
        now = time.monotonic()
        for b in self.bindings.values():
            await self._send(b, 0, now, force=True)
            b.note = "aus"
        self.regulator = Regulator()
        self.decision_text = f"Alle Geräte auf 0 W: {reason}"
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)

    async def async_set_enabled(self, enabled: bool) -> None:
        """Switch the regulation on or off."""
        if self.enabled == enabled:
            return
        self.enabled = enabled
        if not enabled:
            await self.async_all_zero("Regelung ausgeschaltet")
        else:
            self.regulator = Regulator()
            self._schedule()
