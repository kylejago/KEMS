# Changelog

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
