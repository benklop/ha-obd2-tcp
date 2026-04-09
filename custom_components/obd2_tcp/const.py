"""Constants for OBD2 TCP integration."""

from typing import Final

DOMAIN: Final = "obd2_tcp"

CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_PROFILE: Final = "profile"
CONF_DEVICE_NAME: Final = "device_name"
CONF_FUEL_TYPE: Final = "fuel_type"

DEFAULT_PORT: Final = 35000
DEFAULT_SCAN_INTERVAL: Final = 30
DEFAULT_PROFILE: Final = "default"

# ELM327
ELM_TIMEOUT: Final = 8.0
ELM_READ_CHUNK: Final = 256
ELM_PROMPT: Final = b">"

# Fuel types (match obd.h)
FUEL_TYPE_GASOLINE: Final = 1
FUEL_TYPE_METHANOL: Final = 2
FUEL_TYPE_ETHANOL: Final = 3
FUEL_TYPE_DIESEL: Final = 4
FUEL_TYPE_LPG: Final = 5
FUEL_TYPE_CNG: Final = 6
FUEL_TYPE_PROPANE: Final = 7
FUEL_TYPE_ELECTRIC: Final = 8

AF_RATIO_GAS: Final = 17.2
AF_RATIO_GASOLINE: Final = 14.7
AF_RATIO_PROPANE: Final = 15.5
AF_RATIO_ETHANOL: Final = 9.0
AF_RATIO_METHANOL: Final = 6.4
AF_RATIO_DIESEL: Final = 14.6

DENSITY_GAS: Final = 540.0
DENSITY_GASOLINE: Final = 740.0
DENSITY_PROPANE: Final = 505.0
DENSITY_ETHANOL: Final = 789.0
DENSITY_METHANOL: Final = 792.0
DENSITY_DIESEL: Final = 830.0

KPH_TO_MPH: Final = 1.60934
LITER_TO_GALLON: Final = 3.7854

PI: Final = 3.1415926535897932384626433832795

STATE_TYPE_READ: Final = 0
STATE_TYPE_CALC: Final = 1
