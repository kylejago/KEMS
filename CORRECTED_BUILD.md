# KEMS 0.6.0-alpha2 source-isolation correction

This build keeps KEMS classified as a Home Assistant hub integration and fixes
the false observed export-income feedback loop.

Key protections:

- strict integration-platform ownership for every source mapping;
- rejection of all KEMS-generated output entities as inputs;
- no observed grid export until a real FoxESS Modbus source exists;
- official Ohme status drives EV connected and charging state;
- Octopus cumulative total gas consumption drives the lifetime gas ledger;
- rejected mappings are visible in diagnostics and on the diagnostic dashboard;
- fresh history and lifetime storage under `clean_v6_alpha2`.

The manifest contains:

```json
"integration_type": "hub",
"version": "0.6.0-alpha2"
```
