# KEMS Alpha7.36 validation report

Build: `0.7.0-alpha7.36`

## Behavioural baseline

Alpha7.36 is a reporting, dashboard and managed-panel release. The proven economic/dispatch stack remains Alpha7.31 plus Alpha7.34 latest-safe-start protection and Alpha7.35 overnight reporting handover.

The release must not change:

- the 7 kW shared inverter ceiling;
- the 10% minimum SOC reserve;
- the 13-point independent shadow-command safety validator;
- strict candidate-applied replay/tracking;
- the configured overnight schedule as the only cheap-control authority;
- the real-hardware write block before commissioning.

## Alpha7.36 validation scope

The release must prove:

- manifest and coordinated bundle versions agree on `0.7.0-alpha7.36`;
- Panel6 is the expected managed firmware and is delivered by KEMS core;
- Panel6 exposes only Live Data, Battery & Solar, Full KEMS and Full KEMS Agile;
- Full KEMS Agile panel flow is generated from the final coherent `current_routing_snapshot`, including grid import/export, battery-to-home, battery export and simulated SOC;
- the legacy Panel5 compact Agile flow entity is also republished from that final snapshot during migration;
- the established managed ESPHome automatic compile, OTA and reconnect-verification path remains intact;
- the Compare page uses native observed import cost instead of a literal dash;
- Full KEMS Agile SOC falls back to the current-routing snapshot and no longer renders blank;
- genuinely uncommissioned live solar/battery/export values are labelled as awaiting hardware data rather than shown as broken calculations;
- Winner by period compares the three user-facing simulated products on the common `import cost - export income` basis for today, yesterday, seven days and 30 days;
- rolling 365-day and all-tracked Agile evidence compare Full KEMS with Full KEMS Agile without inventing unavailable Battery & Solar history;
- the Cost & ROI page separates actual measured costs from simulated costs and exposes predicted ROI plus the existing actual savings/ROI/payback ledger for post-commissioning use;
- property Web and Pi agent remain on `0.7.0-alpha7-web.13` and public Web remains IONOS SFTP delivered.

## Required automated checks

- packaged managed-dashboard current
- Alpha7.36 dashboard composition regression
- Panel6 simplified-mode and routing-parity regression
- coordinated bundle regression
- Black
- Ruff
- Pytest
- Python compile
- hassfest
- HACS

Real FoxESS writes remain blocked until commissioning passes.
