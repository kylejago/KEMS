# Start here — Octoplus Power Down aware export

This package is prepared for:

```text
feature/octoplus-power-down-aware-export
```

It is KEMS `0.6.0-alpha5`. It keeps the Fox ESS KH7 7kW paced-export and home-reserve logic, then protects battery energy for joined Octoplus Power Down sessions.

## Preserved and reset data

- Existing observation history, learning data, source mappings, and observed electricity/gas totals are preserved.
- The simulated financial ledger resets once because alpha5 adds a new higher-value session strategy and bonus calculation.
- The current day is recalculated immediately using the Power Down aware model.

## BottlecapDave prerequisites

1. Keep BottlecapDave's auto-enrol blueprint enabled so sessions are added to `joined_events`.
2. KEMS discovers both `event.octopus_energy_*_octoplus_power_down_events` and `event.octopus_energy_*_octoplus_saving_session_events`.
3. For estimated bonus values, enable the disabled-by-default Power Down import baseline sensor. Enable its export variant too when available.
4. KEMS remains read-only and does not join events or control the inverter.

## Upload with GitHub Desktop

1. Switch to `develop` and pull the latest changes.
2. Create `feature/octoplus-power-down-aware-export`.
3. Extract this ZIP elsewhere.
4. Copy everything inside its top-level folder into the repository root, replacing existing files but preserving the hidden `.git` directory.
5. Open the repository in VS Code.

## Local validation

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m black .
python -m ruff check . --fix
python -m pytest
python -m pre_commit run --all-files
```

## Commit

```text
feat: add Power Down aware battery export planning
```

## Home Assistant update

After merging into `develop`, install the exact full `develop` commit SHA with `update.install`, restart Home Assistant, and keep the KEMS config entry.

Confirm:

- `sensor.kems_simulation_strategy` is `paced_export`;
- `sensor.kems_simulation_export_rate` is `12.0`;
- `sensor.kems_source_validation` is `OK`;
- `binary_sensor.kems_saving_session_joined` turns on for a joined event;
- `binary_sensor.kems_battery_reserved_for_saving_session` turns on when the event is before the next cheap recharge;
- ordinary battery export reduces as needed;
- during the event, battery-to-home plus battery export respects the 7kW limit.
