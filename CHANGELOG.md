## 0.7.0-alpha5 — awaiting export tariff / no-export live readiness

- Added an explicit Export tariff status: Active or Not active / awaiting export tariff.
- Awaiting mode values export at 0p/kWh and overrides normal export settings without deleting the configured future export rate.
- Forces self-consumption-first simulation: solar → home → battery, then battery → home, with deliberate grid export disabled.
- Adds solar-aware cheap-period charging targets so the battery retains forecast home cover while leaving conservative PV headroom.
- Power Down remains visible but no battery/export reserve is created while paid export is unavailable; reduction can still come from avoiding import.
- Added export-tariff/no-export status, solar-to-battery flow and overnight charge-target diagnostics.
- Control Lab mirrors the policy in shadow planning but real hardware writes remain hard-blocked.
- Existing alpha4 users migrate with Export tariff status = Active so behaviour does not silently change.

## 0.7.0-alpha4 hotfix — actual lifetime reconciliation

- Makes the persisted daily ledger authoritative for observed/pre-install lifetime energy and billing totals, matching the simulated-ledger approach.
- Corrects stale-source high-water contamination such as frozen live-demand intervals that were later excluded from a day.
- Reconciles house consumption, grid import/export, solar/battery energy, gas, import/export cost and simulated totals on load and every update.
- Deliberately leaves commissioned-only actual system-value counters on their existing commissioning-gated accumulation path.
- Keeps incomplete-day flags intact rather than silently treating repaired history as complete.
- Real hardware writes remain unavailable.

## 0.7.0-alpha4 hotfix — stale live-source protection

- Detects stale live power/SOC sources using Home Assistant `State.last_reported`.
- Uses the existing configurable stale-data timeout (default 180 seconds).
- Stops integrating frozen power values into consumption, cost, learning and simulation totals.
- Marks reporting periods incomplete when stale/missing intervals reduce day coverage.
- Lowers Data Quality and exposes the exact stale logical fields and source ages.
- Makes Control Data Fresh fail safe from underlying source age, not merely the new KEMS snapshot timestamp.
- Adds source report timestamps/ages to diagnostics for troubleshooting connectivity outages.
- Real hardware writes remain unavailable.

## 0.7.0-alpha4

- Fixed blank settings-menu labels when Home Assistant or the browser retained an older custom-integration translation bundle.

# Changelog

## 0.7.0-alpha4 — guided setup and editable tariff UI

- Replaced the single oversized options form with a six-page Home Assistant Configure menu.
- Added automatic tariff mode with user-editable day-rate, off-peak-rate, standing-charge, export-rate, and cheap-period fallback values.
- Added manual tariff mode for users without a supported live tariff integration.
- Added local-time cheap-period start/end controls with correct overnight handling across midnight.
- Preserved confirmed Intelligent extra-slot safety: the cheap rate is used only when the Intelligent slot and active EV charging agree.
- Added guided first-time setup for automatic versus manual tariff selection.
- Allowed manual-tariff installations to run without a current-import-rate entity.
- Split battery, solar/export, financial, monitoring, and Control Lab settings into focused pages with descriptive selectors and units.
- Added alpha3-to-alpha4 migration defaults without changing existing automatic Octopus behaviour.
- Fixed Home Assistant 2026.8 config-flow import failure by using supported high-precision number-selector steps.
- Added tariff-resolution and UI-schema regression coverage; 107 tests pass.
- Real FoxESS and charger writes remain disabled.

## 0.7.0-alpha3 hotfix — simulated period reconciliation

- Made the persisted daily ledger authoritative for all simulated lifetime totals.
- Corrected Month, Year, and All-time export, battery-export, and export-income differences caused when intraday simulation forecasts revised downward.
- Reconciles stored alpha3 totals immediately on load and after every accumulation update without changing actual observed totals.
- Added regression coverage for daily-ledger summation and downward simulated-export revisions.
- Real FoxESS writes remain disabled.

## 0.7.0-alpha3 — KH7 topology, retained Power Down results, and accumulator repair

