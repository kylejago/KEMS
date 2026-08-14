# KEMS — Kyle Energy Management System

KEMS 0.7.0-alpha7 is the pre-installation control-development lab for Home Assistant. It extends the 0.6.0-beta1 baseline into:

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

### Live-source freshness protection

Instantaneous house/grid/battery/solar observations are checked against Home Assistant's latest source report timestamp. If a configured live source has not reported within the Control Lab stale-data timeout (180 seconds by default), KEMS treats that reading as unavailable instead of repeatedly integrating the frozen value. Intervals touching stale live data are excluded from energy/cost accumulation, affected reporting periods are marked incomplete, Data Quality falls and identifies the stale logical fields, and the control planner enters its stale-data fail-safe. Diagnostics include each source's report time and age. Once the upstream sensor reports again, KEMS resumes automatically.

## Home Assistant setup and settings UI

Initial setup now asks whether KEMS should use automatic tariff entities or a manual tariff. After setup, open **Settings → Devices & services → KEMS → Configure** to edit one clear category at a time:

- Tariff and prices
- Battery, inverter and grid limits
- Solar, export and Power Down
- Forecast and reserve planning
- System cost and ROI
- Monitoring and history
- Control Lab and EPS safety

Each category preserves the other settings and reloads KEMS safely after saving. Source entity mappings remain available through **Reconfigure**.

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

## Awaiting Export Tariff / no-export mode

Alpha6 retains the alpha5 separation of the future export rate from whether an export tariff is actually active. Set **Export tariff status** to **Not active / awaiting export tariff** while commissioning or waiting for an export tariff. KEMS then values export at 0p/kWh, disables deliberate battery export, uses solar for the home first, stores surplus solar in the battery, curtails remaining simulated surplus, and uses battery energy for the remaining home load. During confirmed cheap periods it charges only toward a conservative solar-aware target rather than automatically filling the battery, leaving headroom for the following day's PV. Real FoxESS writes remain disabled; this behaviour is available for simulation/shadow validation first.

## What-if scenario comparison

KEMS evaluates the same retained demand and tariff observations through seven parallel scenarios without changing the active operating strategy:

- **No system** — the whole home is supplied from the grid.
- **Solar only** — solar supplies the home first and surplus is valued at the configured paid export rate.
- **Solar + battery** — conventional self-use: solar → home → battery, battery → home, no tariff-aware grid charging.
- **KEMS no-export** — the alpha5 awaiting-export strategy with solar-aware cheap charging and deliberate export disabled.
- **Full KEMS smart control** — paid export, cheap charging, home reserve, paced battery export and Power Down optimisation.
- **Full KEMS Forecast** — the same profit-first Full KEMS policy, with minimum forecast reserve protection and solar recovery only when the forward energy model predicts otherwise unnecessary day-rate import.
- **Full island mode — grid down** — the grid is unavailable for the whole replay period; EV charging is deliberately blocked, then solar and battery must serve the remaining house demand through the EPS limit, with no import or export possible.

The first six financial scenarios expose total cost including the daily standing charge, import/export, cheap/day import split, solar and battery routing, end SOC, and saving versus the No system baseline. The saving breakdown reconciles to reduced day-rate import, change in cheap-rate import, export income and Power Down income.

Full island mode is deliberately **not** included in the cheapest-scenario calculation because a grid outage is a resilience test, not a zero-cost tariff. Recorded whole-home demand remains visible, but EV charging is forced off before the EPS replay; the removed EV energy is reported separately as intentionally shed and does not count as unserved load. KEMS then reports island/EPS demand, load served, unserved energy, outage survival, starting/minimum/ending SOC, EPS-limited shortfall, energy-limited shortfall, first shortfall time and an estimated remaining runtime. The sudden-outage replay starts from the SOC Full KEMS had immediately before the selected outage period when that prior-day state is available.

The same island result also includes a **prepared outage** calculation. KEMS first checks whether 100% SOC plus the replayed solar can remove all energy-limited shortfall, then uses a binary search to find the minimum energy-secure starting SOC and adds a 5% safety margin. The prepared replay starts at no less than that target, but never assumes more than the configured EPS output. This means the result can explicitly say **EPS limited** when the battery contains enough energy but a whole-house load spike still exceeds the EPS rating, or **insufficient energy even at 100%** when no starting SOC can cover the full outage period.

KEMS also exposes Yesterday, 7-day and 30-day retained-history rollups. The Today comparison keeps six financial cumulative-cost lines and adds island load-served, unserved-energy, SOC and survival status timeline data for resilience graphs. Prepared-outage headline sensors expose the required SOC, recommended target, prepared load served and remaining shortfall.

The shipped dashboards are `kems_compare_builtin.yaml` and `kems_compare_advanced.yaml`. The advanced version uses ApexCharts and Mushroom; the built-in version requires no custom frontend cards.

### Full KEMS Forecast

