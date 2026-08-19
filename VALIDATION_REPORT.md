# KEMS Alpha7.33 validation report

Build: `0.7.0-alpha7.33`

## Behavioural baseline

Alpha7.33 is intentionally a managed-panel/display release. The economic and dispatch baseline remains Alpha7.31.

Fresh Alpha7.31 runtime evidence before this release showed:

- genuine non-zero Agile battery export selected by the optimiser;
- Feed-in First command shape for deliberate export;
- 13/13 independent shadow-command safety;
- 100% strict candidate-applied digital-twin tracking at 0.01 kW tolerance;
- combined solar + battery KH7 AC output held to the 7 kW configured limit;
- minimum 10% SOC protection retained;
- real hardware writes blocked.

## Alpha7.33 validation scope

The release must prove:

- manifest and coordinated bundle versions agree;
- property Web and Pi agent remain on `0.7.0-alpha7-web.13` without an unnecessary Web reinstall;
- the public website remains externally delivered by IONOS SFTP;
- Panel5 is the expected managed firmware and is delivered by KEMS core;
- battery export activates the battery-to-house/AC-bus connector even when `battery_to_home` is zero;
- `battery_to_home` remains a truthful separate flow rather than being overwritten for display purposes;
- the established KEMS-managed ESPHome automatic compile, OTA and reconnect verification path remains intact;
- Alpha7.31 remains the last installed Agile runtime patch, confirming Alpha7.33 does not alter optimiser/dispatch behaviour.

## Required automated checks

- packaged dashboard current
- managed Panel5 regression coverage
- Black
- Ruff
- Pytest
- Python compile
- hassfest
- HACS

Real FoxESS writes remain blocked.
