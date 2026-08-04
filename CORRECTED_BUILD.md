# KEMS 0.6.0-alpha5 Power Down aware export planning

This build retains the alpha2 source-isolation protections, KH7 paced export, and alpha4 home-reserve fallbacks. It adds read-only planning for joined Octoplus Power Down / Saving Session events.

Key changes:

- discovery of both Power Down and Saving Session event names;
- joined-event detection from BottlecapDave's `joined_events` attribute;
- pre-session battery reserve for home demand and maximum useful KH7 export;
- maximum session export while respecting the 7kW inverter, discharge, and grid-export limits;
- 8 Octopoints = 1p reward conversion;
- separate fixed 12p export income and Power Down bonus;
- optional import/export baseline support for net-reduction estimates;
- baseline-incomplete diagnostics;
- preserved observed learning history;
- one-time reset of superseded simulated financial value;
- no enrolment service calls and no inverter control.

The manifest contains:

```json
"integration_type": "hub",
"version": "0.6.0-alpha5"
```
