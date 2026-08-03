# Start here — KH7 paced-export simulation

This package is prepared for:

```text
feature/kh7-paced-export-simulation
```

It is KEMS `0.6.0-alpha3`. It upgrades the proposal simulation to the revised
Fox ESS KH7 7kW inverter and paces surplus battery export toward the next cheap
period instead of exporting heavily after 05:30.

## Preserved and reset data

- Existing alpha2 observation history and learning data are preserved.
- Source mappings and observed electricity/gas data are preserved.
- The simulated financial ledger is reset once because the old 10kW
  export-first results are no longer comparable.
- The current day is recalculated immediately using the new KH7 paced-export
  model.

## Upload with GitHub Desktop

1. Switch to `develop` and pull the latest changes.
2. Create `feature/kh7-paced-export-simulation`.
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
feat: add KH7 paced battery export simulation
```

## Home Assistant update

A full uninstall is not required. After merging into `develop`:

1. Install the exact new `develop` commit SHA with `update.install`.
2. Restart Home Assistant.
3. KEMS migrates the existing entry to 7kW limits, fixed 12p export, and the
   paced-export strategy.
4. Confirm `sensor.kems_simulation_strategy` reports `paced_export`.
5. Confirm `sensor.kems_target_battery_export_power` is moderate and changes as
   the hours and forecast demand change.
6. After a standard 23:30–05:30 cheap window with no extra slots, expect the
   simulated battery to reach about 80.7% from a 10% start, not 100%.
7. Replace or add the dashboard from
   `dashboards/kems_actual_vs_simulated.yaml`.
