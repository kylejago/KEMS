# Automatic source matching profile

KEMS 0.6.0-alpha2 includes deterministic matching before fuzzy discovery for:

- BottlecapDave Octopus Energy (`octopus_energy`)
- MegaKid Octopus Intelligent (`octopus_intelligent`)
- Home Assistant Ohme (`ohme`)
- FoxESS Modbus (`foxess_modbus`) when installed later

## Current pre-install mappings

KEMS detects the Octopus electricity current-demand sensor as both house load
and grid import before FoxESS is installed. It does not invent an export source.
When FoxESS Modbus becomes available, its dedicated load and grid entities take
priority over the Octopus current-demand fallback.

Ohme connection and charging states are derived from the official Ohme status
sensor. The Ohme power and vehicle-battery sensors are mapped directly.

Gas prefers the Octopus kWh cumulative sensors. The m³ sensors remain available
as a fallback and use the configured conversion factor.
