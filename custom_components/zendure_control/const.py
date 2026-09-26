"""Constants for Zendure Regelung."""

from __future__ import annotations

DOMAIN = "zendure_control"
SOURCE_DOMAIN = "zendure_ha"

CONF_P1_SENSOR = "p1_sensor"
CONF_COMMAND_MODE = "command_mode"
CONF_EXCLUDED = "excluded_devices"

COMMAND_AUTO = "auto"
COMMAND_DRIVER = "driver"
COMMAND_ENTITIES = "entities"
COMMAND_MODES = [COMMAND_AUTO, COMMAND_DRIVER, COMMAND_ENTITIES]

MODE_MATCHING = "nulleinspeisung"
MODE_DISCHARGE_ONLY = "nur_entladen"
MODE_CHARGE_ONLY = "nur_laden"
MODES = [MODE_MATCHING, MODE_DISCHARGE_ONLY, MODE_CHARGE_ONLY]

SIGNAL_UPDATE = f"{DOMAIN}_update"

# --- regulation timing ---------------------------------------------------------------
MIN_INTERVAL = 3.0  # s, minimum time between two regulation runs
WATCHDOG_INTERVAL = 5  # s, watchdog period
WATCHDOG_MAXAGE = 10.0  # s, re-run the regulation if the last run is older
P1_STALE_AGE = 30.0  # s, P1 older than this is not used for regulation
P1_STALE_STOP = 120.0  # s, P1 older than this: all devices are set to 0 (safe state)
DISCOVERY_INTERVAL = 60.0  # s, rediscover the devices of the source integration

# --- command handling ------------------------------------------------------------------
DRIVER_TOLERANCE = 5  # W, change needed before a new driver command is sent
ENTITY_TOLERANCE = 10  # W, change needed before a new entity write (flash friendly)
ENTITY_MIN_INTERVAL = 5.0  # s, minimum time between entity writes per device
COMMAND_REFRESH = 30.0  # s, repeat an unchanged command after this time (keeps device automations alive)

# --- command verification --------------------------------------------------------------
VERIFY_TIME = 15.0  # s after a changed command before it is verified
VERIFY_TOLERANCE_MIN = 30  # W
VERIFY_TOLERANCE_REL = 0.2  # share of the command
UNRESPONSIVE_TIME = 60.0  # s a device is treated as "not following" after a failed check

# --- distribution ------------------------------------------------------------------------
DEADBAND = 10  # W around the target without new distribution
START_POWER = 25  # W demand needed to start the first device
SOLAR_MIN = 20  # W solar power that counts as "producing"
ADD_FACTOR = 0.8  # add a device when demand > ADD_FACTOR * capacity of active devices
REMOVE_FACTOR = 0.5  # remove a device when demand < REMOVE_FACTOR * capacity without it
REMOVE_TIME = 60.0  # s the remove condition must hold before the handover starts
RAMP_MIN = 20  # W below this a ramping device is switched off
CHARGE_THRESHOLD = 50  # W export needed before AC charging starts
CHARGE_DELAY = 20.0  # s export must last before switching from discharge to charge
