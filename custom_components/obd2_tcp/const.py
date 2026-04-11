"""Constants for OBD2 TCP integration."""

from typing import Final

DOMAIN: Final = "obd2_tcp"

CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_PROFILE: Final = "profile"
CONF_DEVICE_NAME: Final = "device_name"
CONF_FUEL_TYPE: Final = "fuel_type"
CONF_DISABLE_ELM_LOW_POWER: Final = "disable_elm_low_power"

# ELM327 programmable parameter PP0E (hex byte) — default matches common VGate iCar Wi‑Fi stock → low‑power off; see README.
DEFAULT_ELM_PP0E_HEX: Final = "7A"

# Display units (stored in config entry options)
CONF_UNIT_TEMPERATURE: Final = "temperature_unit"
CONF_UNIT_PRESSURE: Final = "pressure_unit"
CONF_UNIT_SPEED: Final = "speed_unit"
CONF_UNIT_DISTANCE: Final = "distance_unit"

UNIT_TEMP_CELSIUS: Final = "celsius"
UNIT_TEMP_FAHRENHEIT: Final = "fahrenheit"
UNIT_PRESSURE_KPA: Final = "kpa"
UNIT_PRESSURE_PSI: Final = "psi"
UNIT_PRESSURE_BAR: Final = "bar"
UNIT_SPEED_KMH: Final = "kmh"
UNIT_SPEED_MPH: Final = "mph"
UNIT_DISTANCE_KM: Final = "km"
UNIT_DISTANCE_MI: Final = "mi"

DEFAULT_PORT: Final = 35000
DEFAULT_SCAN_INTERVAL: Final = 30
DEFAULT_PROFILE: Final = "default"

# ELM327
ELM_TIMEOUT: Final = 8.0
ELM_READ_CHUNK: Final = 256
ELM_PROMPT: Final = b">"

# AT RV reports pin-16 voltage; many adapters sense through a protection diode (~0.6 V silicon).
CONF_ADAPTER_VOLTAGE_OFFSET: Final = "adapter_voltage_offset"
DEFAULT_ADAPTER_AT_RV_VOLTAGE_OFFSET_V: Final = 0.6

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

# km per mile (divide km/h by this for mph)
KPH_TO_MPH: Final = 1.60934
KMH_TO_MPH_FACTOR: Final = 1.0 / 1.60934
KPA_TO_PSI: Final = 0.1450377380072152
LITER_TO_GALLON: Final = 3.7854

PI: Final = 3.1415926535897932384626433832795

STATE_TYPE_READ: Final = 0
STATE_TYPE_CALC: Final = 1
