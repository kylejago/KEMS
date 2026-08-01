# KEMS clean install build 0.6.0-alpha1

This build intentionally uses a fresh internal storage namespace. A new KEMS
config entry starts with no KEMS learning or lifetime-ledger history.

Automatic discovery is tuned for:

- BottlecapDave `octopus_energy`
- MegaKid `octopus_intelligent`
- Home Assistant `ohme`
- FoxESS Modbus when installed later

The Octopus electricity `current_demand` sensor is used as both house load and
grid import before solar/battery hardware is installed. Export remains zero
unless a real export source is configured.
