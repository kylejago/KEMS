# Start here — KH7 paced-export simulation

This package is prepared for:

```text
fix/home-reserve-fallback
```

It is KEMS `0.6.0-alpha4`. It keeps the Fox ESS KH7 7kW paced-export model
and fixes the home-energy reserve fallback so a missing learned forecast can
never be treated as zero demand.

## Preserved and reset data

- Existing alpha2 observation history and learning data are preserved.
- Source mappings and observed electricity/gas data are preserved.
- The simulated financial ledger is reset once because alpha3 could export
  battery energy that was still needed by the home when its forecast was missing.
- The current day is recalculated immediately using the new KH7 paced-export
  model.

## Upload with GitHub Desktop

1. Switch to `develop` and pull the latest changes.
2. Create `fix/home-reserve-fallback`.
3. Extract this ZIP elsewhere.
4. Copy everything inside its top-level folder into the repository root,
   replacing existing files but preserving the hidden `.git` directory.
5. Open the repository in VS Code.

## Local validation

```powershell
.\.venv\Scripts\Activate.ps1
python -m black .
python -m ruff check . --fix
python -m pytest
python -m pre_commit run --all-files
```

## Commit

```text
fix: protect home reserve when learning forecast is unavailable
```

## Home Assistant update

A full uninstall is not required. After merging into `develop`:

1. Install the exact new `develop` commit SHA with `update.install`.
2. Restart Home Assistant.
3. KEMS keeps the 7kW limits, fixed 12p export, and paced-export strategy.
4. Confirm `sensor.kems_simulation_strategy` reports `paced_export`.
5. Confirm `sensor.kems_home_reserve_forecast_source` reports `learned_profile`,
   `recent_average`, or `current_load`.
6. When the remaining battery is needed by the house, confirm the target and
   actual battery-export power both fall to `0.0kW` and
   `binary_sensor.kems_battery_export_paused_for_home_reserve` turns on.
7. Replace or add the dashboard from
   `dashboards/kems_actual_vs_simulated.yaml`.
