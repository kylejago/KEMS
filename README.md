# KEMS — Kyle Energy Management System

KEMS is a read-only Home Assistant custom integration that turns existing energy entities into one explainable pipeline:

**Observe → Learn → Advise → Simulate**

Device control is deliberately excluded from this release. KEMS never calls an Octopus, Ohme, or FoxESS service and never writes inverter or charger settings.

## Supported sources

KEMS starts with automatic discovery for:

- **Octopus Energy**: import/export prices, off-peak state, Intelligent dispatch slots, and off-peak timestamps.
- **Ohme**: charger status, EV connected/charging state, charging power, and vehicle state of charge. KEMS understands the current Ohme enum status sensor and also supports older/custom binary sensors.
- **FoxESS Modbus**: house load, battery state of charge, PV power, grid import, and grid export. Battery power is read directly when available or derived from the FoxESS Battery Voltage and Battery Current sensors.

KEMS scores entity-registry metadata, original names, unique IDs, device class, units, and source integration. High-confidence matches are preselected automatically, while the setup and reconfigure flows provide a manual fallback.

## What each phase does

### Observe

KEMS reads Home Assistant's state machine through provider adapters. Values are normalised to pence/kWh, kW, percentages, booleans, and timestamps. Standard off-peak is accepted directly; an extra Intelligent slot is treated as confirmed cheap only when Ohme also reports active charging. Compact five-minute observations are retained locally in Home Assistant storage for up to 90 days by default.

### Learn

KEMS builds weekday/weekend quarter-hour profiles for house load, solar production, grid import, and tariff rates. It reports days observed, sample count, current-slot typical load/solar, a confidence score, and predicted energy demand before the next off-peak period.

### Advise

The explainable rules engine highlights cheap charging opportunities, EV opportunities, day-rate grid import, predicted battery shortfall, solar surplus, missing tariff data, and learning progress. Advice includes a code, message, priority, confidence, and optional estimated saving.

### Simulate

KEMS replays the current day's observations through a read-only battery model. It compares observed cost and grid import with a hypothetical tariff-arbitrage strategy. Default assumptions match Kyle's planned system:

- 56.42 kWh battery capacity
- 10% reserve
- 10 kW charge/discharge power
- 95% charge and discharge efficiency
- export-first strategy outside cheap periods

All assumptions are editable in **Settings → Devices & services → KEMS → Configure**.

## Installation

1. Add `https://github.com/kylejago/KEMS` to HACS as an Integration custom repository.
2. Download KEMS and restart Home Assistant.
3. Add **KEMS** under **Settings → Devices & services**.
4. Review the automatically detected source entities and submit.

When Ohme or FoxESS Modbus is installed later, open KEMS and choose **Reconfigure**. KEMS also fills previously missing high-confidence mappings automatically at startup without replacing user choices.

## Main entities

KEMS creates source mirrors only when their source is configured, plus analysis entities such as:

- `sensor.kems_phase`
- `sensor.kems_data_quality`
- `sensor.kems_learning_confidence`
- `sensor.kems_typical_house_load_now`
- `sensor.kems_predicted_energy_until_off_peak`
- `sensor.kems_advice`
- `sensor.kems_observed_cost_today`
- `sensor.kems_simulated_kems_cost_today`
- `sensor.kems_simulated_saving_today`
- `binary_sensor.kems_cheap_period_confirmed`
- `binary_sensor.kems_learning_ready`
- `binary_sensor.kems_simulation_ready`
- `binary_sensor.kems_grid_import_outside_cheap_period`

## Development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pre_commit install
python -m black .
python -m ruff check .
python -m pytest
python -m pre_commit run --all-files
```

See `START_HERE.md`, `docs/architecture.md`, and `docs/testing-in-home-assistant.md`.

## Example dashboard

`examples/dashboard.yaml` contains a starting Lovelace dashboard. Entity IDs can differ if Home Assistant resolves a name collision, so verify them under Developer Tools → States before pasting the example.
