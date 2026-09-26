"""Distribution algorithm for Zendure Regelung.

This module has no Home Assistant dependency so it can be tested on its own.
All powers are AC powers seen from the home: positive = device feeds the home
(discharge / solar pass-through), negative = device takes power from the home (AC charge).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .const import (
    ADD_FACTOR,
    CHARGE_DELAY,
    CHARGE_THRESHOLD,
    DEADBAND,
    MODE_CHARGE_ONLY,
    MODE_DISCHARGE_ONLY,
    RAMP_MIN,
    REMOVE_FACTOR,
    REMOVE_TIME,
    SOLAR_MIN,
    START_POWER,
)


@dataclass
class DeviceInput:
    """Current state of one device."""

    key: str
    name: str
    soc: float
    min_soc: float
    soc_set: float
    max_out: int
    max_in: int
    ac_out: int
    ac_in: int
    solar: int = 0
    bypass: bool = False
    online: bool = True
    responsive: bool = True

    @property
    def net(self) -> int:
        """Actual AC power into the home."""
        return self.ac_out - self.ac_in

    @property
    def full(self) -> bool:
        return self.soc >= self.soc_set

    @property
    def empty(self) -> bool:
        return self.soc <= self.min_soc

    @property
    def can_discharge(self) -> bool:
        return self.online and self.max_out > 0 and (not self.empty or self.solar > SOLAR_MIN)

    @property
    def can_charge(self) -> bool:
        return self.online and self.max_in > 0 and not self.full

    @property
    def controllable(self) -> bool:
        return self.online and self.responsive


@dataclass
class Decision:
    """Result of one regulation step."""

    demand: int
    commands: dict[str, int] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)
    text: str = ""
    hold: bool = False


def distribute(total: int, items: list[tuple[str, float, int, int]]) -> dict[str, int]:
    """Distribute total over items (key, weight, low, high) with bounds (water filling)."""
    result: dict[str, int] = {}
    if not items:
        return result
    low_sum = sum(lo for _, _, lo, _ in items)
    if total <= low_sum:
        # not even the lower bounds can be met: share proportionally to the lower bounds
        for key, _, lo, _ in items:
            result[key] = int(total * lo / low_sum) if low_sum > 0 else 0
        return result

    open_items = list(items)
    remaining = total
    while open_items:
        weight_sum = sum(max(w, 0.001) for _, w, _, _ in open_items)
        clamped = False
        for key, w, lo, hi in list(open_items):
            share = remaining * max(w, 0.001) / weight_sum
            if share < lo or share > hi:
                value = lo if share < lo else hi
                result[key] = value
                remaining -= value
                open_items.remove((key, w, lo, hi))
                clamped = True
                break
        if not clamped:
            assigned = 0
            for key, w, _, _ in open_items:
                result[key] = int(remaining * max(w, 0.001) / weight_sum)
                assigned += result[key]
            # rounding rest to the item with the most headroom
            if (rest := remaining - assigned) and open_items:
                key, _, _, hi = max(open_items, key=lambda i: i[3] - result[i[0]])
                result[key] = min(hi, result[key] + rest)
            break
    return result


class Regulator:
    """Stateful regulation: which devices are active, handover timers, direction."""

    def __init__(self) -> None:
        self.active_out: list[str] = []
        self.active_in: list[str] = []
        self.remove_since: dict[str, float] = {}
        self.ramping: set[str] = set()
        self.export_since: float | None = None
        self.last: Decision | None = None

    # ------------------------------------------------------------------------------------
    def step(self, p1: int, target: int, devices: list[DeviceInput], now: float, mode: str) -> Decision:
        """Calculate the commands for all devices."""
        online = [d for d in devices if d.online]
        current = sum(d.net for d in online)
        demand = p1 - target + current

        # hold the last distribution inside the deadband (less chatter, flash friendly)
        if self.last is not None and abs(p1 - target) <= DEADBAND and not self.ramping:
            decision = Decision(demand=demand, commands=dict(self.last.commands), notes=dict(self.last.notes), hold=True)
            decision.text = f"Halten ({p1 - target:+d}W vom Ziel)"
            return decision

        # outputs that cannot be reduced: devices not following and devices in bypass
        fixed = sum(d.net for d in online if not d.responsive or d.bypass)
        rest = demand - fixed

        # mode limits
        if mode == MODE_DISCHARGE_ONLY:
            rest = max(rest, 0)
        elif mode == MODE_CHARGE_ONLY:
            rest = min(rest, sum(d.solar for d in online if d.responsive and not d.bypass))

        # discharge -> charge only after a stable export
        if rest < 0:
            if -rest < CHARGE_THRESHOLD:
                rest = 0
                self.export_since = None
            elif self.active_out and not self.active_in:
                self.export_since = self.export_since if self.export_since is not None else now
                if now - self.export_since < CHARGE_DELAY:
                    rest = 0
        else:
            self.export_since = None

        if rest < 0:
            decision = self._charge(rest, online, now)
        else:
            decision = self._discharge(rest + fixed, online, now)
        decision.demand = demand

        # devices that are not online get nothing
        for d in devices:
            if not d.online:
                decision.commands[d.key] = 0
                decision.notes[d.key] = "offline"

        self.last = decision
        return decision

    # ------------------------------------------------------------------------------------
    def _discharge(self, demand: int, devices: list[DeviceInput], now: float) -> Decision:
        decision = Decision(demand=demand)
        self.active_in = []
        remaining = demand

        # devices that cannot be steered: count their real output
        for d in devices:
            if not d.responsive:
                decision.commands[d.key] = d.net
                decision.notes[d.key] = f"folgt nicht (liefert {d.net})"
                remaining -= d.net

        candidates = [d for d in devices if d.controllable and d.can_discharge]
        # full devices first (their solar would be curtailed), then by state of charge
        candidates.sort(key=lambda d: (not d.full, -d.soc))
        mandatory = {d.key for d in candidates if d.full and d.solar > SOLAR_MIN}
        by_key = {d.key: d for d in candidates}

        active = [k for k in self.active_out if k in by_key]
        for k in mandatory:
            if k not in active:
                active.append(k)

        # add devices
        def capacity(keys: list[str]) -> int:
            return sum(by_key[k].max_out for k in keys)

        for d in candidates:
            if d.key in active:
                continue
            if (not active and remaining > START_POWER) or (active and remaining > ADD_FACTOR * capacity(active)):
                active.append(d.key)
                self.remove_since.pop(d.key, None)
                self.ramping.discard(d.key)

        # remove the weakest non mandatory device when the others can easily cover the demand
        active.sort(key=lambda k: (not by_key[k].full, -by_key[k].soc))
        removable = [k for k in active if k not in mandatory]
        if len(active) > 1 and removable:
            weakest = removable[-1]
            if remaining < REMOVE_FACTOR * (capacity(active) - by_key[weakest].max_out):
                since = self.remove_since.setdefault(weakest, now)
                if now - since >= REMOVE_TIME:
                    self.ramping.add(weakest)
            else:
                self.remove_since.pop(weakest, None)
                self.ramping.discard(weakest)

        # ramping devices: halve their output each step, the others take over
        for k in list(self.ramping):
            if k not in active:
                self.ramping.discard(k)
                continue
            d = by_key[k]
            power = 0 if max(d.net, 0) <= RAMP_MIN else max(d.net, 0) // 2
            decision.commands[k] = power
            decision.notes[k] = "Übergabe"
            remaining -= power
            if power == 0:
                active.remove(k)
                self.ramping.discard(k)
                self.remove_since.pop(k, None)

        # distribute the rest over the active devices
        items: list[tuple[str, float, int, int]] = []
        for k in active:
            if k in self.ramping:
                continue
            d = by_key[k]
            low = min(d.solar, d.max_out) if d.full and d.solar > SOLAR_MIN else 0
            if d.bypass:
                low = max(low, min(max(d.net, 0), d.max_out))
            items.append((k, d.max_out * max(d.soc, 1.0), low, d.max_out))
        for k, power in distribute(max(remaining, 0), items).items():
            decision.commands[k] = power
            d = by_key[k]
            decision.notes[k] = "Bypass" if d.bypass else ("entlädt" if power > 0 else "bereit")

        # everything else: off
        for d in devices:
            if d.key not in decision.commands:
                decision.commands[d.key] = 0
                decision.notes[d.key] = "aus" if d.can_discharge else ("leer" if d.empty else "aus")

        self.active_out = [k for k in active if k in decision.commands]
        decision.text = self._text("Entladen", demand, devices, decision)
        return decision

    # ------------------------------------------------------------------------------------
    def _charge(self, demand: int, devices: list[DeviceInput], now: float) -> Decision:
        decision = Decision(demand=demand)
        need = -demand
        self.active_out = []
        self.ramping.clear()

        # outputs that cannot be stopped (bypass, not following) reduce the available surplus
        for d in devices:
            if not d.responsive or d.bypass:
                decision.commands[d.key] = d.net
                decision.notes[d.key] = "Bypass" if d.bypass else f"folgt nicht (liefert {d.net})"

        candidates = [d for d in devices if d.controllable and not d.bypass and d.can_charge]
        candidates.sort(key=lambda d: d.soc)  # emptiest first
        by_key = {d.key: d for d in candidates}
        active = [k for k in self.active_in if k in by_key]

        def capacity(keys: list[str]) -> int:
            return sum(by_key[k].max_in for k in keys)

        for d in candidates:
            if d.key in active:
                continue
            if not active or need > ADD_FACTOR * capacity(active):
                active.append(d.key)

        items = [(k, by_key[k].max_in * max(100 - by_key[k].soc, 1.0), 0, by_key[k].max_in) for k in active]
        for k, power in distribute(need, items).items():
            decision.commands[k] = -power
            decision.notes[k] = "lädt" if power > 0 else "bereit"

        for d in devices:
            if d.key not in decision.commands:
                decision.commands[d.key] = 0
                decision.notes[d.key] = "voll" if d.full else "aus"

        self.active_in = active
        decision.text = self._text("Laden", demand, devices, decision)
        return decision

    @staticmethod
    def _text(label: str, demand: int, devices: list[DeviceInput], decision: Decision) -> str:
        parts = []
        for d in devices:
            power = decision.commands.get(d.key, 0)
            note = decision.notes.get(d.key, "")
            if power != 0 or note not in ("aus", "voll", "leer", "bereit"):
                parts.append(f"{d.name} {power}W ({note})")
        return f"{label} {abs(demand)}W: " + (", ".join(parts) if parts else "alle aus")