Full KEMS itself remains the aggressive profit benchmark. Full KEMS Forecast adds a separate forward-looking scenario that combines Forecast.Solar with an independent Open-Meteo UKMO tilted-irradiance check and KEMS' learned house-demand profile. It calculates the physical overnight charging ceiling, the battery SOC actually required for the following day, a minimum pre-cheap SOC when the normal cheap window cannot meet that requirement, and an intraday solar-recovery target when spare PV would otherwise be exported before a predicted energy shortfall.

The planner is deliberately energy-driven rather than weather-label-driven: rain or cloud alone never blocks export. If the projected morning SOC is sufficient for the learned demand and fused solar forecast, Full KEMS Forecast stays in **normal** mode and behaves like Full KEMS. A narrow but still safe margin becomes **watch** with no export restriction. A genuine overnight recharge deficit becomes **protect**, retaining only the calculated extra stored energy. A same-day forecast deficit becomes **recovery**, routing solar to the home and battery only until the calculated target is restored, then resuming normal export. The plan is recalculated continuously as SOC, demand and forecasts change.

Open-Meteo uses the proposal's East, West and South array geometry independently and combines their hourly global-tilted-irradiance estimates behind the shared 7kW inverter limit. Forecast.Solar remains the primary daily-production forecast when available; Open-Meteo supplies the independent weather/irradiance check and hourly shape. If either provider is temporarily unavailable, KEMS degrades to the other provider or reports the forecast scenario unavailable without affecting the existing Full KEMS simulation or any control safety gate.

Weather data is provided by Open-Meteo.com. The selected UK Met Office forecast data is accessed through Open-Meteo and remains subject to the applicable attribution/share-alike terms; KEMS exposes provider attribution with the forecast diagnostics.

## User-configurable tariff model

KEMS now includes a Home Assistant **Configure** menu with a dedicated **Tariff and prices** page. Users can choose:

- **Automatic mode** — follow live Home Assistant tariff entities, with editable manual values used only when a live value is unavailable.
- **Manual mode** — always use the entered day rate, off-peak rate, standing charge, export rate, and cheap-period start/end times.

The manual schedule supports overnight periods that cross midnight. Confirmed Intelligent extra slots remain cheap only when the Intelligent slot source is active **and** the EV charger reports active charging. Export income continues to use the user-configured fixed export rate rather than Intelligent Octopus Flux/time-of-use export pricing.

The combined simulated solar and battery AC output is capped at the KH7 limit of 7kW. A separate editable grid-export limit remains available for the final DNO approval.

At the default 95% charging efficiency, a six-hour 7kW cheap window can store about 39.9kWh. Starting from the 10% reserve, the model therefore reaches roughly 80.7% SOC by 05:30 unless extra confirmed Intelligent slots provide more charging time. KEMS no longer assumes the revised KH7 can always fill this battery from 10% to 100% in one standard cheap window.

## Octoplus Power Down session planning

KEMS discovers both BottlecapDave `octoplus_power_down_events` and `octoplus_saving_session_events` entities, so it works across the current and transitional naming used by the integration. It plans only around entries already present in `joined_events`; it never calls the join service. BottlecapDave's auto-enrol blueprint remains responsible for joining sessions.

For a joined event before the next cheap recharge, KEMS protects enough stored energy for:

- forecast household demand through the event;
- maximum useful session export within the KH7 and DNO limits;
- the normal 10% battery reserve.

During the event, solar and battery output are combined up to the 7kW inverter limit. The home is supplied first and the remaining output is exported. After the event, KEMS returns to ordinary paced export and recalculates the plan toward the next cheap period.

Power Down completion auditing only judges EV blocking, plan safety and island overrides while the session is actually active. A joined/pre-session observation therefore cannot poison the final EV-block result before the event starts. The retained result also records how many active samples were observed and exposes a specific completion reason when an active safety check fails.

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
- `sensor.kems_compare_full_island_mode_today`
- `sensor.kems_compare_full_island_eps_demand_today`
- `sensor.kems_compare_full_island_ev_energy_shed_today`
- `sensor.kems_compare_full_island_prepared_status_today`
- `sensor.kems_compare_full_island_required_starting_soc_today`
- `sensor.kems_compare_full_island_prepared_target_soc_today`
- `sensor.kems_compare_full_island_prepared_load_served_today`
- `sensor.kems_compare_full_island_prepared_unserved_energy_today`
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
- `sensor.kems_today_summary`
- `sensor.kems_week_summary`
- `sensor.kems_month_summary`
- `sensor.kems_year_summary`
- `sensor.kems_all_time_summary`

## ROI and lifetime tracking

KEMS now keeps a permanent local ledger, separate from Home Assistant Recorder retention. Alpha3 accumulates observed electricity, gas, import/export, and billing evidence before installation, while keeping realised system-created value locked until commissioning. It publishes native Today, Week, Month, Year, and All-time summaries with actual and simulated figures stored separately. Missing historical days are marked incomplete instead of silently becoming zero. Before installation it waits for seven complete 24-hour observation periods, then annualises the accumulated proposal simulation value to estimate payback and discounted net value. After a commissioning date is entered in KEMS options, it switches to actual value-created tracking.

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
