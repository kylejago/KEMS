# KEMS — Kyle Energy Management System

KEMS is a read-only Home Assistant custom integration that turns existing whole-home energy entities into one explainable pipeline:

**Observe → Learn → Advise → Simulate**

The Control phase remains deliberately excluded. This build does not call Octopus, Ohme, or FoxESS services and does not write inverter or charger settings.

## Feature branch purpose

This package is prepared for:

```text
feature/roi-lifetime-ledger
```

It builds on the proposal-system simulation and adds predicted ROI, live post-install payback, automatic Profit Mode after payback, a permanent all-time energy and financial ledger, and dedicated ROI/lifetime dashboards. It also corrects the Home Assistant manifest classification from helper to hub.

## Supported sources

KEMS automatically discovers and can manually map:

- **Octopus Energy electricity** — current/next import rates, current export rate, standing charge, off-peak state, Intelligent dispatch slots, and off-peak timestamps.
- **Octopus Energy gas** — gas rate, standing charge, cumulative consumption, daily consumption, and daily cost.
- **Ohme** — EV connected/charging state, charger power, and vehicle state of charge.
- **FoxESS Modbus** — house load, solar power, battery SOC/power, grid import, and grid export.

## Proposal system simulation

The supplied proposal is represented as:

- 21 × DMEGC 460 W panels
- 9.66 kWp total PV
- Fox ESS KH10 10 kW hybrid inverter
- 2 × Fox ESS ECS4100-H7 battery stacks
- 56.42 kWh nominal battery capacity
- 50.77 kWh proposal usable capacity / 10% operating reserve
- three roof groups: East 4.14 kWp, West 4.14 kWp, South 1.38 kWp
- 8,016 kWh quoted annual solar generation
- proposal monthly generation targets and 0.938 shading factor

When live FoxESS solar data is unavailable, the simulation uses a three-array proposal solar curve. Once FoxESS Modbus is available, live solar replaces the proposal estimate automatically.

## Current tariff model

This feature is configured for:

- **Intelligent Octopus Go** import pricing read live from Home Assistant
- normal off-peak periods reported by Octopus
- extra Intelligent dispatch slots accepted as cheap only when Octopus reports a slot **and Ohme reports active charging**
- **Octopus fixed export at 12 p/kWh all day** as the simulation fallback
- a live Octopus export-rate entity takes priority when one is available

The default simulated export power limit is 10 kW. This is an editable modelling assumption, not a confirmed DNO export permission. Change it when the approved export limit is known.

## Whole-home gas tracking

KEMS records gas separately and combines it with electricity for whole-home reporting. It supports direct daily Octopus gas totals or positive deltas from a cumulative kWh/m³ meter. It adds:

- gas use and cost today
- gas use and cost this month
- typical daily gas use
- gas share of whole-home energy
- observed and simulated whole-home cost

Gas is observed rather than optimised. The simulated whole-home comparison changes electricity operation while holding the observed gas cost constant.

## Key new entities

### Live and simulated power

- `sensor.kems_grid_net_power`
- `sensor.kems_simulated_grid_net_power`
- `sensor.kems_simulated_solar_power`
- `sensor.kems_simulated_battery_power`
- `sensor.kems_simulated_house_load_power`

### Import, export, battery and solar

- `sensor.kems_observed_grid_import_today`
- `sensor.kems_observed_grid_export_today`
- `sensor.kems_observed_export_income_today`
- `sensor.kems_simulated_grid_import_today`
- `sensor.kems_simulated_grid_export_today`
- `sensor.kems_simulated_export_income_today`
- `sensor.kems_simulated_solar_generation_today`
- `sensor.kems_simulated_solar_curtailed_today`
- `sensor.kems_simulated_battery_charged_today`
- `sensor.kems_simulated_battery_to_home_today`
- `sensor.kems_simulated_battery_export_today`
- `sensor.kems_avoided_day_rate_import_today`

### Gas and whole-home energy

- `sensor.kems_gas_usage_today`
- `sensor.kems_gas_cost_today`
- `sensor.kems_gas_usage_this_month`
- `sensor.kems_gas_cost_this_month`
- `sensor.kems_typical_daily_gas_usage`
- `sensor.kems_whole_home_energy_today`
- `sensor.kems_whole_home_observed_cost_today`
- `sensor.kems_whole_home_simulated_cost_today`
- `sensor.kems_whole_home_simulated_saving_today`

## ROI and lifetime tracking

KEMS now keeps a permanent local ledger, separate from Home Assistant Recorder retention. Before installation it annualises the accumulated proposal simulation value to estimate payback and discounted net value. After a commissioning date is entered in KEMS options, it switches to actual value-created tracking.

When recovered value reaches the net investment, KEMS permanently records the payback date and changes to **SYSTEM PAID BACK — PROFIT MODE**. Profit is calculated after the investment and recorded operating costs have been deducted.

The default investment is the quoted £20,995. Grants, extra installation costs, annual maintenance, and recorded repair/replacement costs are editable. Gas remains part of whole-home energy and cost reporting but is not falsely counted as a solar/battery ROI saving.

## Dashboards

The `dashboards/` directory contains seven complete dashboards:

- advanced desktop mission control, styled like the supplied reference
- built-in Live-versus-Simulated comparison
- portrait always-on wall display
- multi-tab whole-home analytics
- built-in ROI and lifetime dashboard
- advanced ROI dashboard with a filling financial battery and Profit Mode

See `dashboards/README.md` for installation and frontend-card requirements.

## Development validation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pre_commit install
python -m black .
python -m ruff check . --fix
python -m pytest
python -m pre_commit run --all-files
```

See `START_HERE.md` for the exact GitHub Desktop workflow.