- Separated the 7kW battery charge/discharge limits, 7kW combined KH7 AC output limit, 7kW island/EPS limit, and an independently configurable whole-site import limit.
- Modelled grid bypass correctly so a 2kW home plus 7kW battery charge is a valid 9kW site import when the installer-confirmed site limit permits it.
- Enforced `solar AC + battery AC <= 7kW` during paced export, Power Down, high-solar operation, island operation, and restoration planning.
- Restricted EPS utilisation and warning thresholds to islanded operation; grid-connected demand now uses bypass/site-import diagnostics instead.
- Added battery-charge, total KH7 output, grid-bypass, total-site-import, limit, and headroom entities for clearer dashboards.
- Persisted a separate last-completed Power Down result after Octopus removes the live event, including SOC, planned energy, maximum output, reward estimates, EV blocking, and completion status.
- Repaired the lifetime accumulator so observed electricity, gas, import/export, and bill evidence accumulate before commissioning while actual system-created value remains commissioning-gated.
- Added native Today, Week, Month, Year, and All-time summaries with separate actual/simulated totals and explicit incomplete-day reporting.
- Prevented a mid-day commissioning change from claiming modelled value created before the physical system was commissioned.
- Added an alpha2 ledger migration that rebuilds recoverable observed totals from retained history without double-counting the temporary single-import-source mapping.
- Added accumulator health, rollover, historical-repair, site-limit, KH7-headroom, EPS-status, and retained Power Down diagnostics.
- Expanded the deterministic safety suite from 12 to 15 checks and added topology, site-import, high-solar, and island-cap regression tests.
- Real FoxESS writes remain hard-blocked: backend available, commands permitted, system commissioned, and control enable all remain off by default.

## 0.7.0-alpha2 — validated scenario fixes

- Blocked EV charging during active Power Down sessions so EV demand cannot reduce the rewardable net reduction.
- Split island battery protection into a 20% conservation threshold and a 10% emergency hardware floor.
- Continued whole-house battery support below the conservation threshold while estimating runtime down to the emergency floor.
- Stopped simulated battery discharge once the emergency floor is reached.
- Added explicit virtual-scenario solar and house-load entities so the Control Lab displays injected scenario inputs rather than the normal time-based simulation.
- Added island battery status, conservation-threshold, emergency-floor, and conservation-active diagnostics.
- Removed the aggregate header toggle from the interactive controls card to prevent accidental simultaneous switch changes.
- Added regression coverage for Power Down EV blocking, low-SOC island runtime, emergency-floor protection, and Control Lab entity selection.
- Real FoxESS writes remain hard-blocked; alpha2 is safe to run before hardware installation.

## 0.7.0-alpha1 — pre-installation control lab

- Added hardware-independent Observe, Simulate, Shadow, and Control planning modes.
- Added a virtual KH7 scenario lab for normal operation, high/low solar, high load, active Power Down, daylight/night grid outage, and unstable grid restoration.
- Added whole-house island planning: solar to house first, surplus solar to battery, battery only for the shortfall, no export, and EV charging blocked.
- Added EPS load, headroom, utilisation, warning/critical thresholds, outage-runtime estimate, and five-minute grid-restoration hold planning.
- Added desired work mode, charge, battery-to-home, battery-export, total-discharge, minimum-SOC, operating-reason, blocked-reason, and next-action entities.
- Added stale-data and emergency-stop fail-safe plans plus a 12-check built-in control preflight.
- Added a dedicated Control Lab dashboard and 11 control regression tests.
- Real FoxESS writes remain hard-blocked; alpha1 is safe to run before hardware installation.


## 0.6.0-beta1

- Consolidated all alpha1–alpha5 monitoring and simulation work into the first main-branch beta.
- Included the corrected Power Down dashboard entity IDs and regression tests.
- Retained strict observed-source isolation, KH7 7kW paced export, home-energy reserve protection, fixed 12p/kWh export, Power Down planning, smooth learning confidence, and seven-complete-day ROI gating.
- Removed generated test caches from the release package and aligned manifest, core, and Python package versions.
- Live inverter control remains disabled; this beta is the stable read-only fallback for the separate 0.7 control-development branch.

### Dashboard hotfix

- Corrected Power Down dashboard entity IDs to match the IDs Home Assistant creates from the visible entity names.
- Added duration and baseline net energy to the Actual vs Simulated Power Down card.
- Added regression checks preventing legacy `saving_session` dashboard IDs from returning.


## 0.6.0-alpha5

- Added read-only Octoplus Power Down / Saving Session awareness using BottlecapDave's joined event data.
- Discover both `power_down` and `saving_session` event/baseline entity names for compatibility across BottlecapDave releases.
- Preserve enough battery for forecast home demand and maximum useful KH7 export during a joined session before the next cheap recharge.
- Maximise session output within the 7kW inverter, 7kW battery-discharge, and configurable grid-export limits.
- Convert the joined event reward at **8 Octopoints = 1p** and keep the Power Down bonus separate from normal fixed 12p/kWh export income.
- Use optional import and export baseline sensors to estimate net baseline, rewardable reduction, bonus, and total session income.
- Added Power Down status, reserve, export-target, baseline, reward, and income entities plus dashboard diagnostics.
- KEMS remains read-only: BottlecapDave's automation handles enrolment and KEMS only reacts to events already present in `joined_events`.
- Reset only the simulated financial ledger; all observed history and learning data remain preserved.

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
