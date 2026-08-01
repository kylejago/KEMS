# KEMS source-isolation build 0.6.0-alpha2

This build intentionally uses a fresh internal storage namespace,
`clean_v6_alpha2`. It does not load the contaminated alpha1 observation history
or lifetime ledger.

Automatic discovery is restricted to:

- BottlecapDave `octopus_energy`
- MegaKid `octopus_intelligent`
- Home Assistant `ohme`
- FoxESS Modbus `foxess_modbus`

KEMS output entities can never be selected or retained as KEMS input sources.
Before FoxESS is installed, Octopus electricity `current_demand` is used as
both house load and grid import. Observed export stays at zero unless a genuine
FoxESS Modbus export-power source is configured.
