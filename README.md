# KEMS — Kyle Energy Management System

KEMS 0.7.0-alpha2 is the pre-installation control-development lab for Home Assistant. It extends the 0.6.0-beta1 baseline into:

**Observe → Learn → Advise → Simulate → Shadow → Control**

This alpha builds and validates desired FoxESS commands, whole-house island behaviour, EPS limits, cheap charging, Power Down export, and safety interlocks. Real FoxESS writes are deliberately hard-blocked until the commissioned KH7 backend is mapped and verified on installation day.

## Development branch purpose

This package starts the post-beta `develop` branch for the 17 August commissioning target. It preserves the complete 0.6.0-beta1 monitoring/simulation fallback and adds a hardware-independent control planner plus virtual outage scenarios.

## Supported sources

KEMS automatically discovers and can manually map:

- **Octopus Energy electricity** — current/next import rates, current export rate, standing charge, off-peak state, Intelligent dispatch slots, off-peak timestamps, joined Octoplus Power Down events, and optional import/export baselines.
- **Octopus Energy gas** — gas rate, standing charge, cumulative consumption, daily consumption, and daily cost.
- **Ohme** — EV connected/charging state, charger power, and vehicle state of charge.
- **FoxESS Modbus** — house load, solar power, battery SOC/power, grid import, and grid export.

Before FoxESS is installed, KEMS automatically uses the Octopus electricity current-demand sensor for both house load and grid import. FoxESS sources take priority automatically when they become available.

## Proposal system simulation

The supplied proposal is represented as:

- 21 × DMEGC 460 W panels
- 9.66 kWp total PV
- Fox ESS KH7 7 kW hybrid inverter
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
- **Fixed export at 12 p/kWh all day** for every simulated export interval
- Intelligent Octopus Flux/time-of-use export rates are intentionally ignored

The combined simulated solar and battery AC output is capped at the KH7 limit of 7kW. A separate editable grid-export limit remains available for the final DNO approval.

At the default 95% charging efficiency, a six-hour 7kW cheap window can store about 39.9kWh. Starting from the 10% reserve, the model therefore reaches roughly 80.7% SOC by 05:30 unless extra confirmed Intelligent slots provide more charging time. KEMS no longer assumes the revised KH7 can always fill this battery from 10% to 100% in one standard cheap window.

## Octoplus Power Down session planning

KEMS discovers both BottlecapDave `octoplus_power_down_events` and `octoplus_saving_session_events` entities, so it works across the current and transitional naming used by the integration. It plans only around entries already present in `joined_events`; it never calls the join service. BottlecapDave's auto-enrol blueprint remains responsible for joining sessions.

For a joined event before the next cheap recharge, KEMS protects enough stored energy for:

- forecast household demand through the event;
- maximum useful session export within the KH7 and DNO limits;
- the normal 10% battery reserve.

During the event, solar and battery output are combined up to the 7kW inverter limit. The home is supplied first and the remaining output is exported. After the event, KEMS returns to ordinary paced export and recalculates the plan toward the next cheap period.

Reward calculations use **8 Octopoints = 1p**. Normal export income remains fixed at 12p/kWh and is reported separately from the estimated Power Down bonus. The optional Power Down import baseline is disabled by default in BottlecapDave's integration; enable it for a bonus estimate. When an export baseline exists, KEMS calculates the net baseline as import minus export.

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

### Paced battery export

- `sensor.kems_simulated_battery_to_home_power`
- `sensor.kems_simulated_battery_export_power`
- `sensor.kems_target_battery_export_power`
- `sensor.kems_exportable_battery_energy_remaining`
- `sensor.kems_battery_energy_reserved_for_home`
- `sensor.kems_hours_until_next_cheap_period`
- `sensor.kems_projected_soc_at_cheap_period_start`
- `sensor.kems_home_reserve_forecast_source`
- `sensor.kems_projected_grid_import_before_cheap_period`
- `binary_sensor.kems_battery_export_paused_for_home_reserve`
- `sensor.kems_simulation_strategy`

### Octoplus Power Down planning

- `binary_sensor.kems_power_down_session_joined`
- `binary_sensor.kems_power_down_session_active`
- `binary_sensor.kems_power_down_baseline_incomplete`
- `binary_sensor.kems_battery_reserved_for_power_down_session`
- `binary_sensor.kems_battery_export_reduced_for_power_down_session`
- `sensor.kems_next_power_down_session_start`
- `sensor.kems_next_power_down_session_end`
- `sensor.kems_power_down_session_duration`
- `sensor.kems_power_down_session_octopoints_per_kwh`
- `sensor.kems_power_down_session_bonus_rate`
- `sensor.kems_power_down_session_baseline_net_energy`
- `sensor.kems_power_down_session_battery_reserve`
- `sensor.kems_power_down_session_export_target`
- `sensor.kems_estimated_power_down_session_export`
- `sensor.kems_estimated_power_down_session_rewardable_reduction`
- `sensor.kems_estimated_power_down_session_bonus`
- `sensor.kems_estimated_power_down_session_export_income`
- `sensor.kems_estimated_power_down_session_total_income`
- `sensor.kems_simulated_power_down_session_bonus_today`

### Control Lab and island resilience

- `sensor.kems_virtual_scenario_house_load`
- `sensor.kems_virtual_scenario_solar_power`
- `sensor.kems_island_battery_status`
- `sensor.kems_island_conservation_threshold`
- `sensor.kems_island_emergency_floor`
- `binary_sensor.kems_island_battery_conservation_active`
- `sensor.kems_estimated_outage_runtime`
- `sensor.kems_control_operating_reason`
- `sensor.kems_control_blocked_reason`
- `sensor.kems_control_next_action`

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

KEMS now keeps a permanent local ledger, separate from Home Assistant Recorder retention. Before installation it waits for seven complete 24-hour observation periods, then annualises the accumulated proposal simulation value to estimate payback and discounted net value. After a commissioning date is entered in KEMS options, it switches to actual value-created tracking.

When recovered value reaches the net investment, KEMS permanently records the payback date and changes to **SYSTEM PAID BACK — PROFIT MODE**. Profit is calculated after the investment and recorded operating costs have been deducted.

The default investment is the quoted £20,995. Grants, extra installation costs, annual maintenance, and recorded repair/replacement costs are editable. Gas remains part of whole-home energy and cost reporting but is not falsely counted as a solar/battery ROI saving.

## Dashboards

The `dashboards/` directory contains ten complete dashboards:

- pre-install proposal comparison
- advanced desktop mission control, styled like the supplied reference
- built-in Live-versus-Simulated comparison
- portrait always-on wall display
- multi-tab whole-home analytics
- built-in ROI and lifetime dashboard
- advanced ROI dashboard with a filling financial battery and Profit Mode
- complete dynamic diagnostics dashboard listing every KEMS entity
- full-width actual-versus-simulated dashboard with paced-export diagnostics
- pre-installation Control Lab for scenario and safety validation

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

## Pre-installation Control Lab

The KEMS options page and `dashboards/kems_control_lab.yaml` provide interactive controls for:

- operating mode: Observe, Simulate, Shadow, or blocked Control;
- virtual scenario: normal, sunny, cloudy, high load, active Power Down, daylight outage, night outage, EPS overload, or unstable grid restoration;
- emergency-stop latch and master-control opt-in.

The controller publishes desired work mode, charge/discharge/export power, minimum SOC, EPS headroom, island energy routing, outage runtime, safety status, and a clear blocked reason. The real backend is absent by design, so `Control commands permitted` remains off in this alpha.
