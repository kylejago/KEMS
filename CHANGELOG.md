# Changelog

## 0.6.0-alpha4

- Prevented paced battery export whenever learned demand forecasts are unavailable and the remaining battery is needed by the home.
- Added recent-load/current-load reserve fallbacks with a 10% safety margin.
- Added reserve-source, projected pre-cheap grid import, and export-paused diagnostics.
- Reset only the simulated financial ledger; observed learning history remains preserved.

## 0.6.0-alpha3

- Updated the proposal profile to the Fox ESS KH7 7kW inverter.
- Added paced battery export that spreads surplus energy until the next cheap period instead of discharging early in the day.
- Added a dynamic reserve for forecast house demand and a projected 10% SOC target at the next cheap-period start.
- Enforced a combined 7kW solar/battery AC output limit and a separate configurable grid-export limit.
- Corrected overnight charging so the KH7 no longer assumes a 56.42kWh battery can rise from 10% to 100% during a standard six-hour 7kW cheap window.
- Locked proposal export income to the configured fixed 12p/kWh tariff; Flux/time-of-use export rates are ignored.
- Added separate live battery-to-home and actual battery-export power entities, plus target export power, exportable energy, home reserve, hours-to-cheap, and projected-SOC entities.
- Updated live simulated flow to use the current snapshot rather than the most recent retained five-minute sample.
- Changed learning confidence to increase smoothly with elapsed observation time and data coverage.
- Withheld annualised ROI and payback until seven complete 24-hour observation periods are available.
- Preserved alpha2 observed history while resetting only the superseded simulated financial ledger.
- Added the full-width `kems_actual_vs_simulated.yaml` dashboard.

## 0.6.0-alpha2

- Prevented every `sensor.kems_*` and `binary_sensor.kems_*` entity from being used as an observed input source.
- Added strict source ownership validation for Octopus Energy, Octopus Intelligent, Ohme, and FoxESS Modbus.
- Removed circular mappings to simulated grid export, simulated battery power, and KEMS battery outputs.
- Rejected unrelated Stellantis EV connected, charging, and service-battery entities.
- Made official Ohme status authoritative for connected/charging state, with charging power as a safety fallback.
- Corrected the lifetime gas meter to use Octopus `current_total_consumption_kwh`.
- Added source-validation diagnostics and a dashboard warning card.
- Added regression tests proving proposal solar export cannot become observed export income.
- Started a fresh `clean_v6_alpha2` history and lifetime namespace.

## 0.6.0-alpha1

- Added clean v6 history and lifetime storage namespaces.
- Added exact automatic matching for BottlecapDave Octopus Energy, MegaKid Octopus Intelligent, and official Ohme entities.
- Added pre-install mapping of Octopus current demand to house load and grid import.
- Added safe grid import/export normalisation and raw grid diagnostics.
- Added one-click reconfiguration with optional manual review.
- Added a complete all-entities diagnostic dashboard and expanded downloadable diagnostics.

## 0.5.0-alpha3

- Fixed the KEMS options/settings flow failing with a 500 error.
- Replaced the non-serializable regular-expression validator with Home Assistant's DateSelector.
- Kept the commissioning date optional before the physical system is installed.
- Added regression tests for the options-flow schema and Hub classification.


## 0.5.0-alpha2 — ROI and lifetime ledger

- Corrected `integration_type` from `helper` to `hub`, returning KEMS to Home Assistant Integrations.
- Added a permanent all-time energy, cost, earnings, and system-value ledger independent of Recorder retention.
- Added pre-install ROI prediction using accumulated proposal-system simulation value.
- Added configurable system cost, extra costs, grants, commissioning date, maintenance, recorded repairs, inflation, degradation, discount rate, and forecast horizon.
- Added live post-install payback tracking and permanent payback-date recording.
- Added automatic **SYSTEM PAID BACK — PROFIT MODE** with net profit after investment and operating costs.
- Added lifetime electricity, gas, solar, grid, EV, battery, import-cost, export-income, and whole-home totals.
- Added baseline-without-system, avoided-import-value, and actual/simulated system-value calculations.
- Added built-in and advanced ROI/lifetime dashboards, including a filling financial battery.
- Added ROI and lifetime diagnostics and regression tests.
- Control remains excluded.

## 0.4.0-alpha1 — Proposal system simulation

- Added the 9.66 kWp, 21-panel proposal solar model with East, West, and South roof groups.
- Added the Fox ESS KH10 / 56.42 kWh battery profile and 10% reserve.
- Added Intelligent Octopus Go import handling and 12 p/kWh fixed export fallback.
- Added live and simulated grid export, export income, battery flow, solar generation, curtailment, and avoided day-rate import entities.
- Added gas discovery, conversion, daily/monthly tracking, and typical-use learning.
- Added whole-home electricity-plus-gas energy and cost comparisons.
- Fixed predicted energy until off-peak so unknown future slots use learned/current load rather than a single interval.
- Added Live-versus-Simulated desktop, built-in, portrait, and analytics dashboards.
- Added KEMS integration branding and a full brand concept asset.
- Control remains excluded.

## 0.3.0-alpha1 — Observe, Learn, Advise, Simulate

- Added automatic source discovery, retained observation history, learning profiles, explainable advice, and read-only battery simulation.
